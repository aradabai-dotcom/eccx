"""Profils de catalogue, et le jeu d'évaluation « tâches de dev senior ».

Trois choses sont vérifiées ici, parce que chacune a déjà été fausse une fois
pendant ce travail :

1. les exclusions d'un profil sont qualifiées (`kind:id`). Trois ids existent à
   la fois comme skill et comme command dans ce catalogue ; la première version
   excluait par id nu et retirait 93 documents là où le profil en annonçait 90 ;
2. un profil ne cite aucun nom périmé — une exclusion qui ne retire rien est un
   réglage qui ne fait rien, silencieusement ;
3. le jeu `senior-dev` reste bien formé et reste bilingue : sa partie française
   est le seul test de ce dépôt qui mesure un utilisateur francophone.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eccxlib import indexer, profil  # noqa: E402


class TestProfilesAreUnambiguous(unittest.TestCase):
    def test_every_shipped_profile_loads(self):
        names = profil.available()
        self.assertTrue(names, "aucun profil dans profils/")
        for name in names:
            with self.subTest(profil=name):
                p = profil.load(name)
                self.assertIn("exclude", p)
                self.assertIn("source", p)

    def test_exclusions_are_qualified_by_kind(self):
        """`skill:x` and `command:x` are different documents. A bare `x` is
        ambiguous and silently drops both."""
        for name in profil.available():
            for entry in profil.load(name)["exclude"]:
                with self.subTest(profil=name, entry=entry):
                    self.assertRegex(entry, r"^(skill|agent|command|rule|manual):.+")

    def test_a_bare_id_is_rejected_at_load_time_not_silently_accepted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "mauvais@1.json"
            bad.write_text(json.dumps({"id": "mauvais@1", "exclude": ["python-testing"]}))
            original = profil.PROFILES
            try:
                profil.PROFILES = Path(d)
                with self.assertRaises(profil.ProfileError):
                    profil.load("mauvais")
            finally:
                profil.PROFILES = original

    def test_no_profile_names_a_document_that_does_not_exist(self):
        idx = indexer.load()
        for name in profil.available():
            with self.subTest(profil=name):
                d = profil.describe(idx, profil.load(name))
                self.assertEqual(d["exclus_absents_du_catalogue"], [],
                                 "exclusions périmées — elles ne retirent rien")

    def test_applying_a_profile_never_mutates_the_index(self):
        idx = indexer.load()
        before = len(idx["docs"])
        profil.apply(idx, profil.load("logiciel"))
        self.assertEqual(len(idx["docs"]), before, "apply() a modifié l'index d'entrée")

    def test_the_kept_on_purpose_answers_are_in_the_profile_scope(self):
        """Les trois skills conservées exprès doivent survivre à l'application
        du profil — sinon le profil contredit sa propre documentation."""
        idx = indexer.load()
        p = profil.load("logiciel")
        kept = {f"skill:{k}" for k in (p.get("kept_on_purpose") or {})}
        self.assertTrue(kept, "le profil ne déclare aucune exception")
        ids = {d["kind"] + ":" + d["id"] for d in profil.apply(idx, p)["docs"]}
        for entry in kept:
            self.assertIn(entry, ids)


class TestSeniorDevEval(unittest.TestCase):
    PATH = ROOT / "evals" / "senior-dev.jsonl"

    def setUp(self):
        self.rows = [json.loads(l) for l in self.PATH.read_text().splitlines() if l.strip()]

    def test_twenty_tasks(self):
        self.assertEqual(len(self.rows), 20)

    def test_every_task_names_an_expected_answer_and_an_intent(self):
        for r in self.rows:
            with self.subTest(q=r.get("q", "")[:40]):
                self.assertTrue(r.get("q"))
                self.assertTrue(r.get("expect"))
                self.assertTrue(r.get("why"))

    def test_expected_answers_exist_in_the_catalogue(self):
        """Une cible qui n'existe pas rendrait la requête impossible par
        construction et le score artificiellement bas."""
        known = {f"{d['kind']}:{d['id']}" for d in indexer.load()["docs"]}
        for r in self.rows:
            for e in r["expect"]:
                with self.subTest(target=e):
                    self.assertIn(e, known)

    def test_the_set_stays_bilingual(self):
        """La partie française est le seul test de ce dépôt qui mesure un
        utilisateur francophone. La supprimer ferait monter le score global :
        c'est précisément pourquoi elle est vérifiée."""
        langs = {r.get("lang") for r in self.rows}
        self.assertEqual(langs, {"en", "fr"})
        self.assertGreaterEqual(sum(1 for r in self.rows if r.get("lang") == "fr"), 4)

    def test_the_report_tool_runs_on_it(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "eval_report.py"),
                            "--set", "evals/senior-dev.jsonl"],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("@1", r.stdout)
        self.assertIn("[fr]", r.stdout)


class TestDocsDoNotCiteScriptsThatDoNotExist(unittest.TestCase):
    """Provenance.md renvoyait à `tools/sync_upstream.sh` avant qu'il existe.
    Un document qui nomme un outil absent coûte une heure à celui qui le croit."""

    def test_every_tools_path_cited_in_docs_exists(self):
        missing = []
        for doc in list((ROOT / "docs").glob("*.md")) + [ROOT / "vendor" / "ecc" / "PROVENANCE.md",
                                                        ROOT / "README.md"]:
            if not doc.is_file():
                continue
            for m in re.finditer(r"(?:tools|perf)/[A-Za-z0-9_.-]+\.(?:py|sh|js)", doc.read_text()):
                if not (ROOT / m.group(0)).is_file():
                    missing.append(f"{doc.name}: {m.group(0)}")
        self.assertEqual(sorted(set(missing)), [])
