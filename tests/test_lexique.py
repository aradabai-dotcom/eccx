"""Le lexique français→anglais, et les façons dont il peut mentir.

Un traducteur greffé sur un moteur de recherche est un endroit où l'on se trompe
sans le voir. Trois modes de défaillance ont été observés ou rendus impossibles
ici :

  1. une entrée qui traduit un mot vers lui-même, ou vers un mot que `tokenize`
     jette ensuite : le lexique grossit, rien ne se passe ;
  2. une locution décomposée en mots, qui perd l'ordre des termes — et l'ordre
     est ce qui fait gagner le bonus de bigramme ;
  3. une requête déjà anglaise abîmée au passage.

Le bug des accents n'était pas dans le lexique mais dans `tokenize`
(`déploiement` → `ploiement`), et il rendait toute traduction inutile : c'est
pourquoi les deux sont testés ensemble.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import lexique  # noqa: E402
from eccxlib.util import tokenize  # noqa: E402


def _adds(french: str, english: str) -> set[str]:
    """Tokens the translation contributes that the French word does not already."""
    return set(tokenize(english)) - set(tokenize(french))


class TestAucuneTraductionFantome(unittest.TestCase):
    """Une entrée qui n'ajoute aucun token de vocabulaire ne sert à rien.

    Le lexique en contenait vingt-deux : onze traductions vers la chaîne vide
    (`production`, `test`, `migration`… — identiques en anglais) et onze vers un
    mot que `tokenize` traite comme du vide (`fix`). Elles gonflaient le nombre
    d'entrées sans jamais rien changer au classement.
    """

    def test_every_word_adds_vocabulary(self):
        ghosts = [f"{f}->{e}" for f, e in lexique.WORDS.items() if not _adds(f, e)]
        self.assertEqual([], ghosts, "ces entrées ne changent rien au résultat")

    def test_every_phrase_changes_something(self):
        ghosts = [k for k, v in lexique.PHRASES.items()
                  if lexique._fold(k) == lexique._fold(v)]
        self.assertEqual([], ghosts)

    def test_translations_are_lowercase_ascii(self):
        bad = [f"{k}->{v}" for k, v in lexique.WORDS.items()
               if v != v.lower() or any(ord(c) > 127 for c in v)]
        self.assertEqual([], bad)


class TestLesLocutionsPassentAvantLesMots(unittest.TestCase):
    """« mise en production » est une unité ; mot à mot, elle perd son sens."""

    def test_phrase_is_matched_as_a_whole(self):
        text, _ = lexique.rewrite("la mise en production approche")
        produced = set(tokenize(text))
        self.assertIn("deploy", produced, f"locution non reconnue : {sorted(produced)}")

    def test_phrase_keeps_word_order(self):
        """L'ordre porte le bonus de bigramme du routeur, pas le vocabulaire."""
        text, _ = lexique.rewrite("revoir le code legacy")
        self.assertIn("legacy code", text,
                      "la locution doit être réécrite dans l'ordre anglais")

    def test_matching_ignores_case_and_accents(self):
        self.assertEqual(lexique.rewrite("Mise en Production")[1],
                         lexique.rewrite("mise en production")[1])


class TestUneRequeteAnglaiseEstIntacte(unittest.TestCase):
    """La non-régression qui compte : le lexique ne casse rien en anglais."""

    def test_english_query_is_returned_unchanged(self):
        for query in (
            "review the pull request before merging",
            "our deployment fails in production",
            "add a NOT NULL column to a large table",
            "the retry logic double charges the customer",
        ):
            text, hits = lexique.rewrite(query)
            self.assertEqual(query, text, f"requête anglaise modifiée : {query!r}")
            self.assertEqual([], hits)

    def test_empty_query_is_safe(self):
        for query in ("", "   ", None):
            self.assertEqual((query, []), lexique.rewrite(query))


class TestRienNEstRetire(unittest.TestCase):
    """Le lexique ajoute, il ne remplace jamais : un mot non traduit reste."""

    def test_every_original_word_survives(self):
        query = "mon déploiement échoue, comment revenir à la version précédente ?"
        produced = set(tokenize(lexique.rewrite(query)[0]))
        missing = [w for w in tokenize(query) if w not in produced]
        self.assertEqual([], missing, "le lexique a supprimé des mots de la requête")

    def test_translation_actually_adds_english(self):
        produced = set(tokenize(lexique.rewrite("mon déploiement échoue")[0]))
        self.assertTrue({"deployment", "deploy", "fail"} <= produced,
                        f"traduction incomplète : {sorted(produced)}")


class TestMorphologie(unittest.TestCase):
    """Formes fléchies mesurées en échec : sans elles, la traduction ne part pas."""

    def test_inflected_forms_are_translated(self):
        cases = {
            "ces tests échouent une fois sur quatre": "fail",
            "une branche fusionnée hier": "merge",
            "le correctif a été déployé": "deploy",
            "les requêtes sont lentes": "query",
        }
        for query, expected in cases.items():
            produced = set(tokenize(lexique.rewrite(query)[0]))
            self.assertIn(expected, produced, f"{query!r} → {sorted(produced)}")

    def test_generated_inflections_never_override_written_entries(self):
        for form, english in lexique.LOOKUP.items():
            if form in lexique.WORDS:
                self.assertEqual(lexique.WORDS[form], english,
                                 f"{form} : la flexion a écrasé l'entrée explicite")


class TestTokenizeNeutraliseLesAccents(unittest.TestCase):
    """Régression : `déploiement` devenait `ploiement`, et le fragment gagnait."""

    def test_accented_word_is_one_token(self):
        self.assertEqual(["mon", "deploiement", "echoue", "vers", "precedente"],
                         tokenize("mon déploiement échoue vers précédente"))

    def test_no_two_letter_fragment_from_a_french_word(self):
        """`précédente` produisait `pr` + `dente` ; `pr` pesait 5,0 via le nom."""
        tokens = tokenize("la version précédente")
        self.assertNotIn("pr", tokens)
        self.assertIn("precedente", tokens)

    def test_sentence_final_punctuation_is_not_a_token(self):
        """`pipeline.` peuplait la table de co-occurrence de tokens fantômes."""
        self.assertEqual([], [t for t in tokenize("The pipeline fails. Then it stops.")
                              if t.endswith(".")])

    def test_filenames_keep_their_punctuation(self):
        """Le point a été conservé *dans* un token pour `package.json`."""
        self.assertIn("package.json", tokenize("edit package.json now"))


if __name__ == "__main__":
    unittest.main()
