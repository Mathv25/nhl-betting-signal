import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import nhl_verdict as V  # noqa: E402


def line(sel="X -1.5", p_mkt=0.40, proxy=None, p_mod=0.50):
    min_odds = round(1.03 / p_mkt, 2) if p_mkt else None
    return {"marche": "nhl_puck", "selection": sel, "prob_modele": p_mod, "prob_marche": p_mkt,
            "prob": p_mkt, "fair_odds": round(1 / p_mkt, 3) if p_mkt else None,
            "min_odds": min_odds, "proxy_odds": proxy, "proxy_book": "fanduel" if proxy else "",
            "a_verifier": bool(proxy and min_odds and proxy >= min_odds)}


def game(lines, statut="pret"):
    gl = {"name": "G", "confirmed": statut == "pret", "detail": "MoneyPuck"}
    return {"statut": statut, "goalies": {"home": dict(gl), "away": dict(gl, name="H")},
            "model_lines": lines}


class VerdictTest(unittest.TestCase):
    def test_soft_book_above_min_is_flagged(self):
        v = V.verdict(game([line(proxy=2.70), line("Y +1.5", 0.60, 1.60)]))
        self.assertEqual(v["decision"], "regarder")
        self.assertEqual(v["selection"], "X -1.5")
        self.assertEqual(v["exiger"], round(1.03 / 0.40, 2))
        self.assertIn("fanduel", v["titre"])

    def test_soft_books_below_min_is_a_pass(self):
        v = V.verdict(game([line(proxy=2.45)]))
        self.assertEqual(v["decision"], "passer")

    def test_model_disagreement_alone_never_flags(self):
        # Ancien defaut: modele 58 % vs marche 41 % -> « a regarder ». Plus maintenant.
        v = V.verdict(game([line(p_mkt=0.41, p_mod=0.58, proxy=2.30)]))
        self.assertEqual(v["decision"], "passer")
        self.assertTrue(any("information seulement" in r for r in v["raisons"]))

    def test_no_market_is_a_pass(self):
        v = V.verdict(game([line(p_mkt=None)]))
        self.assertEqual(v["decision"], "passer")
        self.assertNotIn("selection", v)

    def test_waiting_game_is_provisional(self):
        v = V.verdict(game([line(proxy=2.70)], statut="en_attente"))
        self.assertEqual(v["decision"], "attente")
        self.assertTrue(v["titre"].startswith("Provisoire"))


if __name__ == "__main__":
    unittest.main()
