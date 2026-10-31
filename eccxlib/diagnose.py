"""Diagnostic d'un jeu d'éval : ce que le routeur pouvait gagner, et ce qu'il ne pouvait pas.

Le problème mesuré
------------------
Additionner toutes les requêtes d'un jeu dans un seul « 45 % au rang 1 » mélange
deux choses qui n'ont pas la même solution :

* des requêtes où le bon document **partage du vocabulaire** avec la question.
  Là, le rang dépend du classement, et c'est un problème de routeur ;
* des requêtes où **aucune** cible attendue ne partage un seul token avec la
  question. « le pipeline d'intégration continue échoue » ne peut pas mener à un
  document dont la description ne contient aucun de ces mots. Là, le rang 1 est
  perdu avant la première comparaison : c'est un trou de vocabulaire, et ça se
  corrige avec du contenu (alias, lexique), pas avec des poids.

Un chiffre unique cache toujours laquelle des deux causes on est en train de
regarder. Ce module les sépare.

Ce qu'il ne fait pas
--------------------
Il ne dit pas si une attente est **juste**. « an access key got committed »
n'atteint pas `security-scan` parce que cette fiche parle de `.claude/`, pas de
dépôt : le diagnostic dit « inatteignable, voici les documents qui, eux,
partagent des termes » — et c'est un humain qui tranche entre « l'attente est
fausse » et « le catalogue a un trou ». Un outil qui trancherait à ma place
serait un outil qui réécrit mes propres évaluations.

La classification utilise `router.prepare_terms`, donc elle voit la question
**telle que le routeur la voit** : traduction du lexique comprise. Si un terme
français est traduit et que la traduction touche le document, la requête est
atteignable — et c'est correct, puisque le routeur gagne par ce chemin.
"""
from __future__ import annotations

from . import router

# Fields the router actually scores on the shipped catalogue. `sec` is excluded
# on purpose: it is populated only for a user corpus, never for ECC documents,
# so counting it here would declare a query reachable through evidence the
# router never uses on this corpus.
SCORED_FIELDS = ("name", "desc", "alias", "heads")


def _doc_tokens(doc: dict) -> set[str]:
    f = router._fields(doc)
    out: set[str] = set()
    for field in SCORED_FIELDS:
        out |= f[field]
    return out


def classify(index: dict, case: dict) -> dict:
    """Classe une requête. Ne mesure rien : décrit ce qui était possible.

    Trois statuts :

    * `missing`     — une cible attendue n'existe pas dans le catalogue ; la
      requête est infaisable par construction (défaut du jeu, pas du routeur) ;
    * `unreachable` — toutes les cibles existent, aucune ne partage un token avec
      la question telle que le routeur la lit ;
    * `reachable`   — au moins une cible partage du vocabulaire ; le rang est une
      question de classement.
    """
    by_key = {f"{d['kind']}:{d['id']}": d for d in index["docs"]}
    prepared = router.prepare_terms(case["q"], index=index)
    qtokens = set(prepared[1]) if prepared else set()

    expected = list(case.get("expect") or [])
    missing = [e for e in expected if e not in by_key]
    live = [e for e in expected if e in by_key]

    per_target: dict[str, set[str]] = {}
    for key in live:
        per_target[key] = _doc_tokens(by_key[key]) & qtokens

    shared = {k: v for k, v in per_target.items() if v}

    if missing:
        status = "missing"
    elif shared:
        status = "reachable"
    else:
        status = "unreachable"

    out = {
        "q": case["q"],
        "status": status,
        "tokens": sorted(qtokens),
        "missing": missing,
        "per_target": {k: sorted(v) for k, v in per_target.items()},
    }

    if status == "unreachable":
        # Which documents *would* have matched? If one of them serves the intent
        # better than the expected target, the expectation — not the catalogue —
        # is what is wrong. Reported as information, never applied.
        best = []
        for key, doc in by_key.items():
            overlap = _doc_tokens(doc) & qtokens
            if overlap:
                best.append((len(overlap), key, sorted(overlap)))
        best.sort(key=lambda t: (-t[0], t[1]))
        out["alternatives"] = [{"key": k, "shared": s} for _, k, s in best[:3]]
    return out


def shared_tokens(row: dict) -> int:
    """Combien de tokens distincts la meilleure cible partage avec la question."""
    return max((len(v) for v in row.get("per_target", {}).values()), default=0)


def curve(index: dict, cases: list[dict]) -> list[dict]:
    """La courbe réussite/tokens partagés. **La** mesure, sans seuil.

    Choisir un seuil (« atteignable = au moins N tokens ») après avoir regardé la
    courbe serait la faute que ce dépôt combat : un paramètre réglé sur la donnée
    qu'il prétend mesurer. On publie donc la courbe entière, et toute lecture d'un
    chiffre unique reste vérifiable contre elle.

    Constat mesuré le 2026-10-31 sur les 108 requêtes des cinq jeux, catalogue
    complet (604 documents, registre d'alias actif) :

        tokens partagés   n    réussite @1
              1          25      12 %      <- du bruit
              2          43      30 %
              3          16      50 %
              4           7      86 %      <- le routeur fonctionne
              5+          8     100 %

    Un token commun ne rend donc pas une requête « gagnable » : il la rend
    techniquement atteignable et pratiquement perdue. C'est la différence entre
    la couverture et le classement, et c'est pour ça qu'un chiffre unique
    (« 45 % au rang 1 ») ne pouvait rien dire d'exploitable.
    """
    buckets: dict[int, dict[str, int]] = {}
    rows = [classify(index, c) for c in cases]
    for case, row in zip(cases, rows, strict=True):
        if row["status"] != "reachable":
            continue
        k = shared_tokens(row)
        ids = [f"{d['doc']['kind']}:{d['doc']['id']}"
               for d in router.score(index, case["q"], top=1, project_context=[])]
        hit = any(e in ids for e in case["expect"])
        b = buckets.setdefault(k, {"n": 0, "hit": 0})
        b["n"] += 1
        b["hit"] += hit
    return [{"shared": k, "n": v["n"], "hit": v["hit"]}
            for k, v in sorted(buckets.items())]


def split(index: dict, cases: list[dict]) -> dict:
    """Répartit un jeu en trois seaux, sans juger du classement."""
    buckets: dict[str, list[dict]] = {"reachable": [], "unreachable": [], "missing": []}
    for case in cases:
        buckets[classify(index, case)["status"]].append(case)
    return buckets


def report(index: dict, cases: list[dict]) -> dict:
    """Le chiffre honnête : qualité de classement d'un côté, couverture de l'autre.

    `ranking` ne porte **que** sur les requêtes atteignables — mesurer le rang sur
    les autres, c'est compter des échecs que le classement ne pouvait pas
    éviter, et donc sous-estimer systématiquement le routeur.
    `coverage` porte sur tout le jeu : c'est la part du réel que le vocabulaire
    atteint aujourd'hui.
    """
    rows = [classify(index, c) for c in cases]
    total = len(rows) or 1
    reachable = [r for r in rows if r["status"] == "reachable"]
    return {
        "total": len(rows),
        "reachable": len(reachable),
        "unreachable": sum(1 for r in rows if r["status"] == "unreachable"),
        "missing": sum(1 for r in rows if r["status"] == "missing"),
        "coverage": len(reachable) / total,
        "rows": rows,
    }
