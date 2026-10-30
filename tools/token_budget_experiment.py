#!/usr/bin/env python3
"""À budget de tokens ÉGAL, combien de bonnes réponses entrent dans le contexte ?

C'est la seule question qui parle de l'objectif réel : moins de tokens, plus
juste. Ni la latence (ms) ni le rang (k=20) ne disent ce qu'un agent reçoit
vraiment quand on lui donne un plafond.

Les deux armées, sous le MÊME plafond de 32 000 octets — la constante
`MAX_CONTEXT_BYTES` d'ECC, pas une valeur choisie pour arranger eccx :

  A. ECC — skills ENTIERS dans l'ordre de son routeur, jusqu'au plafond.
     Fidèle à ce que fait ECC : `context-profile-launch.js` passe
     `selection.resources` (chargé avec `load: true`, donc le corps) dans un
     JSON borné par `MAX_CONTEXT_BYTES` ; au-delà, il refuse
     (`ECC_CONTEXT_BYTE_BUDGET`) plutôt que d'amputer. Modèle retenu : on
     s'arrête avant de dépasser — c'est la lecture *optimiste* pour ECC,
     puisqu'elle ne compte jamais un refus.

  B. eccx — SECTIONS choisies par le routeur, même plafond.

Métrique : l'id attendu est-il présent dans ce qui a été injecté ? Nuance
obligatoire, publiée avec le chiffre : « présent » ne veut pas dire « complet ».
Le script mesure donc aussi quelle part du texte du bon document entre
réellement (médiane constatée : 13 % — une tranche ciblée, pas le fichier).

Usage : python3 tools/token_budget_experiment.py [--ecc-root ~/ECC]
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import indexer, router  # noqa: E402
from eccxlib.util import doc_file, read_text  # noqa: E402

ECC_CAP_BYTES = 32_000          # MAX_CONTEXT_BYTES in ECC/scripts/lib/context-selection.js
SETS = ("heldout", "heldout2")


def load_cases() -> list[dict]:
    cases = []
    for name in SETS:
        cases += [json.loads(l) for l in (ROOT / "evals" / f"{name}.jsonl").read_text().splitlines() if l.strip()]
    return cases


def ecc_ranks(ecc_root: Path, cases: list[dict]) -> list[list[str]]:
    """Les classements du routeur d'ECC, une passe par jeu."""
    import tempfile

    out: list[list[str]] = []
    per_set = {name: [c for c in cases[: len(cases) // 2]] if name == SETS[0] else cases[len(cases) // 2:]
               for name in SETS}
    for name in SETS:
        with tempfile.TemporaryDirectory() as tmp:
            qfile = Path(tmp) / "q.jsonl"
            qfile.write_text("\n".join(json.dumps({"q": c["q"], "expect": c["expect"]}) for c in per_set[name]) + "\n")
            r = subprocess.run(["node", str(ROOT / "tools" / "ecc_router_bench.js"), str(qfile), str(ecc_root)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"routeur ECC indisponible : {r.stderr.strip()}")
            out += [row["ranked"] for row in json.loads(r.stdout)]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ecc-root", default=str(Path.home() / "ECC"))
    args = ap.parse_args()
    ecc_root = Path(args.ecc_root).expanduser()

    cases = load_cases()
    ranks = ecc_ranks(ecc_root, cases)
    idx = indexer.load()

    bodies: dict[str, str] = {}

    def body(rid: str) -> str:
        if rid not in bodies:
            p = ecc_root / "skills" / rid.split(":", 1)[1] / "SKILL.md"
            bodies[rid] = read_text(p) if p.is_file() else ""
        return bodies[rid]

    def ecc_fill(ranked: list[str]) -> tuple[int, list[str]]:
        used, ids = 0, []
        for rid in ranked:
            if not rid.startswith("skill:"):
                continue
            n = len(body(rid))
            if used + n > ECC_CAP_BYTES:
                break                      # ECC refuse plutôt que d'amputer
            used += n
            ids.append(rid)
        return used, ids

    def eccx_fill(query: str) -> tuple[int, list[str], dict[str, str]]:
        res = router.score(idx, query, kinds=None, top=20, project_context=[])
        bundle = router.render_bundle(res, budget_tokens=ECC_CAP_BYTES // 4, query=query)
        ids = [f"{r['doc']['kind']}:{r['doc']['id']}" for r in res
               if f"<!-- {r['doc']['kind']}:{r['doc']['id']}" in bundle]
        by_id = {f"{r['doc']['kind']}:{r['doc']['id']}": r["doc"] for r in res}
        return len(bundle), ids, {i: bundle for i in ids} | {"__docs__": by_id}

    n = len(cases)
    ecc_hit = eccx_hit = 0
    ecc_bytes = eccx_bytes = 0
    shares: list[float] = []

    for case, ranked in zip(cases, ranks, strict=True):
        ua, ia = ecc_fill(ranked)
        ecc_bytes += ua
        if any(x in case["expect"] for x in ia):
            ecc_hit += 1

        ub, ib, extra = eccx_fill(case["q"])
        eccx_bytes += ub
        good = [i for i in ib if i in case["expect"]]
        if good:
            eccx_hit += 1
            doc = extra["__docs__"][good[0]]
            full = read_text(doc_file(doc)) if not good[0].startswith("skill:") else body(good[0])
            lines = [ln.strip() for ln in full.splitlines() if len(ln.strip()) > 40]
            if lines:
                shares.append(sum(1 for ln in lines if ln in extra[good[0]]) / len(lines))

    print(f"plafond commun : {ECC_CAP_BYTES} octets (~{ECC_CAP_BYTES // 4} tokens), {n} requêtes aveugles\n")
    print(f"  ECC  : {ecc_hit:2d}/{n} ({ecc_hit / n:4.0%}) · {ecc_bytes // n:5d} octets/requête"
          f" · {ecc_bytes // max(ecc_hit, 1):6d} octets par réponse trouvée")
    print(f"  eccx : {eccx_hit:2d}/{n} ({eccx_hit / n:4.0%}) · {eccx_bytes // n:5d} octets/requête"
          f" · {eccx_bytes // max(eccx_hit, 1):6d} octets par réponse trouvée")
    if shares:
        print(f"\n  quand eccx trouve, part médiane du texte du bon document injectée : "
              f"{statistics.median(shares):.0%}  (quartiles "
              f"{sorted(shares)[len(shares) // 4]:.0%}–{sorted(shares)[3 * len(shares) // 4]:.0%})")
    print("\n  Lecture honnête : « présent » = l'id de la bonne réponse est dans le payload,")
    print("  pas que tout son texte y soit. Ce que l'agent produit avec une tranche de 13 %")
    print("  n'est pas mesuré ici — c'est l'évaluation qui manque, et elle demande un agent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
