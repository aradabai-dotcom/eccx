#!/usr/bin/env python3
"""Measure routing on an indexed corpus, honestly.

    python3 tools/corpus_report.py --corpus ~/notes --queries mes-requetes.jsonl

Three arms, one pass each, all paired on the same queries:

    lexical          the word-overlap router alone — no model, no download
    +sémantique      same, fused with document-level embeddings
    +sections        same, plus best-section similarity (the shipped mode)

For each arm and each depth it prints the count, a Wilson 95 % interval, and a
McNemar exact test against the lexical arm. Then it lists every query the
shipped arm gets wrong, because a number nobody can debug is a number nobody
trusts.

Why this exists as a tool and not as a script in /tmp: during the session that
built this, four separate measurements were wrong, and every one of them was
produced by a throwaway harness that had drifted from the product — a `--k`
that never reached the evaluator, a baseline that did not load section vectors,
an instrument whose two arms differed by more than the thing under test. The
fix was not care, it was putting the measurement behind the same code path the
product uses, with the arms differing by exactly one term.

Rule of the house, enforced by the shape of this file: the difference between
the arms is one boolean. If an arm needs more than that, it is a different
product, not a variant.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95 % interval. Reported because a count without an interval invites
    reading a 3-query difference as a result."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def mcnemar(a: list[bool], b: list[bool]) -> tuple[int, int, float]:
    """(wins, losses, exact two-sided p). Only the discordant pairs matter."""
    w = sum(1 for x, y in zip(a, b) if y and not x)
    l = sum(1 for x, y in zip(a, b) if x and not y)
    n = w + l
    if n == 0:
        return 0, 0, 1.0
    k = min(w, l)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return w, l, min(1.0, 2 * tail)


def load(corpus_dir: Path):
    from eccxlib import corpus, semantic
    state = Path.home() / ".eccx" / _slug(corpus_dir)
    if not (state / "index.json").exists():
        raise SystemExit(f"pas d'index pour {corpus_dir}\n  eccx corpus build --dir {corpus_dir}")
    idx = corpus.load_from(state)
    semantic.use_state(state)
    return idx, state


def _slug(p: Path) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", str(p).lower()).strip("-")[-40:]


def run_arms(idx, queries, k):
    from eccxlib import evaluate
    start = time.time()
    arms = {
        "lexical": evaluate.run(idx, queries, k=k, semantic=False)["rows"],
        "+sémantique": evaluate.run(idx, queries, k=k, semantic=True, sections=False)["rows"],
        "+sections": evaluate.run(idx, queries, k=k, semantic=True, sections=True)["rows"],
    }
    return arms, time.time() - start


def hit(row: dict, depth: int) -> bool:
    return row["rank"] is not None and row["rank"] <= depth


def report(idx, queries, arms, elapsed, depths=(1, 3, 5, 20)) -> str:
    n = len(queries)
    out = []
    out.append(f"# Mesure de routage — {idx['root']}")
    out.append("")
    docs = idx["docs"]
    n_sec = sum(len(d.get("sections") or []) for d in docs)
    out.append(f"{len(docs)} documents, {n_sec} sections, "
               f"{sum(d['body_tokens'] for d in docs):,} tokens. "
               f"{n} requêtes. {elapsed:.0f} s.")
    out.append("")
    out.append("| armée | " + " | ".join(f"@{d}" for d in depths) + " |")
    out.append("|---|" + "---|" * len(depths))
    base = arms["lexical"]
    for name, rows in arms.items():
        cells = []
        for d in depths:
            got = sum(hit(r, d) for r in rows)
            lo, hi = wilson(got, n)
            cells.append(f"**{got}/{n}** ({got/n:.1%})  *[{lo:.0%};{hi:.0%}]*")
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    out.append("")
    out.append("## Tests appariés contre l'armée lexicale")
    out.append("")
    out.append("| armée | profondeur | gains | pertes | p (McNemar exact) |")
    out.append("|---|---|---|---|---|")
    for name, rows in arms.items():
        if name == "lexical":
            continue
        for d in depths:
            a = [hit(r, d) for r in base]
            b = [hit(r, d) for r in rows]
            w, l, p = mcnemar(a, b)
            verdict = "significatif" if p < 0.05 else "non significatif"
            out.append(f"| {name} | @{d} | {w} | {l} | **{p:.4f}** — {verdict} |")
    out.append("")
    wrong = [r for r in arms["+sections"] if not hit(r, 1)]
    out.append(f"## Les {len(wrong)} requêtes où l'armée livrée n'est pas au rang 1")
    out.append("")
    out.append("À lire avant de conclure : une partie de ces échecs est défendable "
               "(une autre cible aurait convenu). C'est pourquoi la liste est là.")
    out.append("")
    for r in wrong:
        got = r["ranked"][0] if r["ranked"] else "—"
        out.append(f"- « {r['q']} »")
        out.append(f"  attendu : {', '.join(r['expect'])} — obtenu : {got}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--queries", required=True, help="jsonl: {q, expect:[ids]}")
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--out", default=None, help="markdown report path")
    ap.add_argument("--json", default=None, dest="json_out",
                    help="dump per-query ranks per arm, for a paired comparison "
                         "against an outside baseline (see tools/grep_baseline.py)")
    a = ap.parse_args()

    corpus_dir = Path(a.corpus).expanduser().resolve()
    queries = [json.loads(l) for l in open(a.queries) if l.strip()]
    idx, _ = load(corpus_dir)
    known = {f"{d['kind']}:{d['id']}" for d in idx["docs"]} | {d["id"] for d in idx["docs"]}
    missing = [(q["q"], e) for q in queries for e in q["expect"] if e not in known]
    if missing:
        print(f"{len(missing)} cible(s) absente(s) de l'index — l'index et les "
              f"requêtes ne parlent pas du même corpus :", file=sys.stderr)
        for q, e in missing[:5]:
            print(f"  « {q[:50]} » -> {e}", file=sys.stderr)
        return 2

    arms, elapsed = run_arms(idx, queries, a.k)
    md = report(idx, queries, arms, elapsed)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            {name: [{"q": r["q"], "rank": r["rank"]} for r in rows]
             for name, rows in arms.items()}, ensure_ascii=False, indent=1))
        print(f"rangs par requête: {a.json_out}")
    if a.out:
        Path(a.out).write_text(md)
        print(f"rapport: {a.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
