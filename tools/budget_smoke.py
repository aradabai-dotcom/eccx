#!/usr/bin/env python3
"""Budget smoke test — the promise, measured through the CLI, not the library.

Why this exists: `render_bundle(budget=400)` returned 1 684-1 768 tokens for
months and the whole suite was green, because every test called the function
with the arguments it likes best and the CLI wrapped the answer in a banner and
a roadmap that nobody counted. A unit test on the library cannot catch a
promise that the *CLI* breaks, so this measures stdout of `./eccx recall`.

Measured with `util.est_tokens` — the same counter the CLI itself uses to
enforce the budget. Measuring with a different tokenizer would let the two
disagree and the gate would pass on a lie.

Usage:
    python3 tools/budget_smoke.py              # smoke grid, exit 1 on overrun
    python3 tools/budget_smoke.py --max-ratio 1.0
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib.util import est_tokens  # noqa: E402  (same counter as the CLI)

QUERIES = [
    "debug a flaky python test",
    "secure a python api with authentication and rate limiting",
    "review this react component for accessibility",
    "set up database migrations",
    "zzz qqq unanswerable gibberish",
]
BUDGETS = [400, 1000]
K = 8


def measure(query: str, k: int, budget: int) -> tuple[int, int]:
    out = subprocess.run(
        [str(ROOT / "eccx"), "recall", query, "--k", str(k), "--budget", str(budget)],
        cwd=ROOT, capture_output=True, text=True, timeout=120)
    return est_tokens(out.stdout), out.returncode


def main(argv: list[str]) -> int:
    max_ratio = 1.0
    if "--max-ratio" in argv:
        max_ratio = float(argv[argv.index("--max-ratio") + 1])

    worst_ratio, worst = 0.0, ""
    failures = []
    print(f"{'budget':>7}  {'k':>2}  {'tokens':>6}  {'ratio':>5}  query")
    for budget in BUDGETS:
        for query in QUERIES:
            tokens, rc = measure(query, K, budget)
            ratio = tokens / budget
            print(f"{budget:>7}  {K:>2}  {tokens:>6}  {ratio:>5.2f}  {query[:44]}")
            if rc != 0:
                failures.append(f"exit {rc}: {query!r} --budget {budget}")
            if ratio > worst_ratio:
                worst_ratio, worst = ratio, f"{query!r} --budget {budget} -> {tokens}"
            if ratio > max_ratio:
                failures.append(
                    f"over budget: {query!r} --budget {budget} -> {tokens} tokens "
                    f"({ratio:.2f}x)")

    print(f"\nworst: {worst} ({worst_ratio:.2f}x)")
    if failures:
        print("\nFAIL", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("PASS  budget honoured at every measured point")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
