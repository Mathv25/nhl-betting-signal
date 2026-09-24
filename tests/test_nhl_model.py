"""
Modele LNH (2026-09-24): Dixon-Coles, filet desert, prolongation/fusillade,
gardien partant et statut « en attente ». Aucun appel reseau.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import nhl_dixon_coles as DC    # noqa: E402
import nhl_goalies as NG        # noqa: E402


def total(m):
    return sum(map(sum, m))


class TestDixonColes(unittest.TestCase):

    def test_matrix_is_a_distribution(self):
        for rho in (-0.15, 0.0, 0.1):
            self.assertAlmostEqual(total(DC.reg_matrix(2.9, 2.6, rho)), 1.0, places=9)

    def test_rho_zero_is_independent_poisson(self):
        m = DC.reg_matrix(2.9, 2.6, 0.0)
        p = lambda l, k: math.exp(-l) * l ** k / math.factorial(k)
        self.assertAlmostEqual(m[1][1], p(2.9, 1) * p(2.6, 1) / sum(
            p(2.9, h) * p(2.6, a) for h in range(13) for a in range(13)), places=9)

    def test_negative_rho_adds_low_score_draws(self):
        # rho < 0: plus de 0-0 et de 1-1 qu'un Poisson independant
        self.assertGreater(DC.reg_matrix(2.9, 2.6, -0.1)[0][0], DC.reg_matrix(2.9, 2.6, 0.0)[0][0])
        self.assertGreater(DC.reg_matrix(2.9, 2.6, -0.1)[1][1], DC.reg_matrix(2.9, 2.6, 0.0)[1][1])

    def test_only_the_four_low_scores_are_corrected(self):
        for h, a in ((2, 1), (0, 2), (3, 3)):
            self.assertEqual(DC.tau(h, a, 3.0, 2.5, -0.1), 1.0)


class TestEmptyNet(unittest.TestCase):

    def test_mass_moves_from_one_goal_to_two_goal_margins(self):
        base = DC.reg_matrix(2.9, 2.6, -0.05)
        en = DC.with_empty_net(base, {1: 0.4, 2: 0.25}, 0.15)
        self.assertAlmostEqual(total(en), 1.0, places=9)
        m1 = lambda m: sum(m[h][a] for h in range(len(m)) for a in range(len(m)) if abs(h - a) == 1)
        m2 = lambda m: sum(m[h][a] for h in range(len(m)) for a in range(len(m)) if abs(h - a) == 2)
        self.assertLess(m1(en), m1(base))
        self.assertGreater(m2(en), m2(base))

    def test_empty_net_raises_totals_and_minus_1_5(self):
        p0 = {"en_q": {1: 0.0, 2: 0.0}, "en_q2": 0.0}
        g0, g1 = DC.game_probs(3.1, 2.8, p0), DC.game_probs(3.1, 2.8)
        self.assertGreater(g1["over"](5.5), g0["over"](5.5))
        self.assertGreater(g1["home_-1.5"], g0["home_-1.5"])
        # le vainqueur ne change pas: un but dans un filet desert ne renverse rien
        self.assertAlmostEqual(g1["reg_tie"], g0["reg_tie"], places=9)


class TestOvertime(unittest.TestCase):

    def test_two_way_moneyline_sums_to_one(self):
        g = DC.game_probs(3.0, 2.7)
        self.assertAlmostEqual(g["home_ml"] + g["away_ml"], 1.0, places=9)
        self.assertAlmostEqual(g["reg_home"] + g["reg_away"] + g["reg_tie"], 1.0, places=9)

    def test_equal_teams_split_extra_time(self):
        p = {"ot_home": 0.0, "so_home": 0.5}
        self.assertAlmostEqual(DC.ot_home_prob(3.0, 3.0, p), 0.5, places=9)

    def test_better_team_gets_a_small_overtime_premium(self):
        self.assertGreater(DC.ot_home_prob(3.4, 2.6, {"ot_home": 0.0, "ot_k": 0.5, "so_home": 0.5}), 0.5)
        self.assertLess(DC.ot_home_prob(3.4, 2.6, {"ot_home": 0.0, "ot_k": 0.5, "so_home": 0.5}), 0.6)

    def test_a_tied_game_never_covers_minus_1_5(self):
        g = DC.game_probs(3.0, 3.0)
        # -1.5 des deux cotes + egalites + victoires par 1 = 1
        m = DC.final_matrix(3.0, 3.0)
        by1 = sum(m[h][a] for h in range(len(m)) for a in range(len(m)) if abs(h - a) == 1)
        self.assertAlmostEqual(g["home_-1.5"] + g["away_-1.5"] + g["reg_tie"] + by1, 1.0, places=9)

    def test_tied_games_add_one_goal_to_the_book_total(self):
        # 0.5 de lambda de chaque cote: presque tout finit 0-0 -> total officiel 1
        g = DC.game_probs(0.3, 0.3, {"reg_share": 1.0, "en_q": {1: 0, 2: 0}, "en_q2": 0})
        self.assertGreater(g["over"](0.5), 0.99)


class TestGoalie(unittest.TestCase):

    def test_good_goalie_lowers_opponent_lambda(self):
        self.assertLess(DC.goalie_multiplier(20.0, 3000 * 60), 1.0)
        self.assertGreater(DC.goalie_multiplier(-20.0, 3000 * 60), 1.0)

    def test_small_samples_are_shrunk(self):
        big = DC.goalie_multiplier(10.0, 3000 * 60)
        small = DC.goalie_multiplier(1.0, 300 * 60)      # meme GSAx/60, 10x moins de glace
        self.assertLess(abs(1 - small), abs(1 - big))

    def test_bounds(self):
        self.assertGreaterEqual(DC.goalie_multiplier(500.0, 3600 * 10), 0.80)
        self.assertLessEqual(DC.goalie_multiplier(-500.0, 3600 * 10), 1.20)

    def test_only_confirmed_counts(self):
        self.assertTrue(NG.is_confirmed("Confirmed"))
        for s in ("Likely", "Unconfirmed", "", None, "Not confirmed"):
            self.assertFalse(NG.is_confirmed(s), s)


class _Lineup:
    def __init__(self, confirmed):
        self.confirmed = confirmed

    def is_back_to_back(self, *a):
        return False

    def get_starter(self, team):
        return f"G {team}", self.confirmed, "Confirmed" if self.confirmed else "Likely"


class TestWaitingStatus(unittest.TestCase):

    def _calc(self, confirmed):
        import edge_calculator as EC
        import nhl_goalies
        c = EC.EdgeCalculator.__new__(EC.EdgeCalculator)
        c.lineup = _Lineup(confirmed)
        c.team_stats = type("T", (), {"get": lambda self, t: {"gf_pg": 3.1, "ga_pg": 3.0}})()
        c._get_recent_stats = lambda t: {"days_rest": 1}
        c._hybrid_stats = lambda s, r: {"gf_pg": 3.1, "ga_pg": 3.0}
        c._motivation = lambda t: 1.0
        orig = nhl_goalies.multiplier
        nhl_goalies.multiplier = lambda name, today=None: (1.0, "test")
        try:
            game = {"home_team": "H", "away_team": "A", "commence_time": "2030-01-01T23:00:00Z",
                    "markets": {"moneyline": {"home": {"team": "H", "odds_decimal": 2.5, "implied_prob": 40.0},
                                              "away": {"team": "A", "odds_decimal": 2.5, "implied_prob": 40.0}}}}
            edges = c.calculate_all_edges(game)
        finally:
            nhl_goalies.multiplier = orig
        return game, edges

    def test_unconfirmed_goalie_means_waiting_and_no_signal(self):
        game, edges = self._calc(False)
        self.assertEqual(game["statut"], "en_attente")
        self.assertEqual(edges, [])
        self.assertTrue(all(l["statut"] == "en_attente" for l in game["model_lines"]))

    def test_confirmed_goalies_are_ready(self):
        game, _ = self._calc(True)
        self.assertEqual(game["statut"], "pret")
        ml = [l for l in game["model_lines"] if l["marche"] == "nhl_ml"]
        self.assertAlmostEqual(sum(l["prob_modele"] for l in ml), 1.0, places=3)

    def test_waiting_games_are_not_journaled(self):
        import prediction_capture as PC
        from datetime import datetime, timezone
        game, _ = self._calc(False)
        self.assertEqual(PC.nhl_rows([{"game": game}], "2029-12-31",
                                     datetime(2029, 12, 31, tzinfo=timezone.utc)), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
