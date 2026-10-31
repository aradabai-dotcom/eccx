"""Le diagnostic d'éval : trois statuts, et la courbe qui remplace un seuil.

Ce qui se teste ici n'est pas une performance, c'est une **classification**. Le
risque d'une classification est de toujours répondre la même chose : un
classifieur qui déclare tout « atteignable » fait monter le score de classement
sans rien mesurer. Chaque cas est donc construit pour forcer une seule réponse.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import diagnose  # noqa: E402


def _doc(doc_id: str, name: str, desc: str = "", aliases=None) -> dict:
    return {"id": doc_id, "kind": "skill", "name": name, "desc": desc,
            "headings": [], "sections": [], "path": f"{doc_id}/SKILL.md",
            "body_tokens": 10, "aliases": aliases or [], "aliases_fm": [],
            "extra": {}}


def _index(*docs) -> dict:
    return {"docs": list(docs)}


class TestLesTroisStatuts(unittest.TestCase):

    def test_shared_vocabulary_is_reachable(self):
        idx = _index(_doc("alpha", "alpha-skill", "handles deployment rollback"))
        row = diagnose.classify(idx, {"q": "deployment is broken", "expect": ["skill:alpha"]})
        self.assertEqual("reachable", row["status"])
        self.assertEqual(["deployment"], row["per_target"]["skill:alpha"])

    def test_no_shared_vocabulary_is_unreachable(self):
        idx = _index(_doc("alpha", "alpha-skill", "handles deployment rollback"))
        row = diagnose.classify(idx, {"q": "the wifi password resets", "expect": ["skill:alpha"]})
        self.assertEqual("unreachable", row["status"])

    def test_absent_target_is_missing_not_unreachable(self):
        """Une cible inexistante est un défaut du jeu, pas un trou de vocabulaire.

        Les confondre ferait passer un jeu cassé pour un catalogue incomplet.
        """
        idx = _index(_doc("alpha", "alpha-skill", "deployment"))
        row = diagnose.classify(idx, {"q": "deployment", "expect": ["skill:fantome"]})
        self.assertEqual("missing", row["status"])
        self.assertEqual(["skill:fantome"], row["missing"])

    def test_missing_wins_over_reachable(self):
        """Une seule cible inexistante suffit à rendre la requête infaisable."""
        idx = _index(_doc("alpha", "alpha-skill", "deployment"))
        row = diagnose.classify(idx, {"q": "deployment",
                                      "expect": ["skill:alpha", "skill:fantome"]})
        self.assertEqual("missing", row["status"])

    def test_alternative_targets_are_offered_as_information(self):
        idx = _index(_doc("alpha", "alpha-skill", "deployment"),
                     _doc("beta", "beta-skill", "wifi password reset procedure"))
        row = diagnose.classify(idx, {"q": "the wifi password resets", "expect": ["skill:alpha"]})
        self.assertEqual("unreachable", row["status"])
        self.assertIn("skill:beta", [a["key"] for a in row["alternatives"]])

    def test_aliases_count_as_vocabulary(self):
        """L'alias est un vrai chemin d'accès : il doit rendre la requête atteignable."""
        idx = _index(_doc("alpha", "alpha-skill", "latency budget", aliases=["endpoint"]))
        row = diagnose.classify(idx, {"q": "this endpoint is slow", "expect": ["skill:alpha"]})
        self.assertIn("endpoint", row["per_target"]["skill:alpha"])


class TestLaCourbeNeTranchePas(unittest.TestCase):

    def test_buckets_count_shared_tokens(self):
        idx = _index(_doc("a", "a", "x1 x2 x3"), _doc("b", "b", "y1 y2"))
        cases = [{"q": "x1 x2 x3", "expect": ["skill:a"]},
                 {"q": "y1", "expect": ["skill:b"]}]
        pts = diagnose.curve(idx, cases)
        self.assertEqual([{"shared": 1, "n": 1, "hit": 1},
                          {"shared": 3, "n": 1, "hit": 1}], pts)

    def test_unreachable_queries_are_out_of_the_curve(self):
        """Les compter dedans ramènerait le chiffre mélangé qu'on veut éviter."""
        idx = _index(_doc("a", "a", "x1"))
        pts = diagnose.curve(idx, [{"q": "zzz", "expect": ["skill:a"]}])
        self.assertEqual([], pts)

    def test_report_separates_coverage_from_rows(self):
        idx = _index(_doc("a", "a", "x1"), _doc("b", "b", "y1"))
        cases = [{"q": "x1", "expect": ["skill:a"]},
                 {"q": "zzz", "expect": ["skill:b"]},
                 {"q": "x1", "expect": ["skill:nope"]}]
        rep = diagnose.report(idx, cases)
        self.assertEqual((3, 1, 1, 1),
                         (rep["total"], rep["reachable"], rep["unreachable"], rep["missing"]))
        self.assertAlmostEqual(1 / 3, rep["coverage"], places=6)


class TestLesJeuxSontScelles(unittest.TestCase):
    """Une empreinte commitée : modifier un jeu sans le resceller se voit en revue.

    Ce que ce sceau ne fait pas : il ne prouve rien sur ce qui s'est passé avant
    son ajout. Les jeux `fr-heldout` et `en-heldout` ont été lus avant la fin du
    développement qu'ils devaient mesurer, et aucune empreinte ne le corrige.
    Il empêche la prochaine modification silencieuse, rien de plus.
    """

    SEALS = ROOT / "evals" / "SEALS.json"

    def test_the_seal_file_exists(self):
        self.assertTrue(self.SEALS.is_file(),
                        "lancer `python3 tools/eval_health.py --reseal`")

    def test_every_sealed_set_matches_its_digest(self):
        sealed = json.loads(self.SEALS.read_text())
        self.assertTrue(sealed, "aucun jeu scellé")
        changed = []
        for name, expected in sealed.items():
            path = ROOT / name
            if not path.is_file():
                changed.append(f"{name} : fichier absent")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                changed.append(f"{name} : contenu différent du sceau")
        self.assertEqual([], changed,
                         "jeu(x) modifié(s) sans resceller : " + "; ".join(changed))

    def test_every_eval_file_is_sealed(self):
        """Un jeu non scellé est un jeu qu'on peut éditer sans laisser de trace."""
        sealed = set(json.loads(self.SEALS.read_text()))
        # Même frontière que `tools/eval_health.py` : les jeux de réglage et les
        # fixtures de corpus ne sont pas des jeux de mesure.
        unsealed = [p.name for p in (ROOT / "evals").glob("*.jsonl")
                    if p.stem != "routing" and not p.stem.startswith("corpus-")
                    and f"evals/{p.name}" not in sealed]
        self.assertEqual([], unsealed)


if __name__ == "__main__":
    unittest.main()
