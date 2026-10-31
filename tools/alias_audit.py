#!/usr/bin/env python3
"""Le registre d'alias tient-il debout contre le catalogue réel ?

Trois questions, dans cet ordre :

  1. **Validité** — chaque `kind:id` existe, chaque entrée a un `why`, aucun
     terme ne dépasse les limites. Un alias qui vise un document disparu est
     une couverture imaginaire.
  2. **Effet** — chaque terme ajoute-t-il du vocabulaire absent de la fiche ?
     Un alias dont tous les mots sont déjà dans le nom, la description ou les
     titres ne change rien. Le lexique français en contenait 22 de ce genre ;
     le premier jet de ce registre en contenait 13 sur 43.
  3. **Atteignabilité** — le terme, interrogé **seul**, ramène-t-il sa fiche
     dans le top 10 ? C'est le seul contrôle qui vérifie le mécanisme sans
     passer par un jeu d'éval : il ne dit rien de la qualité éditoriale, il dit
     que le mot conduit quelque part.

Ce que ce script ne peut pas faire : dire si un alias est *juste*. Ça se lit
dans `why`, par un humain.

Usage :
    python3 tools/alias_audit.py              # validité + effet + atteignabilité
    python3 tools/alias_audit.py --check      # code de sortie seul (porte)
    python3 tools/alias_audit.py --quiet       # une ligne de résumé
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import aliases, indexer, router  # noqa: E402

REACH_TOP = 10      # a word that cannot find its own document in the top ten is
                    # not evidence of coverage; chosen before looking at results


def reachability(index: dict, table: dict[str, list[str]]) -> list[tuple[str, str, int | None]]:
    out = []
    for key, terms in table.items():
        for term in terms:
            hits = [f"{r['doc']['kind']}:{r['doc']['id']}"
                    for r in router.score(index, term, top=REACH_TOP, project_context=[])]
            out.append((key, term, hits.index(key) + 1 if key in hits else None))
    return out


def main() -> int:
    # `--check` has no behaviour of its own: the exit code already *is* the
    # check, so the flag exists only so a gate can say what it is doing.
    quiet = "--quiet" in sys.argv or "--check" in sys.argv

    index = indexer.load()
    try:
        table = aliases.load()
    except aliases.AliasError as exc:
        print(f"registre invalide : {exc}", file=sys.stderr)
        return 2

    problems = aliases.audit(index["docs"], table)
    reach = reachability(index, table)
    unreachable = [(k, t) for k, t, rank in reach if rank is None]

    terms = sum(len(v) for v in table.values())
    aliasable = len(table)
    print(f"registre        {aliasable} fiches, {terms} termes")
    print(f"couverture      {aliasable}/{len(index['docs'])} documents "
          f"({aliasable / max(1, len(index['docs'])):.1%})")

    if quiet:
        print("OK" if not problems and not unreachable else
              f"{len(problems)} problème(s), {len(unreachable)} terme(s) hors d'atteinte")
        return 0 if not problems and not unreachable else 1

    print(f"\n=== atteignabilité (terme seul → rang de sa fiche, top {REACH_TOP}) ===")
    for key, term, rank in reach:
        mark = "" if rank else "   <<< hors d'atteinte"
        print(f"  {key.split(':', 1)[1]:34s} {term:22s} {'#' + str(rank) if rank else 'absent':>7s}{mark}")

    if problems:
        print("\n=== problèmes ===")
        for p in problems:
            print(f"  {p}")
    if unreachable:
        print("\n=== termes hors d'atteinte ===")
        for key, term in unreachable:
            print(f"  {key} : « {term} »")

    ok = not problems and not unreachable
    print("\nOK — registre valide, chaque terme conduit à sa fiche." if ok
          else "\nECHEC — voir ci-dessus.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
