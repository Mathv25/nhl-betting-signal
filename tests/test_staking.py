"""
Gestion des mises (staking.py): Kelly 0.25, plafond 1.5% par pari, 3% par
soir avec reduction proportionnelle, cote plancher. Aucun appel reseau.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import staking as ST    # noqa: E402


class TestKelly(unittest.TestCase):

    def test_quarter_kelly(self):
        # p=0.55 a 2.00: f* = 0.10 -> 0.25 x 10% = 2.5% -> plafonne a 1.5%
        self.assertEqual(ST.kelly_pct(0.55, 2.0), 1.5)
        # p=0.52 a 2.00: f* = 0.04 -> 1.0%
        self.assertAlmostEqual(ST.kelly_pct(0.52, 2.0), 1.0, places=2)

    def test_no_edge_no_stake(self):
        self.assertEqual(ST.kelly_pct(0.50, 2.0), 0.0)
        self.assertEqual(ST.kelly_pct(0.45, 2.0), 0.0)
        self.assertEqual(ST.kelly_pct(0.5, 1.0), 0.0)

    def test_floor_odds_is_where_the_edge_vanishes(self):
        p = 0.537
        fl = ST.floor_odds(p)
        self.assertAlmostEqual(ST.kelly_pct(p, fl), 0.0, places=2)
        self.assertGreater(ST.kelly_pct(p, fl + 0.05), 0.0)


class TestNight(unittest.TestCase):

    def test_under_the_cap_is_untouched(self):
        adj, k = ST.plan_night([1.0, 1.5])
        self.assertEqual((adj, k), ([1.0, 1.5], 1.0))

    def test_over_the_cap_scales_everything_proportionally(self):
        adj, k = ST.plan_night([1.5, 1.5, 1.0])      # 4% > 3%
        self.assertLessEqual(sum(adj), 3.0, "le plafond du soir n'est jamais depasse")
        self.assertGreater(sum(adj), 2.97)
        self.assertAlmostEqual(adj[0] / adj[2], 1.5, delta=0.02)   # mises arrondies au centieme
        self.assertAlmostEqual(k, 0.75, places=4)

    def test_already_placed_stakes_use_up_the_room(self):
        adj, k = ST.plan_night([1.0, 1.0], already=2.0)
        self.assertAlmostEqual(sum(adj), 1.0, places=2)

    def test_apply_night_groups_by_evening(self):
        bets = [{"p_final": 0.56, "odds": 2.0, "date": "d1"} for _ in range(3)] + \
               [{"p_final": 0.56, "odds": 2.0, "date": "d2"}]
        ST.apply_night(bets)
        self.assertLessEqual(sum(b["stake_pct"] for b in bets[:3]), 3.0)
        self.assertGreater(sum(b["stake_pct"] for b in bets[:3]), 2.97)
        self.assertEqual(bets[3]["stake_pct"], 1.5)

    def test_every_kelly_in_the_code_uses_the_same_rule(self):
        import odds_api, props_analyzer, nba_props_analyzer, mlb_props_analyzer
        self.assertEqual(odds_api.kelly_units(55.0, 2.0), 1.5)
        self.assertEqual(props_analyzer._kelly(55.0, 50.0, 2.0), 1.5)
        self.assertEqual(nba_props_analyzer._kelly(55.0, 50.0, 2.0), 1.5)
        self.assertEqual(mlb_props_analyzer._kelly(55.0, 50.0, 2.0), 1.5)

    def test_nfl_signal_stakes_are_capped_per_night(self):
        out = {"nfl_analysis": {"games": [
            {"commence": "2026-09-28T17:00:00Z", "signals": [
                {"statut": "a_miser", "prob": 56.0, "my_odds": 2.0, "stake_units": 9},
                {"statut": "a_miser", "prob": 56.0, "my_odds": 2.0, "stake_units": 9},
                {"statut": "a_miser", "prob": 56.0, "my_odds": 2.0, "stake_units": 9}]}]}}
        self.assertEqual(ST.apply_to_signal(out), 3)
        sigs = out["nfl_analysis"]["games"][0]["signals"]
        self.assertLessEqual(sum(s["stake_units"] for s in sigs), 3.0)
        self.assertGreater(sum(s["stake_units"] for s in sigs), 2.97)
        self.assertAlmostEqual(sigs[0]["floor_odds"], 1 / 0.56, places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
