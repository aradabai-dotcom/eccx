"""Le registre d'alias : les erreurs qu'il peut commettre, et le mécanisme.

Un alias est une affirmation — « ce document parle aussi de ceci ». Les façons
dont elle peut être fausse, toutes rencontrées en écrivant ce registre :

* **viser un document qui n'existe pas** : couverture imaginaire, et rien ne le
  signale tant que personne ne relit les 604 identifiants ;
* **n'ajouter aucun mot** : le premier jet contenait 13 termes sur 43 dont tous
  les tokens étaient déjà dans les titres. Le registre grossissait, le rappel ne
  bougeait pas ;
* **survivre à sa propre suppression** : si `apply` fusionnait au lieu
  d'écraser, un alias retiré du registre continuerait de vivre dans un index
  construit avant, sans aucun moyen de le voir ;
* **ne pas atteindre son document** : un mot qui ne trouve pas sa propre fiche
  n'est pas une preuve de couverture.

Le dernier test est le plus utile à long terme : il confronte le registre au
catalogue réel, donc il échoue si un document est renommé en amont. C'est la
seule protection contre un registre qui pourrit lentement.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import aliases, indexer, router  # noqa: E402


def _write(payload) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "catalogue.json"
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    return tmp


class TestLeRegistreRefuseLeVideEtLeSilence(unittest.TestCase):

    def test_missing_file_is_an_empty_registry_not_a_crash(self):
        """Un dépôt sans alias doit fonctionner exactement comme avant."""
        self.assertEqual({}, aliases.load(Path("/nonexistent/catalogue.json")))

    def test_entry_without_why_is_rejected(self):
        """Un alias sans justification est un ajustement sur la réponse, pas un fait."""
        path = _write({"entries": {"skill:a": {"terms": ["x"]}}})
        with self.assertRaises(aliases.AliasError):
            aliases.load(path)

    def test_unknown_kind_separator_is_rejected(self):
        path = _write({"entries": {"skill-a": {"why": "x", "terms": ["y"]}}})
        with self.assertRaises(aliases.AliasError):
            aliases.load(path)

    def test_broken_json_names_the_file(self):
        tmp = Path(tempfile.mkdtemp()) / "catalogue.json"
        tmp.write_text("{not json", encoding="utf-8")
        with self.assertRaises(aliases.AliasError):
            aliases.load(tmp)

    def test_too_many_terms_is_rejected(self):
        path = _write({"entries": {"skill:a": {
            "why": "x", "terms": [f"t{i}" for i in range(aliases.MAX_TERMS + 1)]}}})
        with self.assertRaises(aliases.AliasError):
            aliases.load(path)

    def test_terms_are_normalised_and_deduplicated(self):
        path = _write({"entries": {"skill:a": {"why": "x",
                                              "terms": ["  Response   Time ", "response time"]}}})
        self.assertEqual({"skill:a": ["response time"]}, aliases.load(path))


class TestLeFrontmatterEstLuAussi(unittest.TestCase):
    """Le champ doit marcher quand on possède le fichier, pas seulement en overlay."""

    def test_bracketed_list(self):
        self.assertEqual(["a", "b c"], aliases.from_frontmatter({"aliases": "[a, b c]"}))

    def test_bare_comma_list(self):
        self.assertEqual(["a", "b"], aliases.from_frontmatter({"aliases": "a, b"}))

    def test_absent_key_is_empty(self):
        self.assertEqual([], aliases.from_frontmatter({"name": "x"}))


class TestApplyEcraseAuLieuDeFusionner(unittest.TestCase):

    def test_a_removed_alias_does_not_survive(self):
        doc = {"kind": "skill", "id": "a", "aliases": ["vieux"]}
        aliases.apply([doc], {"skill:a": ["neuf"]})
        self.assertEqual(["neuf"], doc["aliases"],
                         "un alias retiré du registre survivrait à sa suppression")

    def test_a_document_without_entry_loses_stale_aliases(self):
        doc = {"kind": "skill", "id": "a", "aliases": ["fantome"]}
        aliases.apply([doc], {})
        self.assertEqual([], doc["aliases"])

    def test_frontmatter_and_registry_are_merged(self):
        doc = {"kind": "skill", "id": "a", "aliases_fm": ["du frontmatter"]}
        aliases.apply([doc], {"skill:a": ["du registre"]})
        self.assertEqual(["du registre", "du frontmatter"], doc["aliases"])

    def test_the_table_is_not_modified(self):
        table = {"skill:a": ["x"]}
        aliases.apply([{"kind": "skill", "id": "a"}], table)
        self.assertEqual({"skill:a": ["x"]}, table)


class TestAudit(unittest.TestCase):

    def test_unknown_document_is_reported(self):
        problems = aliases.audit([{"kind": "skill", "id": "a", "name": "a",
                                   "desc": "", "headings": []}],
                                 {"skill:disparu": ["x"]})
        self.assertTrue(any("inconnu" in p for p in problems), problems)

    def test_no_op_alias_is_reported(self):
        """Tous les tokens déjà présents : l'alias ne change rien au classement."""
        doc = {"kind": "skill", "id": "a", "name": "alpha beta",
               "desc": "", "headings": []}
        problems = aliases.audit([doc], {"skill:a": ["beta"]})
        self.assertTrue(any("déjà dans la fiche" in p for p in problems), problems)

    def test_alias_of_stopwords_only_is_reported(self):
        doc = {"kind": "skill", "id": "a", "name": "alpha", "desc": "", "headings": []}
        problems = aliases.audit([doc], {"skill:a": ["the of"]})
        self.assertTrue(any("aucun token" in p for p in problems), problems)

    def test_a_healthy_entry_passes(self):
        doc = {"kind": "skill", "id": "a", "name": "alpha", "desc": "", "headings": []}
        self.assertEqual([], aliases.audit([doc], {"skill:a": ["omega"]}))


