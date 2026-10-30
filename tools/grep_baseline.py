#!/usr/bin/env python3
"""The baseline that decides whether eccx deserves to exist for you.

    python3 tools/grep_baseline.py --corpus ~/notes --queries mes-requetes.jsonl

Searching your own markdown with `grep` is free, instant, and already
installed. Any claim that a router is worth its 130 MB has to be a claim
*against this*, not against "nothing". Two rules keep it honest:

* **The ranking is naive on purpose.** A file scores the sum of occurrences of
  the query's words. No stemming, no idf, no field weights — those are exactly
  the things the router adds, and giving them to the baseline too would measure
  the router against a copy of itself.
* **Same query file, same `expect` lists, same depths.** Anything else and the
  comparison is between two different questions.
* **Same file set as the index.** The baseline reads exactly the suffixes the
  indexer reads (`.md`, `.markdown`, `.mdx`, `.txt`), no more and no less. It
  is tempting to hand grep the whole repo — it would win more often — but then
  it would be ranking PHP sources the router was never allowed to see, and the
  two columns would no longer describe the same product decision.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# French and English function words. A grep user would type the query as-is; the
# router strips these, so leaving them in would handicap the baseline for a
# reason that has nothing to do with ranking.
STOP = set("""le la les un une des de du d l et ou où à a au aux en dans pour par sur sous
avec sans que qui quoi dont mais si ne pas plus moins très tout tous toute toutes
ce cet cette ces son sa ses leur leurs il elle ils elles on nous vous je tu me te
se y est sont être avoir a ont fait faire the a an and or of to in on for with
without is are be was were it its this that these those do does did how what
when where which who why i we you they my your our their""".split())


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", norm(s)) if len(w) > 1 and w not in STOP]


def load_corpus(root: Path) -> dict[str, str]:
    sys.path.insert(0, str(ROOT))
    from eccxlib.corpus import SUFFIXES  # single source of truth, not a copy
    docs = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SUFFIXES:
            continue
        parts = p.relative_to(root).parts
        if any(part.startswith(".") for part in parts):
            continue
        try:
            docs[p.relative_to(root).as_posix().rsplit(".", 1)[0]] = norm(
                p.read_text(errors="replace"))
        except OSError:
            continue
    return docs


def rank_grep(docs: dict[str, str], query: str, top: int) -> list[str]:
    qs = words(query)
    scored = []
    for did, text in docs.items():
        score = sum(text.count(w) for w in qs)
        if score:
            scored.append((score, did))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [d for _, d in scored[:top]]


def mcnemar(a: list[bool], b: list[bool]) -> tuple[int, int, float]:
    w = sum(1 for x, y in zip(a, b, strict=True) if y and not x)
    l = sum(1 for x, y in zip(a, b, strict=True) if x and not y)
    n = w + l
    if n == 0:
        return 0, 0, 1.0
    k = min(w, l)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return w, l, min(1.0, 2 * tail)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--queries", required=True)
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--against", default=None,
                    help="ranks JSON from corpus_report.py --json; adds the "
                         "paired test grep vs router")
    a = ap.parse_args()

    root = Path(a.corpus).expanduser().resolve()
    docs = load_corpus(root)
    cases = [json.loads(l) for l in open(a.queries) if l.strip()]
    by_path = {d: d for d in docs}
    by_tail = {}
    for d in docs:
        by_tail.setdefault(d.split("/")[-1], []).append(d)

    def resolve(expect: str) -> list[str]:
        """Accept the same ids the corpus index uses: full path without
        extension, or `kind:path`."""
        e = expect.split(":", 1)[-1]
        if e in by_path:
            return [e]
        return by_tail.get(e.split("/")[-1], [])

    ranks = []
    for c in cases:
        ranked = rank_grep(docs, c["q"], a.k)
        targets = {t for e in c["expect"] for t in resolve(e)}
        rank = next((i + 1 for i, d in enumerate(ranked) if d in targets), None)
        ranks.append({"q": c["q"], "rank": rank, "ranked": ranked[:3],
                      "expect": sorted(targets)})

    n = len(ranks)
    print(f"# grep brut — {root}")
    print(f"\n{len(docs)} documents, {n} requêtes (les mêmes que le routeur).\n")
    print("| profondeur | trouvés | taux |")
    print("|---|---|---|")
    for d in (1, 3, 5, 20):
        got = sum(1 for r in ranks if r["rank"] and r["rank"] <= d)
        print(f"| @{d} | {got}/{n} | {got/n:.1%} |")
    print("\n## Où grep échoue complètement (absent du top 20)\n")
    for r in ranks:
        if not r["rank"]:
            print(f"- « {r['q']} »")
            print(f"  attendu : {', '.join(r['expect'])}")
            print(f"  grep a vu : {', '.join(r['ranked']) or '—'}")
    if a.against:
        other = json.load(open(a.against))
        print("\n## grep contre le routeur (apparié, même requêtes)\n")
        print("| armée | profondeur | routeur mieux | grep mieux | p | verdict |")
        print("|---|---|---|---|---|---|")
        for name, rows in other.items():
            if [r["q"] for r in rows] != [r["q"] for r in ranks]:
                print(f"| {name} | — | — | — | — | **requêtes désappariées, "
                      f"comparaison refusée** |")
                continue
            for d in (1, 3, 5, 20):
                g = [bool(r["rank"] and r["rank"] <= d) for r in ranks]
                o = [bool(r["rank"] and r["rank"] <= d) for r in rows]
                wins, losses, p = mcnemar(g, o)  # wins = router-only hit
                verdict = ("routeur gagne" if p < 0.05 and wins > losses else
                           "grep gagne" if p < 0.05 and losses > wins else
                           "indistinguable")
                print(f"| {name} | @{d} | {wins} | {losses} | {p:.4f} | {verdict} |")
    json.dump([{"q": r["q"], "rank": r["rank"]} for r in ranks],
              open("/tmp/grep-ranks.json", "w"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
