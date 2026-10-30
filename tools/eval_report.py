#!/usr/bin/env python3
"""Mesurer un jeu d'évaluation, avec ou sans profil, globalement ou par langue.

    python3 tools/eval_report.py --set evals/senior-dev.jsonl
    python3 tools/eval_report.py --set evals/senior-dev.jsonl --profil logiciel
    python3 tools/eval_report.py --all                 # heldout + heldout2 + senior-dev

Chaque jeu porte ses propres cibles ; le script refuse de mesurer s'il manque
`q` ou `expect`, parce qu'un jeu mal formé rendrait un score inventé.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import indexer, profil, router  # noqa: E402

SETS = {"heldout": ("evals/heldout.jsonl", "evals/heldout2.jsonl"),
        "senior-dev": ("evals/senior-dev.jsonl",)}


def load(paths: list[str]) -> list[dict]:
    out = []
    for rel in paths:
        p = ROOT / rel
        if not p.is_file():
            sys.exit(f"jeu absent : {rel}")
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if "q" not in row or "expect" not in row:
                sys.exit(f"{rel} : ligne sans « q » ou « expect » — {line[:60]}")
            out.append(row)
    return out


def score(docs: list[dict], cases: list[dict], ks=(1, 3, 20)) -> dict[int, int]:
    hits = dict.fromkeys(ks, 0)
    for c in cases:
        ids = [f"{r['doc']['kind']}:{r['doc']['id']}"
               for r in router.score({"docs": docs}, c["q"], kinds=None, top=max(ks), project_context=[])]
        for k in ks:
            if any(i in c["expect"] for i in ids[:k]):
                hits[k] += 1
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", dest="one", help="chemin d'un .jsonl")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--profil", default=None)
    ap.add_argument("--failures", action="store_true", help="lister les échecs au rang 1")
    args = ap.parse_args()

    if args.all:
        cases, label = [], "+".join(p for v in SETS.values() for p in v)
        for v in SETS.values():
            cases += load(list(v))
    elif args.one:
        cases, label = load([args.one]), args.one
    else:
        ap.print_help()
        return 2

    idx = indexer.load()
    docs = idx["docs"]
    if args.profil:
        prof = profil.load(args.profil)
        docs = profil.apply(idx, prof)["docs"]
        label += f"  [profil {prof['id']}]"

    hits = score(docs, cases)
    n = len(cases)
    print(f"{label} — {n} requêtes, {len(docs)} documents")
    print("  " + "  ".join(f"@{k} {hits[k]}/{n} ({hits[k] / n:.0%})" for k in (1, 3, 20)))

    langs = sorted({c.get("lang") for c in cases if c.get("lang")})
    if len(langs) > 1:
        for lang in langs:
            sub = [c for c in cases if c.get("lang") == lang]
            h = score(docs, sub)
            print(f"  [{lang}] n={len(sub):2d}  @1 {h[1]}/{len(sub)}  @3 {h[3]}/{len(sub)}  @20 {h[20]}/{len(sub)}")

    if args.failures:
        print("\néchecs au rang 1 :")
        for c in cases:
            ids = [f"{r['doc']['kind']}:{r['doc']['id']}"
                   for r in router.score({"docs": docs}, c["q"], kinds=None, top=3, project_context=[])]
            if not any(i in c["expect"] for i in ids[:1]):
                where = "rang 2-3" if any(i in c["expect"] for i in ids) else "absent du top 3"
                print(f"  {c['q'][:52]:54s} → {ids[0].split(':', 1)[1]:24s} ({where})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
