#!/usr/bin/env python3
"""Inspecter et mesurer un profil de catalogue.

    python3 tools/profil.py --list
    python3 tools/profil.py --show logiciel
    python3 tools/profil.py --diff logiciel      # ce qui sort du périmètre
    python3 tools/profil.py --bench logiciel     # ce que ça change au routage

`--show` vérifie au passage les noms périmés : un profil qui exclut une skill
qui n'existe plus est un profil qui ne fait rien, silencieusement. C'est le
genre d'erreur qu'on ne remarque jamais sans un contrôle dédié.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import indexer, profil, router  # noqa: E402


def cases() -> list[dict]:
    out = []
    for name in ("heldout", "heldout2"):
        out += [json.loads(l) for l in (ROOT / "evals" / f"{name}.jsonl").read_text().splitlines() if l.strip()]
    return out


def score(idx: dict, ks: tuple[int, ...]) -> dict[int, int]:
    hits = dict.fromkeys(ks, 0)
    data = cases()
    for c in data:
        ranked = [f"{r['doc']['kind']}:{r['doc']['id']}"
                  for r in router.score(idx, c["q"], kinds=None, top=max(ks), project_context=[])]
        for k in ks:
            if any(i in c["expect"] for i in ranked[:k]):
                hits[k] += 1
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--show", metavar="PROFIL")
    ap.add_argument("--diff", metavar="PROFIL")
    ap.add_argument("--bench", metavar="PROFIL")
    args = ap.parse_args()

    if args.list:
        for name in profil.available():
            p = profil.load(name)
            print(f"  {name:14s} {len(p.get('exclude', [])):3d} exclusions — {p.get('description', '')[:70]}")
        return 0

    if args.show:
        p = profil.load(args.show)
        index = indexer.load()
        d = profil.describe(index, p)
        print(f"profil {d['profil']} — {p.get('description', '')}")
        print(f"  source           : {p.get('source', '?')}")
        print(f"  documents totaux : {d['documents_totaux']}")
        print(f"  exclus demandés  : {d['exclus_demandes']}")
        print(f"  documents après  : {d['documents_apres']}")
        if d["exclus_absents_du_catalogue"]:
            print(f"  ATTENTION noms périmés : {', '.join(d['exclus_absents_du_catalogue'])}")
        else:
            print("  aucun nom périmé — chaque exclusion retire un document réel")
        for kept, why in (p.get("kept_on_purpose") or {}).items():
            print(f"  conservée exprès : {kept} — {why}")
        return 0

    if args.diff:
        p = profil.load(args.show or args.diff)
        index = indexer.load()
        drop = set(p["exclude"])
        out = [d for d in index["docs"] if d["id"] in drop]
        by_kind: dict[str, int] = {}
        for d in out:
            by_kind[d["kind"]] = by_kind.get(d["kind"], 0) + 1
        print(f"  {len(out)} documents sortent du périmètre : "
              + ", ".join(f"{k} {v}" for k, v in sorted(by_kind.items())))
        for d in out[:40]:
            print(f"    {d['kind']:8s} {d['id']}")
        if len(out) > 40:
            print(f"    … et {len(out) - 40} autres")
        return 0

    if args.bench:
        p = profil.load(args.bench)
        index = indexer.load()
        filtered = profil.apply(index, p)
        ks = (1, 3, 20)
        a = score(index, ks)
        b = score(filtered, ks)
        n = len(cases())
        print(f"  {n} requêtes aveugles\n")
        print("  | catalogue | @1 | @3 | @20 |")
        print("  |---|---|---|---|")
        print(f"  | complet ({len(index['docs'])} docs) | {a[1]}/{n} | {a[3]}/{n} | {a[20]}/{n} |")
        print(f"  | {p['id']} ({len(filtered['docs'])} docs) | {b[1]}/{n} | {b[3]}/{n} | {b[20]}/{n} |")
        print()
        if b[1] < a[1]:
            print("  Le profil DÉGRADE le rang 1 : il y a donc une bonne réponse dans")
            print("  ce qu'il écarte. À corriger avant de l'utiliser.")
        elif b[1] == a[1]:
            print("  Effet nul : le profil ne change pas le routage sur ce jeu.")
        else:
            print(f"  +{b[1] - a[1]} au rang 1, rappel ({b[20] - a[20]:+d}) — c'est un périmètre,")
            print("  pas une amélioration du routeur. Ne pas présenter autrement.")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
