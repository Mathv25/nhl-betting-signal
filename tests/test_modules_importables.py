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

    def test_rendu_avec_props_nfl(self):
        """Le chemin des props, celui-la meme qui avait casse."""
        from report_generator import ReportGenerator
        rg = ReportGenerator()
        etat = {
            "week": "2026-09-08", "stale": False, "min_edge": 3.0, "min_total": 47.0,
            "requests_week": 9, "max_requests": 40, "n_scanned": 1, "n_games": 1,
            "n_signals": 2,
            "signals": [
                {"type": "cote", "joueur": "Matthew Stafford",
                 "market": "player_rush_yds", "marche_lbl": "verges au sol",
                 "selection": "Matthew Stafford Over 0.5", "side": "Over", "ligne": 0.5,
                 "prob": 41.0, "odds": 2.54, "book": "fanduel", "fair_odds": 2.44,
                 "edge_pct": 4.2, "source": "pinnacle", "n_books": 4,
                 "game": "SF @ LAR", "books": [{"book": "fanduel", "ligne": 0.5,
                                                "over": 2.54, "under": 1.5}]},
                {"type": "ligne", "joueur": "Brock Purdy",
                 "market": "player_pass_yds", "marche_lbl": "verges de passe",
                 "selection": "Brock Purdy middle 238.5-245.5", "fenetre": 7.0,
                 "breakeven": 6.8, "edge_pct": 0.0,
                 "over": {"ligne": 238.5, "odds": 1.90, "book": "draftkings"},
                 "under": {"ligne": 245.5, "odds": 1.87, "book": "fanatics"},
                 "game": "SF @ LAR", "books": [{"book": "draftkings", "ligne": 238.5,
                                                "over": 1.90, "under": 1.88}]},
            ],
        }
        html = rg._nfl_props_section(etat)
        self.assertIn("Matthew Stafford", html)
        self.assertIn("Brock Purdy", html)
        self.assertIn("6.8", html)          # rentabilite exigee du middle
        self.assertNotIn("None", html)

    def test_rendu_props_vide(self):
        from report_generator import ReportGenerator
        html = ReportGenerator()._nfl_props_section(
            {"week": "2026-09-08", "signals": [], "n_signals": 0,
             "requests_week": 0, "max_requests": 40, "n_scanned": 0, "n_games": 0})
        self.assertIn("Aucun signal", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
