#!/usr/bin/env python3
"""Deux chiffres au lieu d'un : le classement, et la couverture du vocabulaire.

Un « 45 % au rang 1 » ne dit pas si le routeur classe mal ou si le catalogue ne
parle pas la langue de la question. Ce rapport sépare les deux, par jeu :

    couverture = requêtes atteignables / requêtes       (trou de vocabulaire)
    rang @k    = réussites / requêtes atteignables      (qualité du classement)

La couverture ne se corrige pas avec des poids. Le rang ne se corrige pas avec
des alias. Tant que les deux sont additionnés, on investit au hasard.

Ce que la couverture ne couvre pas : `--assume-expect-correct` n'existe pas, et
c'est volontaire. Une requête inatteignable peut aussi signaler une **attente
fausse**. L'outil affiche les documents qui, eux, partagent des termes, pour
qu'un humain tranche.

Usage :
    python3 tools/eval_health.py                  # tous les jeux d'evals/
    python3 tools/eval_health.py --set evals/senior-dev.jsonl
    python3 tools/eval_health.py --unreachable    # la liste, avec alternatives
    python3 tools/eval_health.py --seal           # vérifie les empreintes
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import diagnose, indexer, router  # noqa: E402

SEALS = ROOT / "evals" / "SEALS.json"
SETS = ("senior-dev", "heldout", "heldout2", "fr-heldout", "en-heldout")
# Tout jeu dont le nom dit qu'il mesure, sauf deux familles :
#   routing.jsonl   — le jeu de réglage ; l'éditer est légitime, c'est son rôle ;
#   corpus-*.jsonl  — des entrées de démonstration pour le chemin `--corpus`.
# Sceller un jeu de réglage interdirait de régler ; ne pas sceller un jeu de
# mesure laisserait desserrer une porte sans trace. La frontière est le nom.
def measurable(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*.jsonl")
                  if p.stem != "routing" and not p.stem.startswith("corpus-"))


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def hits(index: dict, case: dict, k: int) -> bool:
    ids = [f"{r['doc']['kind']}:{r['doc']['id']}"
           for r in router.score(index, case["q"], top=k, project_context=[])]
    return any(e in ids for e in case["expect"])


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_seals() -> int:
    """Une empreinte par jeu, commitée. Modifier un jeu sans le resceller se voit."""
    if not SEALS.is_file():
        print(f"{SEALS} absent — lancer `python3 tools/eval_health.py --reseal`")
        return 1
    sealed = json.loads(SEALS.read_text())
    bad = []
    for name, expected in sealed.items():
        path = ROOT / name
        if not path.is_file():
            bad.append(f"{name} : fichier absent")
        elif digest(path) != expected:
            bad.append(f"{name} : empreinte différente — le jeu a changé depuis "
                       "son scellement (relire le diff avant de resceller)")
    for line in bad:
        print(f"  {line}")
    print("sceaux conformes" if not bad else f"{len(bad)} sceau(x) rompu(s)")
    return 0 if not bad else 1


def reseal() -> int:
    """Rescelle les jeux **explicitement**. Jamais appelé automatiquement.

    Un scellement automatique ne vaudrait rien : ce qui a de la valeur, c'est que
    resceller laisse une trace dans le diff, relue par quelqu'un.
    """
    table = {f"evals/{p.name}": digest(p) for p in measurable(ROOT / "evals")}
    SEALS.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n")
    print(f"{len(table)} jeu(x) scellé(s) dans {SEALS.relative_to(ROOT)}")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if "--seal" in argv:
        return check_seals()
    if "--reseal" in argv:
        return reseal()

    index = indexer.load()
    wanted = None
    if "--set" in argv:
        wanted = Path(argv[argv.index("--set") + 1])
    paths = [wanted] if wanted else [ROOT / f"evals/{n}.jsonl" for n in SETS]
    show = "--unreachable" in argv

    print(f"{'jeu':14s} {'n':>4s} {'couv.':>7s} {'atteign.':>9s} "
          f"{'@1':>11s} {'@3':>11s} {'@20':>11s}")
    print("-" * 76)
    total = {"n": 0, "reach": 0}
    for path in paths:
        if not path.is_file():
            continue
        cases = load(path)
        rep = diagnose.report(index, cases)
        reachable = [c for c, r in zip(cases, rep["rows"], strict=True)
                     if r["status"] == "reachable"]
        cells = []
        for k in (1, 3, 20):
            got = sum(1 for c in reachable if hits(index, c, k))
            cells.append(f"{got}/{len(reachable)}")
        total["n"] += rep["total"]
        total["reach"] += rep["reachable"]
        flag = "" if rep["unreachable"] == 0 and rep["missing"] == 0 else "  <<"
        print(f"{path.stem:14s} {rep['total']:4d} {rep['coverage']:6.1%} "
              f"{rep['reachable']:9d} "
              f"{cells[0]:>11s} {cells[1]:>11s} {cells[2]:>11s}{flag}")
        if show:
            for row in rep["rows"]:
                if row["status"] == "reachable":
                    continue
                why = ("cible inexistante : " + ", ".join(row["missing"])
                       if row["status"] == "missing"
                       else "aucun terme commun")
                print(f"    [{row['status']}] {row['q'][:66]}")
                print(f"        {why}")
                for alt in row.get("alternatives", []):
                    print(f"        partagerait {alt['shared']} avec {alt['key']}")

    print("-" * 76)
    print(f"{'TOTAL':14s} {total['n']:4d} {total['reach'] / max(1, total['n']):6.1%} "
          f"{total['reach']:9d}")

    # La courbe, jamais un seuil : un chiffre unique choisi après avoir vu la
    # courbe serait un paramètre réglé sur ce qu'il mesure.
    all_cases = [c for p_ in paths if p_.is_file() for c in load(p_)]
    pts = diagnose.curve(index, all_cases)
    if pts:
        print("\n=== courbe : réussite @1 selon le nombre de tokens partagés ===")
        for pt in pts:
            bar = "#" * round(20 * pt["hit"] / max(1, pt["n"]))
            print(f"  {pt['shared']:2d} token(s)  n={pt['n']:3d}  "
                  f"{pt['hit']:3d}/{pt['n']:<3d} {pt['hit'] / max(1, pt['n']):5.0%}  {bar}")
        fair = [pt for pt in pts if pt["shared"] >= 4]
        nf = sum(pt["n"] for pt in fair)
        hf = sum(pt["hit"] for pt in fair)
        if nf:
            print(f"\n  signal réel (>= 4 tokens) : {hf}/{nf} = {hf / nf:.0%}")
        thin = [pt for pt in pts if pt["shared"] <= 2]
        nt = sum(pt["n"] for pt in thin)
        ht = sum(pt["hit"] for pt in thin)
        if nt:
            print(f"  recouvrement mince (<= 2) : {ht}/{nt} = {ht / nt:.0%}"
                  "   <- cible du travail sur le vocabulaire")

    print("\nLa couverture est une propriété du vocabulaire (alias, lexique).")
    print("Le rang @k est une propriété du classement, mesuré sur ce qui est atteignable.")
    print("La courbe dit où investir : un token commun ne suffit pas à gagner.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
