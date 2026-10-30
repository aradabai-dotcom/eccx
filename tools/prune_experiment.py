#!/usr/bin/env python3
"""Élaguer le catalogue aide-t-il à router ? Et jusqu'où ?

Puisque le catalogue est désormais dans le dépôt (vendor/ecc/), le supprimer ou
le réduire est décidé ici. Ce script mesure ce que chaque suppression fait, au
lieu de laisser croire qu'« enlever ce qui ne sert pas » est gratuitement bon.

Deux protocoles, volontairement séparés :

  A. Élagage AVEC protection — on retire N skills au hasard, jamais une skill
     qui est la bonne réponse d'une des 60 requêtes aveugles. C'est le scénario
     « je supprime ce dont je n'ai pas besoin » : par définition, ce qu'on
     supprime n'est pas la réponse.

  B. Contrôle SANS protection — on retire N skills au hasard sur tout le
     catalogue, y compris des bonnes réponses. C'est le scénario « je supprime
     vite, sans vérifier ».

  C. Plancher — les bonnes réponses sont retirées volontairement.

(A) est la borne haute du bénéfice ; (C) montre le coût de l'erreur. Aucun des
deux n'est une prédiction : ils encadrent.

Usage : python3 tools/prune_experiment.py [--draws 5]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import indexer, router  # noqa: E402

SETS = ("heldout", "heldout2")


def load_cases() -> list[dict]:
    cases = []
    for name in SETS:
        cases += [json.loads(l) for l in (ROOT / "evals" / f"{name}.jsonl").read_text().splitlines() if l.strip()]
    return cases


def score(docs: list[dict], cases: list[dict], k: int = 1) -> int:
    sub = {"docs": docs}
    hits = 0
    for case in cases:
        ranked = router.score(sub, case["q"], kinds=None, top=20, project_context=[])
        ids = [f"{r['doc']['kind']}:{r['doc']['id']}" for r in ranked]
        if any(i in case["expect"] for i in ids[:k]):
            hits += 1
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=5, help="tirages par point de mesure")
    args = ap.parse_args()

    idx = indexer.load()
    cases = load_cases()
    n = len(cases)
    skills = [d for d in idx["docs"] if d["kind"] == "skill"]
    targets = {e.split(":", 1)[1] for c in cases for e in c["expect"] if e.startswith("skill:")}
    protected = [d for d in skills if d["id"] not in targets]

    full = score(idx["docs"], cases)
    print(f"catalogue complet : {len(idx['docs'])} documents ({len(skills)} skills), "
          f"cibles à préserver : {len(targets)}")
    print(f"  @1 = {full}/{n} ({full / n:.0%})\n")

    print("A. élagage avec protection des bonnes réponses (5 tirages par ligne)")
    rows = {}
    for cut in (50, 150, 250):
        got = []
        for seed in range(args.draws):
            drop = {d["id"] for d in random.Random(seed).sample(protected, min(cut, len(protected)))}
            got.append(score([d for d in idx["docs"] if d["id"] not in drop], cases))
        avg = sum(got) / len(got)
        rows[cut] = avg
        print(f"   −{cut:3d} skills → @1 {avg:4.1f}/{n} ({avg / n:4.0%})   tirages {got}")

    print("\nB. contrôle : mêmes coupes, sans protection")
    for cut in (150,):
        drop = {d["id"] for d in random.Random(0).sample(skills, cut)}
        print(f"   −{cut:3d} skills tirées sur tout le catalogue → @1 "
              f"{score([d for d in idx['docs'] if d['id'] not in drop], cases)}/{n}")

    print("\nC. plancher : on retire volontairement les bonnes réponses")
    gone = {d["id"] for d in skills if d["id"] in targets}
    print(f"   → @1 {score([d for d in idx['docs'] if d['id'] not in gone], cases)}/{n}")

    print("\nLecture : le gain de (A) n'existe que si ce qu'on supprime n'aurait")
    print("jamais été la bonne réponse — c'est toute la difficulté, et c'est")
    print("pourquoi docs/BASE-VENDORISEE.md impose de rejouer vos 20 tâches")
    print("réelles avant de committer une suppression.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
