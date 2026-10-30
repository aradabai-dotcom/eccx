#!/usr/bin/env python3
"""Compare eccx against the router ECC already ships, on blind queries.

    python3 tools/bench_vs_ecc.py [--ecc-root ~/ECC] [--out docs/…]

Two things this script refuses to do, because both were tried and both
produced a flattering number instead of a true one:

1. Compare on targets ECC cannot reach. ECC routes skills only (292 entries);
   eccx indexes 607 documents. 44 of the 60 blind queries carry at least one
   agent:/command:/rule: target, which ECC's registry does not contain at all.
   The fair comparison therefore keeps only queries where a skill is a valid
   answer and scores both arms on skills alone.
2. Report a top-1 winner without a paired test. @1 and @3 differences are
   inside the noise on this sample; only @20 clears McNemar.

Writes a markdown table on stdout and, with --out, into a docs file.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import evaluate, indexer  # noqa: E402

SETS = ("heldout", "heldout2")
KS = (1, 3, 5, 20)


def ecc_ranks(ecc_root: Path, queries: list[dict]) -> list[list[str]]:
    """Ask ECC's own router, once per eval set, via the node harness."""
    import tempfile

    ranked: list[list[str]] = []
    for name in SETS:
        with tempfile.TemporaryDirectory() as tmp:
            qfile = Path(tmp) / "q.jsonl"
            qfile.write_text(
                "\n".join(json.dumps({"q": r["q"], "expect": r.get("expect", [])})
                          for r in queries if r["set"] == name) + "\n")
            r = subprocess.run(
                ["node", str(ROOT / "tools" / "ecc_router_bench.js"), str(qfile), str(ecc_root)],
                capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"routeur ECC indisponible sous {ecc_root} : {r.stderr.strip()}")
            ranked += [row["ranked"] for row in json.loads(r.stdout)]
    return ranked


def hit(ranked, expect, k: int) -> bool:
    return any(r in expect for r in (ranked or [])[:k])


def mcnemar(a: list[bool], b: list[bool]) -> tuple[int, int, float]:
    wins = sum(1 for x, y in zip(a, b, strict=True) if y and not x)
    losses = sum(1 for x, y in zip(a, b, strict=True) if x and not y)
    n = wins + losses
    if n == 0:
        return 0, 0, 1.0
    tail = sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2 ** n
    return wins, losses, min(1.0, 2 * tail)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ecc-root", default=str(ROOT / "vendor" / "ecc"),
                    help="catalogue à mesurer (défaut : la base vendue)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    queries = []
    for name in SETS:
        for line in (ROOT / "evals" / f"{name}.jsonl").read_text().splitlines():
            if line.strip():
                queries.append({**json.loads(line), "set": name})

    ecc = ecc_ranks(Path(args.ecc_root).expanduser(), queries)
    if len(ecc) != len(queries):
        sys.exit(f"désapparié : {len(ecc)} classements ECC pour {len(queries)} requêtes")

    # équité : ne garder que les requêtes où un skill est une réponse valide
    keep = [i for i, q in enumerate(queries) if any(e.startswith("skill:") for e in q["expect"])]
    skills_only = [[e for e in queries[i]["expect"] if e.startswith("skill:")] for i in keep]

    idx = indexer.load()
    ours = evaluate.run(idx, [queries[i] for i in keep], k=max(KS), semantic=False)["rows"]
    ecc_kept = [ecc[i] for i in keep]

    lines = [f"{len(keep)} requêtes aveugles, cibles restreintes aux skills des deux côtés", "",
             "| armée | " + " | ".join(f"@{k}" for k in KS) + " |",
             "|---" * (len(KS) + 1) + "|"]
    for label, ranked in (("ECC (son routeur)", ecc_kept), ("eccx lexical", [r["ranked"] for r in ours])):
        cells = []
        for k in KS:
            got = sum(hit(r, e, k) for r, e in zip(ranked, skills_only, strict=True))
            cells.append(f"**{got}/{len(keep)}** ({got / len(keep):.0%})")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    lines += ["", "McNemar apparié (eccx vs ECC) :", "",
              "| k | gains | pertes | p |", "|---|---|---|---|"]
    for k in KS:
        a = [hit(r, e, k) for r, e in zip(ecc_kept, skills_only, strict=True)]
        b = [hit(r["ranked"], e, k) for r, e in zip(ours, skills_only, strict=True)]
        w, l, p = mcnemar(a, b)
        lines.append(f"| @{k} | {w} | {l} | {p:.3f}{' **significatif**' if p < 0.05 else ''} |")

    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
