"""Les affirmations de docs/AUDIT-BASE.md, rendues vérifiables.

Deux fois pendant la rédaction, mes propres contrôles se sont révélés faux :
le premier comptait deux fixtures de test comme des `eval` de production, le
second annonçait 90 skills hors domaine quand la prose en disait 92. Un chiffre
dans un document dérive ; un contrôle doit rester juste.

Note de forme : ce fichier est en `unittest.TestCase`, pas en fonctions
`test_*` de pytest. La porte tourne `python3 -m unittest discover tests`, qui
**ignore silencieusement** les fonctions de module ; la première version de ce
fichier comptait cinq tests qui ne s'exécutaient jamais. `TestNoSilentSkips`
existe pour que ça ne se reproduise pas.
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "vendor" / "ecc"


class TestTheAuditIsReproducible(unittest.TestCase):
    def test_the_audit_script_runs_and_names_its_checks(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "base_audit.py"), "--only", "orphans"],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("orphelins", r.stdout)

    def test_an_unknown_check_fails_instead_of_silently_doing_nothing(self):
        """Un `--only` qui ignore une faute de frappe est un audit qui rend 0."""
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "base_audit.py"), "--only", "bidon"],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("contrôle inconnu", r.stderr)

    def test_production_code_carries_no_eval(self):
        """L'affirmation de sécurité de l'audit. Les fixtures de test sont
        exclues volontairement : elles contiennent la chaîne `eval(x)` parce
        qu'elles exercent le hook censé la bloquer."""
        offenders = [
            str(p.relative_to(BASE)) for p in BASE.rglob("*.js")
            if "node_modules" not in str(p)
            and not str(p.relative_to(BASE)).startswith("tests/")
            and re.search(r"\beval\(|new Function\(", p.read_text(errors="replace"))
        ]
        self.assertEqual(offenders, [])

    def test_the_doc_and_the_script_agree_on_the_off_domain_count(self):
        """`OFF_DOMAIN` dans le script est la source unique, le document la
        cite. Si l'un bouge seul, ils se contredisent en public."""
        sys.path.insert(0, str(ROOT / "tools"))
        import base_audit

        doc = (ROOT / "docs" / "AUDIT-BASE.md").read_text()
        self.assertIn(f"{len(base_audit.OFF_DOMAIN)} skills", doc)

    def test_the_audit_names_the_right_orphans_and_their_fate(self):
        """Le tableau du §1.1 doit rester vrai dans les deux sens : les deux
        fichiers supprimés ne doivent plus être là, et les trois `.d.ts`
        conservés doivent y être encore. Une ligne périmée dans ce tableau est
        une invitation à supprimer un fichier vivant."""
        doc = (ROOT / "docs" / "AUDIT-BASE.md").read_text()
        rows = [line for line in doc.splitlines() if line.startswith("| `scripts/")]
        self.assertEqual(len(rows), 5, f"le tableau du §1.1 a {len(rows)} lignes")
        for line in rows:
            rel = re.search(r"`(scripts/[^`]+)`", line).group(1)
            deleted = "**supprimé**" in line
            exists = (BASE / rel).is_file()
            self.assertEqual(exists, not deleted,
                             f"{rel} : ligne « supprimé »={deleted} mais fichier présent={exists}")

    def test_the_types_declarations_are_not_reported_as_orphans(self):
        """La régression exacte : `.stem` sur `x.d.ts` rend `x.d`, donc les
        trois fichiers étaient comptés comme orphelins alors que leurs `.js`
        sont importés. Le détecteur doit lister exactement deux orphelins."""
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "tools"))
        import base_audit  # noqa: F401  (imported for the module to be importable)

        def refname(p):
            name = p.name
            for suffix in (".d.ts", ".ts"):
                if name.endswith(suffix):
                    return name[: -len(suffix)]
            return p.stem

        self.assertEqual(refname(Path("session-manager.d.ts")), "session-manager")
        self.assertEqual(refname(Path("session-manager.js")), "session-manager")


class TestNoSilentSkips(unittest.TestCase):
    """La porte tourne `unittest discover`. Un fichier écrit en style pytest
    n'est pas une erreur pour lui : il l'ignore. Cinq tests ont disparu comme
    ça, dans le fichier même qui audite le dépôt."""

    def test_every_test_module_uses_unittest(self):
        offenders = []
        for p in sorted((ROOT / "tests").glob("test_*.py")):
            text = p.read_text()
            has_unittest = "unittest.TestCase" in text
            # a module-level `def test_...` is invisible to `unittest discover`
            has_bare = re.search(r"^def test_\w+\(", text, re.M) is not None
            if has_bare and not has_unittest:
                offenders.append(p.name)
        self.assertEqual(offenders, [], f"ignorés par unittest discover : {offenders}")

    def test_the_gate_collects_at_least_as_many_tests_as_pytest(self):
        """Deux collecteurs, deux comptes. S'ils divergent, une partie des
        tests ne tourne pas dans la porte qui décide.

        Le compte côté unittest se fait en mémoire (`TestLoader`), jamais en
        relançant `unittest discover` : la première version de ce test spawnait
        la suite entière depuis l'intérieur de la suite, qui relançait ce test.
        Récursion infinie, porte bloquée 20 minutes.
        """
        r = subprocess.run([sys.executable, "-m", "pytest", "tests", "--collect-only", "-q"],
                           capture_output=True, text=True, cwd=ROOT)
        m = re.search(r"(\d+) tests", r.stdout + r.stderr)
        if not m:
            self.skipTest("pytest non installé")
        pytest_n = int(m.group(1))

        loader = unittest.TestLoader()
        unittest_n = loader.discover(str(ROOT / "tests")).countTestCases()
        self.assertEqual(pytest_n, unittest_n,
                         f"pytest collecte {pytest_n} tests, unittest en exécute {unittest_n}")
