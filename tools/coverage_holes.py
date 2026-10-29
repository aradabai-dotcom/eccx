#!/usr/bin/env python3
"""Name every coverage hole, per function, with its enclosing def.

"A coverage number" is not actionable. "cli.py:776-824, inside cmd_gaps, no
test at all" is. This walks coverage's JSON report and attributes each missing
line to the innermost function that contains it, so the gaps can be triaged one
by one instead of averaged away.

Usage:
    python3 tools/coverage_holes.py            # table, worst first
    python3 tools/coverage_holes.py --md       # markdown, for pasting in docs
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def enclosing(path: Path) -> list[tuple[int, int, str]]:
    """(start, end, qualified name) for every def in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    spans: list[tuple[int, int, str]] = []

    def walk(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                end = getattr(child, "end_lineno", child.lineno)
                spans.append((child.lineno, end, name))
                walk(child, name + ".")
            elif isinstance(child, ast.ClassDef):
                walk(child, f"{child.name}.")
            else:
                walk(child, prefix)

    walk(tree)
    return spans


def name_for(spans, line: int) -> str:
    """Innermost function containing `line`; module level if none."""
    best = None
    for start, end, name in spans:
        if start <= line <= end:
            if best is None or (end - start) < best[0]:
                best = (end - start, name)
    return best[1] if best else "<module>"


def collect() -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out = Path(f.name)
    subprocess.run([sys.executable, "-m", "coverage", "json", "--quiet",
                    "-o", str(out)], cwd=ROOT, check=True,
                   capture_output=True)
    data = json.loads(out.read_text())
    out.unlink()

    rows = []
    for fname, info in data["files"].items():
        path = Path(fname)
        if not path.is_absolute():
            path = ROOT / path
        spans = enclosing(path)
        buckets: dict[str, list[int]] = {}
        for line in info.get("missing_lines", []):
            buckets.setdefault(name_for(spans, line), []).append(line)
        for fn, lines in buckets.items():
            rows.append({"file": Path(fname).name, "function": fn,
                         "lines": lines, "count": len(lines)})
    rows.sort(key=lambda r: -r["count"])
    return rows


def render(rows: list[dict], md: bool) -> str:
    total = sum(r["count"] for r in rows)
    if md:
        out = [f"| fichier | fonction | lignes manquantes | n |",
               "|---|---|---|---|"]
        for r in rows:
            out.append(f"| `{r['file']}` | `{r['function']}` | "
                       f"{compress(r['lines'])} | {r['count']} |")
        out.append(f"| | | **total** | **{total}** |")
        return "\n".join(out)
    width = max(len(r["function"]) for r in rows) if rows else 8
    lines = [f"{'file':<18}{'function':<{width + 2}}{'n':>4}  lines"]
    for r in rows:
        lines.append(f"{r['file']:<18}{r['function']:<{width + 2}}"
                     f"{r['count']:>4}  {compress(r['lines'])}")
    lines.append(f"\n{total} statement(s)/branch-line(s) uncovered in "
                 f"{len(rows)} function(s)")
    return "\n".join(lines)


def compress(lines: list[int]) -> str:
    """[1,2,3,7] -> '1-3, 7'"""
    out, i = [], 0
    while i < len(lines):
        j = i
        while j + 1 < len(lines) and lines[j + 1] == lines[j] + 1:
            j += 1
        out.append(str(lines[i]) if i == j else f"{lines[i]}-{lines[j]}")
        i = j + 1
    return ", ".join(out)


if __name__ == "__main__":
    print(render(collect(), "--md" in sys.argv))
