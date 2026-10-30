#!/usr/bin/env python3
"""Audit the mutation score itself.

`mutmut` decides "survived" by running pytest against a *trampolined* module:
the mutated function is reachable through a wrapper. That wrapper is enough to
break control flow, but it hides some things from introspection — most
importantly function defaults, because `inspect.signature()` follows
`__wrapped__` back to the original.

Consequence: a mutant that changes `shortlist_k: int = 15` to `= 16` is
reported "survived" even when a test asserts that default and fails as soon as
the mutation is applied for real. The published score is therefore a **lower
bound**, and nobody can tell how much lower without checking.

This tool checks. For each survivor it:

  1. re-applies the mutant's patch as plain text to a scratch copy of the tree
     (no trampoline, no cache),
  2. runs the same fast test pool mutmut used,
  3. records whether the suite actually fails.

Three verdicts:
  killed-by-hand   the suite fails -> mutmut misclassified, score is higher
  real-survivor    the suite passes -> a genuine gap, goes in the triage doc
  broken           the patch does not apply -> the report is stale, re-run

Usage:
    python3 tools/mutation_audit.py                  # sample of 60, all files
    python3 tools/mutation_audit.py --all            # every survivor
    python3 tools/mutation_audit.py --sample 200     # bigger sample
    python3 tools/mutation_audit.py --json           # machine-readable
"""
from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns("mutants", ".git", "__pycache__", ".eccx",
                                ".coverage", "*.pyc")


def survivors() -> list[tuple[str, str]]:
    """[(mutant_name, function)] from the last mutmut run."""
    out = subprocess.run(["mutmut", "results", "--all", "true"], cwd=ROOT,
                         capture_output=True, text=True).stdout
    found = []
    for line in out.splitlines():
        m = re.match(r"^\s*(\S+__mutmut_\d+): survived\s*$", line)
        if m:
            name = m.group(1)
            fn = re.search(r"\.x_(\w+?)__mutmut_\d+$", name)
            found.append((name, fn.group(1) if fn else "?"))
    return found


def diff_for(name: str) -> str | None:
    p = subprocess.run(["mutmut", "show", name], cwd=ROOT,
                       capture_output=True, text=True)
    return p.stdout if p.returncode == 0 and p.stdout.strip() else None


def test_pool() -> list[str]:
    """The exact pytest selection mutmut uses, read from pyproject."""
    text = (ROOT / "pyproject.toml").read_text()
    m = re.search(r'"-k", "([^"]+)"', text)
    if not m:
        raise SystemExit("no pytest -k selection in pyproject.toml")
    return ["tests/test_eccx.py", "-k", m.group(1), "-q", "-p", "no:cacheprovider"]


def apply_textual(work: Path, diff: str) -> tuple[bool, list[tuple[Path, str, str]]]:
    """Apply a mutmut diff by literal replacement, not by line numbers.

    mutmut's hunk headers claim `@@ -1,6 +1,6 @@` for every mutant — the
    snippet is numbered as if it were the whole file. `patch(1)` therefore
    rejects all of them ("patch failed: 40/40" on the first version of this
    tool). The diff *body* is still exact, so the mutation is applied as a
    find-and-replace of the removed line by the added line, which is what the
    mutation means anyway.
    """
    target = None
    undo: list[tuple[Path, str, str]] = []
    minus: list[str] = []
    plus: list[str] = []
    for line in diff.splitlines():
        if line.startswith("--- "):
            if target is not None:
                if not _commit(target, minus, plus, undo):
                    return False, undo
            target = work / line[4:].strip()
            minus, plus = [], []
        elif line.startswith("+++ ") or line.startswith("@@") or line.startswith("#"):
            continue
        elif line.startswith("-"):
            minus.append(line[1:])
        elif line.startswith("+"):
            plus.append(line[1:])
    if target is not None and not _commit(target, minus, plus, undo):
        return False, undo
    return True, undo


def _commit(path: Path, minus: list[str], plus: list[str],
            undo: list) -> bool:
    if not minus and not plus:
        return True
    if len(minus) != len(plus):
        return False
    text = path.read_text(encoding="utf-8")
    for old, new in zip(minus, plus, strict=True):
        if old not in text:
            return False
        text = text.replace(old, new, 1)
        undo.append((path, old, new))
    path.write_text(text, encoding="utf-8")
    return True


def revert(undo: list[tuple[Path, str, str]]) -> None:
    for path, old, new in reversed(undo):
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(new, old, 1), encoding="utf-8")


def run_pool(where: Path, args: list[str]) -> bool:
    """True if the suite fails (i.e. the mutant is killed)."""
    p = subprocess.run(["python3", "-m", "pytest", *args], cwd=where,
                       capture_output=True, text=True)
    return p.returncode != 0


def main(argv: list[str]) -> int:
    pool = test_pool()
    found = survivors()
    if not found:
        print("no survivors listed — run tools/mutate.sh first", file=sys.stderr)
        return 2

    sample = len(found)
    if "--all" not in argv:
        n = 60
        if "--sample" in argv:
            n = int(argv[argv.index("--sample") + 1])
        sample = min(n, len(found))
    # Deterministic sample: a reproducible audit beats a random one that
    # cannot be argued about in a review.
    picked = random.Random(20261028).sample(found, sample)

    scratch = Path(tempfile.mkdtemp(prefix="mutaudit-"))
    work = scratch / "tree"
    shutil.copytree(ROOT, work, ignore=IGNORE)

    verdicts = {"killed-by-hand": [], "real-survivor": [], "broken": []}
    try:
        for i, (name, fn) in enumerate(picked, 1):
            diff = diff_for(name)
            if not diff:
                verdicts["broken"].append((name, fn, "no diff"))
                continue
            ok, undo = apply_textual(work, diff)
            if not ok:
                revert(undo)
                verdicts["broken"].append((name, fn, "does not apply"))
                continue
            try:
                killed = run_pool(work, pool)
            finally:
                revert(undo)
            verdicts["killed-by-hand" if killed else "real-survivor"].append((name, fn, ""))
            if i % 10 == 0:
                print(f"  …{i}/{len(picked)}", file=sys.stderr)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if "--json" in argv:
        print(json.dumps({k: [v[0] for v in vs] for k, vs in verdicts.items()},
                         indent=1))
        return 0

    total = sum(len(v) for v in verdicts.values())
    print(f"\naudited {total} of {len(found)} survivors "
          f"(deterministic sample, seed 20261028)\n")
    for label, key in (("killed by hand  (mutmut misclassified)", "killed-by-hand"),
                       ("real survivor   (genuine gap)", "real-survivor"),
                       ("patch failed    (stale report)", "broken")):
        print(f"  {label:<40}{len(verdicts[key]):>5}")

    ok = len(verdicts["killed-by-hand"]) + len(verdicts["real-survivor"])
    if ok:
        rate = len(verdicts["killed-by-hand"]) / ok
        print(f"\n  misclassification rate: {rate:.0%} of audited survivors")
        print("  -> the mutmut score understates the truth by roughly "
              f"{rate * 100:.0f} % of the surviving set.")

    if verdicts["real-survivor"]:
        print("\n  real survivors by function (these are the ones to test):")
        by_fn: dict[str, int] = {}
        for _name, fn, _ in verdicts["real-survivor"]:
            by_fn[fn] = by_fn.get(fn, 0) + 1
        for fn, n in sorted(by_fn.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {fn:<22}{n:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
