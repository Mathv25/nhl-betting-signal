"""
Garde-fou d'integrite: chaque module de src/ doit compiler et s'importer.

Existe pour une panne precise. Une erreur de syntaxe dans report_generator.py
est passee en production: la suite de tests etait verte parce qu'aucun test
n'importait ce module, et le signal horaire echouait a chaque execution avec
un SyntaxError. Le dashboard est reste fige plusieurs cycles.

Un test qui ne fait qu'importer parait pauvre; il aurait attrape celle-la en
une seconde.
"""
import os
import py_compile
import sys
import unittest

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, SRC)

# Modules qui parlent au reseau ou lisent des fichiers au chargement: on les
# compile sans les importer.
COMPILE_SEULEMENT = {"signal.py"}


def modules():
    return sorted(f for f in os.listdir(SRC) if f.endswith(".py"))


class TestTousLesModulesCompilent(unittest.TestCase):

    def test_syntaxe(self):
        for f in modules():
            with self.subTest(module=f):
                try:
                    py_compile.compile(os.path.join(SRC, f), doraise=True)
                except py_compile.PyCompileError as e:
                    self.fail(f"{f} ne compile pas: {e}")

    def test_import(self):
        for f in modules():
            if f in COMPILE_SEULEMENT:
                continue
            with self.subTest(module=f):
                __import__(f[:-3])


class TestDashboardSeGenere(unittest.TestCase):
    """
    Le generateur doit produire un HTML complet a partir d'un signal minimal.
    Compiler ne suffit pas: une cle manquante ou un format casse ne se voit
    qu'a l'execution, et personne ne le remarque avant que la page soit figee.
    """

    def test_rendu_minimal(self):
        import tempfile
        from report_generator import ReportGenerator

        data = {
            "date": "2026-09-10", "generated_at": "2026-09-10T18:00:00+00:00",
            "total_games": 0, "total_value_bets": 0, "signals": [], "value_bets": [],
            "props_analysis": [], "nba_analysis": [], "mlb_analysis": [],
            "mlb_ml_analysis": [], "power_analysis": [],
            "odds_api": {"remaining": 1000, "healthy": True, "credits_spent": 0,
                         "cache_hits": 0, "day_budget": 100, "spent_today": 0,
                         "regions": "us,eu"},
        }
        cwd = os.getcwd()
        tmp = tempfile.mkdtemp(prefix="rg")
        os.makedirs(os.path.join(tmp, "src"), exist_ok=True)
        os.chdir(os.path.join(tmp, "src"))
        try:
            ReportGenerator().generate_html(data)
            html = open(os.path.join(tmp, "docs", "index.html"), encoding="utf-8").read()
        finally:
            os.chdir(cwd)
        self.assertGreater(len(html), 10000)
        self.assertIn("</html>", html)
        self.assertIn("tab-nfl", html)

    def test_rendu_onglet_nfl(self):
        """L'onglet NFL (nfl_tab) se rend avec et sans props."""
        from report_generator import ReportGenerator
        rg = ReportGenerator()
        line = {"joueur": "Puka Nacua", "market": "player_reception_yds",
                "marche": "nfl_prop_reception_yds", "marche_lbl": "verges de reception",
                "ligne": 80.5, "p_over": 0.5, "p_under": 0.5, "refs": [],
                "game": "SF @ LAR", "commence": "2099-09-27T17:00:00Z", "event_id": "e1"}
        html = rg._nfl_section({"week": "2026-09-08", "games": [],
                                "props": {"lines": [line]}})
        self.assertIn("Puka Nacua", html)
        self.assertIn("À MISER", html)
        self.assertNotIn("None", html)
        vide = rg._nfl_section({"week": "2026-09-08", "games": [], "props": {}})
        self.assertIn("Aucune prop Pinnacle exploitable", vide)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestLectureDeStatsVides(unittest.TestCase):
    """
    L'API MLB renvoie `{"stats": []}` pour un joueur sans statistiques sur la
    periode demandee. `data.get("stats", [{}])[0]` ne protege que la cle
    ABSENTE: la liste existe, elle est vide, et l'indexation leve IndexError.

    C'est ce qui a fait tomber le signal horaire le 10 septembre, sur un
    frappeur des Pirates. Le motif etait present neuf fois dans src/.
    """

    def test_aucun_module_n_indexe_stats_sans_protection(self):
        import re
        motif = re.compile(r'\.get\("stats",\s*\[\{\}\]\)\[0\]')
        fautifs = []
        for f in modules():
            t = open(os.path.join(SRC, f), encoding="utf-8").read()
            if motif.search(t):
                fautifs.append(f)
        self.assertEqual(fautifs, [], "indexation non protegee de `stats`")

    def test_les_trois_formes_de_reponse(self):
        for payload, attendu in (({"stats": []}, []),
                                 ({}, []),
                                 ({"stats": [{"splits": [1, 2]}]}, [1, 2])):
            self.assertEqual((payload.get("stats") or [{}])[0].get("splits", []),
                             attendu)