class TestLeChampEstBrancheSurLeRouteur(unittest.TestCase):
    """Un alias qui ne change pas le classement est une décoration."""

    def _index(self):
        return {"docs": [
            {"kind": "skill", "id": "alpha", "name": "alpha-skill", "desc": "",
             "headings": [], "sections": [], "path": "alpha/SKILL.md",
             "body_tokens": 10, "aliases": [], "extra": {}},
            {"kind": "skill", "id": "beta", "name": "beta-skill",
             "desc": "totally unrelated matter", "headings": [], "sections": [],
             "path": "beta/SKILL.md", "body_tokens": 10, "aliases": [], "extra": {}},
        ]}

    def test_a_document_is_not_found_by_a_word_it_lacks(self):
        index = self._index()
        ids = [r["doc"]["id"] for r in router.score(index, "omega", top=2)]
        self.assertNotIn("alpha", ids)

    def test_the_alias_makes_the_document_reachable(self):
        index = self._index()
        aliases.apply(index["docs"], {"skill:alpha": ["omega"]})
        ids = [r["doc"]["id"] for r in router.score(index, "omega", top=2)]
        self.assertEqual(["alpha"], ids,
                         "le champ alias n'atteint pas le calcul de score")


class TestLeRegistreReelTientContreLeCatalogue(unittest.TestCase):
    """Anti-pourrissement : un document renommé en amont casse ce test."""

    def test_every_entry_points_at_a_live_document(self):
        index = indexer.load()
        problems = aliases.audit(index["docs"])
        self.assertEqual([], problems, "\n".join(problems))

    def test_each_term_reaches_its_own_document(self):
        index = indexer.load()
        table = aliases.load()
        misses = []
        for key, terms in table.items():
            for term in terms:
                ids = [f"{r['doc']['kind']}:{r['doc']['id']}"
                       for r in router.score(index, term, top=10, project_context=[])]
                if key not in ids:
                    misses.append(f"{key} : « {term} » n'atteint pas sa fiche")
        self.assertEqual([], misses, "\n".join(misses))


if __name__ == "__main__":
    unittest.main()
