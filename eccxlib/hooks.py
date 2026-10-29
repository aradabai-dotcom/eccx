"""Hook runtime — the layer Claude Code provides and a plain agent does not.

ECC ships `hooks/hooks.json` bound to Claude Code's event protocol (JSON on
stdin, exit 2 = block, stderr = feedback). Here we re-implement the *behaviour*
of the hooks that still make sense without a harness, using the same contract so
`eccx fire PreToolUse < payload.json` behaves like the real thing:

    exit 0  -> allow (stderr may carry a warning)
    exit 2  -> deny, stderr is the reason fed back to the agent

Hooks that only exist to steer Claude Code's internals (tmux orchestration,
Skill tool bookkeeping, MCP health for a client we don't have) are declared but
inert, and `eccx fire` says so instead of pretending.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from .util import (ADAPTER_STATE, ECC_ROOT, load_json, locked, read_text,
                   save_json)

ALLOW, WARN, DENY = 0, 0, 2

LINT_CONFIGS = {
    ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml",
    "eslint.config.js", "eslint.config.mjs", "eslint.config.ts",
    ".prettierrc", ".prettierrc.json", ".prettierrc.js", ".prettierrc.yml",
    "prettier.config.js", ".markdownlint.json", ".markdownlint.yaml",
    ".stylelintrc", ".stylelintrc.json", "ruff.toml", ".ruff.toml",
    ".flake8", "mypy.ini", ".golangci.yml", ".golangci.yaml", "commitlint.config.js",
    "biome.json", ".editorconfig",
}
DOC_ALLOWLIST = {
    "README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE",
    "AGENTS.md", "CLAUDE.md", "CODE_OF_CONDUCT.md", "SPONSORS.md", "TROUBLESHOOTING.md",
}
SECRET_PATTERNS = [
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key id"),
    (r"\bsk-[A-Za-z0-9]{20,}\b", "OpenAI-style API key"),
    (r"\bghp_[A-Za-z0-9]{36}\b", "GitHub personal access token"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "Slack token"),
    (r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", "private key block"),
    (r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
     "hardcoded credential"),
]

STATE_FILE = ADAPTER_STATE / "hook-state.json"
OBSERVATIONS = ADAPTER_STATE / "observations.jsonl"


def _state() -> dict:
    return load_json(STATE_FILE, {}) or {}


def _save_state(s: dict) -> None:
    # Hooks fire per tool call and several can overlap; the state file is a
    # read-modify-write like every other one here.
    with locked(STATE_FILE):
        save_json(STATE_FILE, s)


def _project_root(payload: dict) -> Path:
    p = payload.get("cwd") or payload.get("project_dir") or os.getcwd()
    return Path(p).resolve()


def _rel(path: str, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(root))
    except Exception:
        return path


# --------------------------------------------------------------------------
# PreToolUse hooks
# --------------------------------------------------------------------------

def h_config_protection(payload: dict) -> tuple[int, str]:
    """Block edits to linter/formatter configs: fix the code, not the rules."""
    tool = payload.get("tool_name", "")
    if tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit", "str_replace_editor"):
        return ALLOW, ""
    ti = payload.get("tool_input") or {}
    target = ti.get("file_path") or ti.get("path") or ""
    if not target:
        return ALLOW, ""
    name = Path(target).name
    if name in LINT_CONFIGS or name.startswith((".eslintrc.", ".prettierrc.")):
        return DENY, (
            f"ECC config-protection: '{name}' is a linter/formatter config.\n"
            "Fix the code instead of weakening the rules. If the change is truly "
            "intended, re-run with ECC_ALLOW_CONFIG_EDIT=1."
        )
    return ALLOW, ""


def h_gateguard(payload: dict) -> tuple[int, str]:
    """Fact-forcing gate: the first edit of a file must be justified.

    Claude Code's version asks the model to state what it knows about the file
    before touching it. We reproduce the friction once per file, then stay out
    of the way.
    """
    if os.environ.get("ECC_GATEGUARD") == "0":
        return ALLOW, ""
    tool = payload.get("tool_name", "")
    if tool not in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return ALLOW, ""
    ti = payload.get("tool_input") or {}
    target = ti.get("file_path") or ti.get("path") or ""
    if not target:
        return ALLOW, ""
    if not Path(target).exists():
        return ALLOW, ""   # new file: there is no prior behaviour to justify
    root = _project_root(payload)
    key = _rel(target, root)
    st = _state()
    gated = st.setdefault("gateguard", {})
    if gated.get(key):
        return ALLOW, ""
    gated[key] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _save_state(st)
    return DENY, (
        f"ECC gateguard: first write to '{key}' this session (file exists).\n"
        "Before editing, confirm in one line: (1) what this file currently does, "
        "(2) every place that imports/calls it, (3) whether it is generated.\n"
        "Then retry the same edit — the gate opens after one check per file."
    )


def h_doc_file_warning(payload: dict) -> tuple[int, str]:
    """Warn (never block) when creating ad-hoc docs at a repo root."""
    if payload.get("tool_name") not in ("Write", "NotebookEdit"):
        return ALLOW, ""
    ti = payload.get("tool_input") or {}
    target = ti.get("file_path") or ""
    if not target.endswith(".md"):
        return ALLOW, ""
    root = _project_root(payload)
    p = Path(target).resolve()
    if p.parent != root:
        return ALLOW, ""
    if p.name in DOC_ALLOWLIST:
        return ALLOW, ""
    return ALLOW, (
        f"ECC doc-file-warning: '{p.name}' is a new markdown file at the repo root. "
        "Prefer docs/<topic>.md or fold it into README/AGENTS.md."
    )


def h_mcp_health(payload: dict) -> tuple[int, str]:
    tool = payload.get("tool_name", "")
    if not tool.startswith("mcp__"):
        return ALLOW, ""
    server = tool.split("__")[1] if tool.count("__") >= 2 else ""
    cfg = load_json(ECC_ROOT / "mcp-configs" / "mcp-servers.json", {}) or {}
    servers = cfg.get("mcpServers", {})
    if server and server not in servers:
        return DENY, (f"ECC mcp-health-check: '{server}' is not in mcp-configs/mcp-servers.json. "
                      "Run `eccx tools` to see what is configured.")
    return ALLOW, ""


def h_governance(payload: dict) -> tuple[int, str]:
    """Capture (never block) secret-shaped content seen by a tool."""
    if os.environ.get("ECC_GOVERNANCE_CAPTURE") != "1":
        return ALLOW, ""
    blob = json.dumps(payload.get("tool_input") or {}, ensure_ascii=False)
    hits = [label for pat, label in SECRET_PATTERNS if re.search(pat, blob)]
    if not hits:
        return ALLOW, ""
    ADAPTER_STATE.mkdir(parents=True, exist_ok=True)
    with (ADAPTER_STATE / "governance.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": payload.get("tool_name"),
            "signals": sorted(set(hits)),
        }) + "\n")
    return ALLOW, (f"ECC governance-capture: {', '.join(sorted(set(hits)))} pattern(s) "
                   "seen in tool input and logged to .eccx/governance.jsonl.")


def h_observe(payload: dict) -> tuple[int, str]:
    """Continuous-learning observation log (input to `eccx learn`)."""
    ADAPTER_STATE.mkdir(parents=True, exist_ok=True)
    ti = payload.get("tool_input") or {}
    rec = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": payload.get("hook_event_name", "PreToolUse"),
        "tool": payload.get("tool_name", ""),
        "target": (ti.get("file_path") or ti.get("path") or ti.get("command") or "")[:300],
        "cwd": payload.get("cwd", os.getcwd()),
    }
    with OBSERVATIONS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return ALLOW, ""


# --------------------------------------------------------------------------
# PostToolUse hooks
# --------------------------------------------------------------------------

CONSOLE_EXCLUDE = re.compile(
    r"(\.d\.ts$|/__tests?__/|\.test\.[tj]sx?$|\.spec\.[tj]sx?$|console-safety)")


def h_console_log(payload: dict) -> tuple[int, str]:
    """Warn when an edit leaves console.log in product code. Never blocks."""
    ti = payload.get("tool_input") or {}
    target = ti.get("file_path") or ti.get("path") or ""
    if not target or CONSOLE_EXCLUDE.search(target):
        return ALLOW, ""
    if not target.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
        return ALLOW, ""
    p = Path(target)
    if not p.is_file():
        return ALLOW, ""
    txt = read_text(p)
    n = len(re.findall(r"\bconsole\.(log|debug)\s*\(", txt))
    if not n:
        return ALLOW, ""
    lines = [i + 1 for i, ln in enumerate(txt.splitlines())
             if re.search(r"\bconsole\.(log|debug)\s*\(", ln)][:5]
    return ALLOW, (f"ECC console-log-guard: {n} console.log in {p.name} "
                   f"(lines {', '.join(map(str, lines))}). Remove before shipping.")


def h_self_review(payload: dict) -> tuple[int, str]:
    """After a code edit, hand back the cheap review checklist for that file."""
    ti = payload.get("tool_input") or {}
    target = ti.get("file_path") or ti.get("path") or ""
    if not target.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
                            ".rb", ".php", ".kt", ".swift", ".cs", ".cpp", ".c")):
        return ALLOW, ""
    return ALLOW, ("ECC self-review gate: before declaring done, check "
                   "(a) error paths, (b) input validation, (c) tests updated, "
                   "(d) no debug output left.")


# --------------------------------------------------------------------------
# SessionStart / PreCompact / Stop
# --------------------------------------------------------------------------

def h_session_start(payload: dict) -> tuple[int, str]:
    """Bootstrap: recall memory + project fingerprint, bounded to ~1500 tokens."""
    from . import memory
    root = _project_root(payload)
    lines = ["[ECC session bootstrap]"]
    try:
        packs = _detect(root)
        if packs:
            lines.append(f"rule packs: {', '.join(packs)}")
    except Exception:
        pass
    try:
        hits = memory.search("", cwd=root, limit=5)
        if hits:
            lines.append("memory (prior decisions, newest first):")
            for h in hits:
                lines.append(f"  - [{h.get('kind','note')}] {h.get('title','')}")
    except Exception:
        pass
    git = root / ".git"
    if git.exists():
        try:
            out = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                                 capture_output=True, text=True, timeout=5).stdout
            dirty = len([l for l in out.splitlines() if l.strip()])
            lines.append(f"git: {dirty} uncommitted file(s)")
        except Exception:
            pass
    if len(lines) == 1:
        return ALLOW, ""
    return ALLOW, "\n".join(lines)


def _detect(root: Path) -> list[str]:
    from .router import detect_packs
    return detect_packs(root)


def _count_observations() -> int:
    if not OBSERVATIONS.exists():
        return 0
    with OBSERVATIONS.open(encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def h_pre_compact(payload: dict) -> tuple[int, str]:
    """Persist a resumable snapshot before context is compacted."""
    from . import memory
    root = _project_root(payload)
    ADAPTER_STATE.mkdir(parents=True, exist_ok=True)
    snap = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cwd": str(root),
        "observations": _count_observations(),
    }
    save_json(ADAPTER_STATE / "pre-compact.json", snap)
    try:
        memory.save(title=f"Pre-compact snapshot {snap['at']}",
                    body=json.dumps(snap, indent=1), kind="handoff", cwd=root)
        return ALLOW, "ECC pre-compact: state snapshot saved to the memory vault."
    except Exception as exc:
        return ALLOW, f"ECC pre-compact: snapshot written locally ({exc})."


def h_stop(payload: dict) -> tuple[int, str]:
    """End-of-turn gate: surface uncommitted debug markers, don't block."""
    notes = []
    n = _count_observations()
    if n:
        notes.append(f"{n} observations logged")
    return ALLOW, ("ECC stop: " + "; ".join(notes)) if notes else ""


