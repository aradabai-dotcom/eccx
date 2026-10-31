"""L'étage 2 : quand il s'abstient, et sur quelles lignes il calcule.

Deux propriétés seulement, mais ce sont celles qui coûtent cher quand elles sont
fausses :

* **L'abstention.** Sur une réponse franche du premier étage, l'étage 2 ne doit
  rien faire — c'est ce qui rend le modèle optionnel au lieu de le payer à
  chaque requête.
* **L'alignement.** La matrice de vecteurs est construite sur le catalogue
  entier, dans son ordre. Un candidat classé n°1 peut être le document n°57 de
  la matrice. Calculer `matrix[0] @ qv` pour le premier résultat noterait chaque
  document contre le vecteur d'un autre — sans erreur, avec des scores plausibles
  et un classement faux. C'était le bug de la première version.
"""
from __future__ import annotations

import sys
import unittest

import numpy as np

ROOT = "/home/user/ecc-adapter"
sys.path.insert(0, ROOT)

from eccxlib import second_stage  # noqa: E402


def _row(kind: str, doc_id: str, score: float) -> dict:
    return {"doc": {"kind": kind, "id": doc_id}, "score": score,
            "matched": [], "coverage": 1.0}


class TestLeGateSAbstientQuandLePremierEtageEstSur(unittest.TestCase):

    def test_confident_top1_is_not_escalated(self):
        results = [_row("skill", "a", 30.0), _row("skill", "b", 10.0)]
        self.assertFalse(second_stage.uncertain(results, margin=0.20))

    def test_close_top2_is_escalated(self):
        results = [_row("skill", "a", 10.0), _row("skill", "b", 9.5)]
        self.assertTrue(second_stage.uncertain(results, margin=0.20))

    def test_single_result_is_never_escalated(self):
        self.assertFalse(second_stage.uncertain([_row("skill", "a", 10.0)]))

    def test_zero_score_is_never_escalated(self):
        """Division par zéro masquerait un premier étage cassé."""
        self.assertFalse(second_stage.uncertain([_row("skill", "a", 0.0),
                                                 _row("skill", "b", 0.0)]))

    def test_gate_returns_escalation_flag(self):
        confident = [_row("skill", "a", 30.0), _row("skill", "b", 10.0)]
        out, escalated = second_stage.apply_gate(confident, None, None, {})
        self.assertFalse(escalated)
        self.assertEqual([r["doc"]["id"] for r in out], ["a", "b"])

    def test_missing_vectors_leave_the_ranking_alone(self):
        unsure = [_row("skill", "a", 10.0), _row("skill", "b", 9.0)]
        out, escalated = second_stage.apply_gate(unsure, None, None, {})
        self.assertFalse(escalated)
        self.assertEqual([r["score"] for r in out], [10.0, 9.0])


class TestLAlignementDesLignes(unittest.TestCase):
    """Le candidat n°1 n'est pas forcément la ligne n°1 de la matrice."""

    def setUp(self):
        # 4 documents ; seule la ligne 3 pointe vers le vecteur de la requête,
        # la ligne 0 est orthogonale. Un code qui confond position et ligne
        # donnera un score sémantique nul au bon document.
        self.matrix = np.array([[0.0, 1.0],
                                [0.0, 1.0],
                                [0.0, 1.0],
                                [1.0, 0.0]], dtype=np.float32)
        self.qv = np.array([1.0, 0.0], dtype=np.float32)
        self.results = [_row("skill", "first", 10.0), _row("skill", "second", 9.8)]
        self.row_of = {"skill:first": 3, "skill:second": 0}

    def test_uses_the_documents_own_row(self):
        out, escalated = second_stage.apply_gate(
            self.results, self.qv, self.matrix, self.row_of, alpha=1.0, margin=1.0)
        self.assertTrue(escalated)
        by_id = {r["doc"]["id"]: r for r in out}
        self.assertAlmostEqual(by_id["first"]["semantic"], 1.0, places=5,
                               msg="le bon document doit être noté contre sa ligne")
        self.assertAlmostEqual(by_id["second"]["semantic"], 0.0, places=5)

    def test_a_document_missing_from_the_map_aborts_the_stage(self):
        """Mieux vaut rendre le classement du premier étage qu'inventer une ligne."""
        out, escalated = second_stage.apply_gate(
            self.results[:1] + [_row("skill", "unknown", 9.9)],
            self.qv, self.matrix, {"skill:first": 3}, alpha=1.0, margin=1.0)
        self.assertFalse(escalated)
        self.assertEqual([r["score"] for r in out], [10.0, 9.9])

    def test_a_row_past_the_matrix_aborts_the_stage(self):
        out, escalated = second_stage.apply_gate(
            self.results, self.qv, self.matrix,
            {"skill:first": 99, "skill:second": 0}, alpha=1.0, margin=1.0)
        self.assertFalse(escalated)


class TestL_EtageNeMuteRien(unittest.TestCase):

    def test_input_results_are_not_modified(self):
        results = [_row("skill", "a", 10.0), _row("skill", "b", 9.9)]
        snapshot = [(r["doc"]["id"], r["score"], dict(r)) for r in results]
        second_stage.apply_gate(results, np.array([1.0, 0.0], dtype=np.float32),
                                np.eye(2, dtype=np.float32),
                                {"skill:a": 0, "skill:b": 1},
                                alpha=1.0, margin=1.0)
        for (doc_id, score, original), r in zip(snapshot, results, strict=True):
            self.assertEqual(doc_id, r["doc"]["id"])
            self.assertEqual(score, r["score"])
            self.assertEqual(original, r)

    def test_stage_two_marks_the_rows_it_scored(self):
        results = [_row("skill", "a", 10.0), _row("skill", "b", 9.9)]
        out, _ = second_stage.apply_gate(results, np.array([1.0, 0.0], dtype=np.float32),
                                         np.eye(2, dtype=np.float32),
                                         {"skill:a": 0, "skill:b": 1},
                                         alpha=1.0, margin=1.0)
        for r in out:
            self.assertIn("score_lexical", r)
            self.assertEqual(2, r["stage"])


if __name__ == "__main__":
    unittest.main()
