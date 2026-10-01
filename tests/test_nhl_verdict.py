import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import nhl_verdict as V  # noqa: E402

MID = date(2027, 1, 15)      # hors debut de saison
EARLY = date(2026, 10, 1)


def game(p_mod, p_mkt, p, statut="pret", detail="MoneyPuck 2025: GSAx +1.0 en 40 h"):
    gl = {"name": "G", "confirmed": statut == "pret", "detail": detail}
    return {"statut": statut, "goalies": {"home": dict(gl), "away": dict(gl, name="H")},
            "model_lines": [{"marche": "nhl_puck", "selection": "X -1.5", "prob_modele": p_mod,
                             "prob_marche": p_mkt, "prob": p, "min_odds": 1.0}]}


class VerdictTest(unittest.TestCase):
    def test_real_edge_is_flagged_to_look_at(self):
        v = V.verdict(game(0.50, 0.44, 0.50), MID)
        self.assertEqual(v["decision"], "regarder")
        self.assertEqual(v["selection"], "X -1.5")
        self.assertGreaterEqual(v["attendu"], v["exiger"])

    def test_small_edge_is_a_pass(self):
        self.assertEqual(V.verdict(game(0.47, 0.45, 0.456), MID)["decision"], "passer")

    def test_flags_shrink_toward_market(self):
        plain = V.verdict(game(0.50, 0.44, 0.50), MID)
        early = V.verdict(game(0.50, 0.44, 0.50), EARLY)
        self.assertLess(early["prob"], plain["prob"])
        self.assertGreater(early["exiger"], plain["exiger"])

    def test_goalie_without_data_is_flagged(self):
        v = V.verdict(game(0.50, 0.44, 0.50, detail="% arrets ajuste (0 tirs)"), MID)
        self.assertTrue(any("aucune donnée" in r for r in v["raisons"]))
        self.assertEqual(v["decision"], "passer")

    def test_huge_gap_is_distrusted(self):
        v = V.verdict(game(0.62, 0.39, 0.459), MID)
        self.assertTrue(any("info que le modèle n'a pas" in r for r in v["raisons"]))

    def test_waiting_game_is_provisional_never_to_look_at(self):
        v = V.verdict(game(0.50, 0.44, 0.50, statut="en_attente"), MID)
        self.assertEqual(v["decision"], "attente")
        self.assertTrue(v["titre"].startswith("Provisoire"))

    def test_model_only_lines_are_never_picked(self):
        v = V.verdict(game(0.60, None, 0.60), MID)
        self.assertEqual(v["decision"], "passer")
        self.assertNotIn("selection", v)


if __name__ == "__main__":
    unittest.main()