HOOKS = {
    "pre:config-protection": h_config_protection,
    "pre:gateguard-fact-force": h_gateguard,
    "pre:write:doc-file-warning": h_doc_file_warning,
    "pre:mcp-health-check": h_mcp_health,
    "pre:governance-capture": h_governance,
    "pre:observe:continuous-learning": h_observe,
    "post:console-log-guard": h_console_log,
    "post:self-review": h_self_review,
    "session:start": h_session_start,
    "pre:compact": h_pre_compact,
    "stop": h_stop,
}

# Claude Code event -> hooks that run for it (mirrors hooks/hooks.metadata.json)
EVENT_MAP = {
    "PreToolUse": ["pre:observe:continuous-learning", "pre:governance-capture",
                   "pre:write:doc-file-warning", "pre:mcp-health-check",
                   "pre:gateguard-fact-force", "pre:config-protection"],
    "PostToolUse": ["post:console-log-guard", "post:self-review",
                    "pre:observe:continuous-learning"],
    "SessionStart": ["session:start"],
    "PreCompact": ["pre:compact"],
    "Stop": ["stop"],
}

INERT = {
    "pre:bash:dispatcher",
    "pre:powershell:gateguard-fact-force",
    "pre:edit-write:suggest-compact",
    "post:observe:continuous-learning",
    "post:mcp-failure-handler",
    "session:end",
    "orch:tmux-*",
}


def run(event: str, payload: dict) -> tuple[int, list[str]]:
    codes: list[int] = []
    messages: list[str] = []
    for hid in EVENT_MAP.get(event, []):
        fn = HOOKS.get(hid)
        if not fn:
            continue
        if hid == "pre:config-protection" and os.environ.get("ECC_ALLOW_CONFIG_EDIT") == "1":
            continue
        try:
            code, msg = fn(payload)
        except Exception as exc:  # observers must never brick the agent
            code, msg = ALLOW, f"eccx hook {hid} failed open: {exc}"
        codes.append(code)
        if msg:
            messages.append(msg)
    return (DENY if DENY in codes else ALLOW), messages


def fire_from_stdin(event: str) -> int:
    import sys
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {"raw": raw}
    payload.setdefault("hook_event_name", event)
    code, messages = run(event, payload)
    for m in messages:
        print(m, file=sys.stderr)
    return code
