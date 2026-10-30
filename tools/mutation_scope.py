#!/usr/bin/env python3
"""Which modules did this diff actually change?

Mutation testing is the only check here that can fail because a test is
*vacuous*, and it costs ~90 minutes in CI. A full run per pull request is
therefore not a gate, it is a wish. A diff-scoped run is minutes, but it is
only worth anything if the scope is computed the same way twice — hence this
module instead of a one-liner inside the shell script, and hence the tests.

    python3 tools/mutation_scope.py                  # vs origin/main
    python3 tools/mutation_scope.py --base HEAD~3    # one path per line, for shell
    python3 tools/mutation_scope.py --json           # with the reason for each drop

Two rules, both learned the hard way elsewhere in this repository:

* **The scope is the intersection with the configured mutation set**, not
  "whatever the diff touched". `cli.py` changes constantly and is deliberately
  not mutated; reporting it as scope would promise coverage that the run never
  had.
* **An empty scope is a legitimate answer, and it must be loud.** A PR that
  touched only `cli.py` or only docs has nothing to mutate; quietly running
  zero mutants and printing a green score would be the same lie as a budget
  measured on an empty corpus.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"

# Tried in order when the caller does not name a base. `origin/main` is what a
# CI checkout has after `fetch-depth: 0`; `main` is what a plain clone has;
# `HEAD~1` is the last resort that still means "the change being reviewed".
DEFAULT_BASES = ("origin/main", "main", "HEAD~1")


def parse_only_mutate(text: str) -> list[str]:
    """The `only_mutate` list from pyproject, in file order.

    Hand-parsed rather than tomllib-loaded: the script must work under the
    system python of a bare CI runner, and this keeps one dependency out of a
    gate. A regex on a literal list is honest about how little it understands —
    if the config ever grows a nested table this returns [] and the caller
    refuses.
    """
    m = re.search(r"^only_mutate\s*=\s*\[(.*?)\]", text, re.MULTILINE | re.DOTALL)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


def changed_files(base: str, ref: str = "HEAD", root: Path = ROOT) -> list[str]:
    """Paths under eccxlib/ touched between `base` and `ref`.

    `--no-renames` because a rename shows up as two unrelated paths otherwise
    and the deleted half would drag a module that no longer exists into scope.
    """
    r = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "--no-renames",
         f"{base}...{ref}", "--", "eccxlib/"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git diff {base}...{ref} a échoué : {r.stderr.strip()}")
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


def in_scope(only_mutate: list[str], changed: list[str]) -> list[str]:
    """Intersection, preserving the configured order so runs are comparable."""
    touched = set(changed)
    return [p for p in only_mutate if p in touched]


def resolve_base(candidates=DEFAULT_BASES, root: Path = ROOT) -> str | None:
    """First candidate that resolves to a commit in this repository."""
    for c in candidates:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify",
                            "--quiet", f"{c}^{{commit}}"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return c
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None,
                    help=f"référence de comparaison (défaut : {' puis '.join(DEFAULT_BASES)})")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    configured = parse_only_mutate(PYPROJECT.read_text())
    if not configured:
        print("aucune liste only_mutate lisible dans pyproject.toml — "
              "je ne peux pas déduire de portée, et deviner serait pire.",
              file=sys.stderr)
        return 2

    base = a.base or resolve_base()
    if base is None:
        print(f"aucune référence de comparaison trouvée parmi "
              f"{', '.join(DEFAULT_BASES)} — passe --base.", file=sys.stderr)
        return 2

    try:
        changed = changed_files(base, a.ref)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    scope = in_scope(configured, changed)

    if a.json:
        print(json.dumps({"base": base, "changed": changed, "scope": scope,
                          "configured": configured}, indent=1))
    else:
        for p in scope:
            print(p)
        if not scope:
            print(f"aucun module mutable touché entre {base} et {a.ref} "
                  f"(changés : {', '.join(changed) or 'rien'})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
