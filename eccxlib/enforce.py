"""Real enforcement — the structural fix for "hooks only run if the agent remembers".

In Claude Code the runtime fires hooks around every tool call. Here nothing does,
and `eccx fire` is advisory: it only runs when someone thinks to call it. That is
a design flaw, not a limitation of the sandbox.

Git *is* a runtime this environment really has. Its hooks fire on their own, on
every developer and every agent, whether or not anyone remembers. So the checks
that can be expressed on the staged tree (secrets, debug output, weakened lint
configs) are installed there — enforced by `git`, not by discipline.

The rest (gateguard on existing files, section routing) stays advisory by nature;
that boundary is stated plainly in `eccx manifest`.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

from .hooks import LINT_CONFIGS, SECRET_PATTERNS

HOOK_MARK = "# managed by eccx"

PRECOMMIT = """#!/usr/bin/env bash
__MARK__ -- edits will be overwritten by `eccx install-hooks`
# ECC checks that must not depend on the agent remembering to run them.
#
# The interpreter and script are baked in at install time: resolving `eccx` from
# PATH at commit time is how a hook silently stops enforcing. If the binary is
# gone the commit is REFUSED, not waved through — a check that fails open is not
# a check. Set ECCX_HOOK_SOFT=1 to downgrade that to a warning.
set -uo pipefail
ECCX_PY="__PY__"
ECCX_SCRIPT="__SCRIPT__"
if [ ! -f "$ECCX_SCRIPT" ]; then
  echo "ECC pre-commit: $ECCX_SCRIPT is missing — enforcement cannot run." >&2
  if [ "${ECCX_HOOK_SOFT:-0}" = "1" ]; then
    echo "ECC_HOOK_SOFT=1: continuing without checks." >&2
    exit 0
  fi
  echo "Refusing the commit. Reinstall with: eccx install-hooks --force" >&2
  exit 1
fi
"$ECCX_PY" "$ECCX_SCRIPT" precommit "$@"
exit $?
"""


def git_dir(project: Path) -> Path | None:
    try:
        out = subprocess.run(["git", "-C", str(project), "rev-parse", "--git-dir"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            return None
        d = Path(out.stdout.strip())
        return d if d.is_absolute() else (project / d)
    except Exception:
        return None


def install(project: Path, force: bool = False) -> dict:
    gd = git_dir(project)
    if not gd:
        return {"ok": False, "detail": "not a git repository"}
    hooks = gd / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    target = hooks / "pre-commit"
    if target.exists() and HOOK_MARK not in target.read_text(errors="replace") and not force:
        return {"ok": False, "detail": f"{target} exists and is not ours (use --force)"}
    import sys
    script = Path(__file__).resolve().parent.parent / "eccx"
    body = (PRECOMMIT.replace("__MARK__", HOOK_MARK)
            .replace("__PY__", sys.executable)
            .replace("__SCRIPT__", str(script)))
    target.write_text(body, encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {"ok": True, "path": str(target)}


def uninstall(project: Path) -> dict:
    gd = git_dir(project)
    if not gd:
        return {"ok": False, "detail": "not a git repository"}
    target = gd / "hooks" / "pre-commit"
    if not target.exists():
        return {"ok": True, "detail": "no hook installed"}
    if HOOK_MARK not in target.read_text(errors="replace"):
        return {"ok": False, "detail": "pre-commit is not managed by eccx; refusing to delete"}
    target.unlink()
    return {"ok": True, "detail": "removed"}


# ------------------------------------------------------------------ precommit

def _staged(project: Path) -> list[tuple[str, str]]:
    """(status, path) for staged files."""
    out = subprocess.run(["git", "-C", str(project), "diff", "--cached",
                          "--name-status", "--diff-filter=ACMR"],
                         capture_output=True, text=True, timeout=20)
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append((parts[0][0], parts[-1]))
    return rows


def _staged_content(project: Path, path: str) -> str:
    out = subprocess.run(["git", "-C", str(project), "show", f":{path}"],
                         capture_output=True, text=True, timeout=20)
    return out.stdout if out.returncode == 0 else ""


CODE_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".go", ".rs",
            ".java", ".rb", ".php", ".kt", ".swift", ".cs", ".cpp", ".c")
TEST_HINT = re.compile(r"(\.test\.|\.spec\.|/__tests__/|/tests?/|_test\.go$|test_.*\.py$)")
CONSOLE_RE = re.compile(r"\bconsole\.(log|debug)\s*\(")
# MULTILINE is load-bearing: without it `^` only matches offset 0, so a
# debugger left anywhere but the first line was never reported.
PY_DEBUG_RE = re.compile(r"^\s*(breakpoint\(\)|import\s+pdb\b)", re.MULTILINE)


def precommit(project: Path) -> tuple[int, list[str]]:
    """Blocking checks over the staged tree. Exit 1 = refuse the commit."""
    rows = _staged(project)
    if not rows:
        return 0, ["eccx: nothing staged"]

    blockers: list[str] = []
    warnings: list[str] = []

    for status, path in rows:
        name = Path(path).name
        content = _staged_content(project, path)

        # 1. Weakened lint/format configs — the ECC config-protection rule,
        #    now enforced where it actually bites.
        if name in LINT_CONFIGS or name.startswith((".eslintrc.", ".prettierrc.")):
            if os.environ.get("ECC_ALLOW_CONFIG_EDIT") != "1":
                blockers.append(f"config-protection: '{path}' modifies linter/formatter rules. "
                                "Fix the code, or re-run with ECC_ALLOW_CONFIG_EDIT=1.")

        # 2. Secrets in the added lines.
        added = "\n".join(ln[1:] for ln in content.splitlines() if ln.startswith("+"))
        for pat, label in SECRET_PATTERNS:
            if re.search(pat, added or content):
                blockers.append(f"secret-scan: possible {label} in '{path}'.")
                break

        # 3. Debug output left in product code (warning, never blocks).
        if path.endswith(CODE_EXT) and not TEST_HINT.search(path):
            if CONSOLE_RE.search(content):
                warnings.append(f"console-log: '{path}' contains console.log/debug.")
            if PY_DEBUG_RE.search(content):
                warnings.append(f"debugger: '{path}' contains breakpoint()/pdb.")

        # 4. Huge files (agent-generated blobs are usually a mistake).
        if len(content) > 400_000:
            warnings.append(f"size: '{path}' is {len(content)//1024} KiB staged.")

    for w in warnings:
        print(f"  warn  {w}", flush=True)
    if blockers:
        print("", flush=True)
        for b in blockers:
            print(f"  BLOCK {b}", flush=True)
        print("\ncommit refused by eccx pre-commit. "
              "Fix, or bypass with `git commit --no-verify`.", flush=True)
        return 1, blockers + warnings
    return 0, warnings
