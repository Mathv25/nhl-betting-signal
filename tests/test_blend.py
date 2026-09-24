"""
Melange modele-marche (blend.py) et estimation walk-forward du poids w
(blend_backtest.py). Donnees synthetiques: le vrai w est connu.
"""
import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import betting_config            # noqa: E402
import blend                     # noqa: E402
import blend_backtest as BB      # noqa: E402
import predictions_log as PL      # noqa: E402


class TestBlend(unittest.TestCase):

    def test_formula_with_default_weight(self):
        p, src = blend.p_final(0.60, 0.50, "mlb_ml")
        self.assertAlmostEqual(p, 0.3 * 0.60 + 0.7 * 0.50, places=9)
        self.assertIn("w=0.3", src)

    def test_moneyline_without_market_shrinks_to_half(self):
        self.assertAlmostEqual(blend.p_final(0.70, None, "nhl_ml")[0], 0.5 + 0.3 * 0.2, places=9)

    def test_ladder_without_market_keeps_the_model(self):
        self.assertEqual(blend.p_final(0.83, None, "props_k")[0], 0.83)

    def test_floor_odds_is_zero_edge(self):
        p = blend.p_final(0.60, 0.50, "mlb_ml")[0]
        self.assertAlmostEqual(p * blend.floor_odds(p), 1.0, places=2)

    def test_edge_uses_p_final_not_p_model(self):
        import record_prediction as RP
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        os.remove(path)
        try:
            row = RP.record({"sport": "nfl", "marche": "nfl_ml", "selection": "x", "date": "2026-09-27",
                             "prob_modele": 0.60, "prob_finale": 0.53, "cote_prise": 2.0}, path)
            self.assertAlmostEqual(float(row["edge"]), 6.0, places=2)     # 0.53 x 2 - 1
        finally:
            if os.path.exists(path):
                os.remove(path)


def synthetic(n, w_true, seed=1):
    """Issue tiree avec p = w_true * modele + (1 - w_true) * marche."""
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        pk = rnd.uniform(0.3, 0.7)
        pm = min(max(pk + rnd.uniform(-0.25, 0.25), 0.02), 0.98)
        p = w_true * pm + (1 - w_true) * pk
        rows.append({"marche": "mlb_ml", "date": f"2026-{7 + i // 300:02d}-{1 + (i // 10) % 28:02d}",
                     "prob_modele": pm, "prob_marche_novig": pk,
                     "resultat": "W" if rnd.random() < p else "L"})
    return rows


class TestWalkForward(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.csv = os.path.join(self.dir, "p.csv")
        self.cfg = os.path.join(self.dir, "betting.json")
        with open(self.cfg, "w") as f:
            json.dump({"BLEND_W": {"default": 0.3}}, f)
        os.environ["PREDICTIONS_PATH"] = self.csv
        os.environ["BETTING_CONFIG"] = self.cfg
        betting_config.reset()
        self._out = BB.OUT
        BB.OUT = os.path.join(self.dir, "bb.json")

    def tearDown(self):
        os.environ.pop("PREDICTIONS_PATH", None)
        os.environ.pop("BETTING_CONFIG", None)
        betting_config.reset()
        BB.OUT = self._out

    def test_waits_for_200_settled_rows(self):
        PL.save(synthetic(150, 0.6))
        e = BB.run()["marches"]["mlb_ml"]
        self.assertTrue(e["statut"].startswith("attente"))
        self.assertNotIn("w_optimal", e)

    def test_recovers_an_informative_model(self):
        PL.save(synthetic(3000, 0.7, seed=3))
        e = BB.run()["marches"]["mlb_ml"]
        self.assertGreaterEqual(e["w_optimal"], 0.5)
        self.assertLess(e["logloss_walk_forward"], e["logloss_marche_seul"])

    def test_useless_model_gets_little_weight(self):
        PL.save(synthetic(3000, 0.0, seed=4))
        e = BB.run()["marches"]["mlb_ml"]
        self.assertLessEqual(e["w_optimal"], 0.15)

    def test_walk_forward_never_sees_the_day_it_predicts(self):
        # Jour 2: issues inversees par rapport au modele. Si le w du jour 2
        # utilisait le jour 2, il chuterait; entraine sur le jour 1 seul, il
        # reste celui du jour 1.
        rnd = random.Random(7)
        items = []
        for d, sign in (("2026-07-01", 1), ("2026-07-02", -1)):
            for _ in range(300):
                pk = 0.5
                pm = 0.5 + sign * rnd.choice([-0.3, 0.3])
                y = 1 if (pm > 0.5) == (sign > 0) else 0
                items.append((d, pm if sign > 0 else 1 - pm, pk, y))
        wf = BB.walk_forward(items, 0.3)
        self.assertEqual(wf["w_dernier"], BB.best_w([(pm, pk, y) for d, pm, pk, y in items if d == "2026-07-01"]))

    def test_apply_writes_the_config_only_when_better(self):
        import model_version
        PL.save(synthetic(3000, 0.8, seed=5))
        orig = model_version.bump
        model_version.bump = lambda reason, today=None: "test"   # ne pas reecrire le vrai fichier
        try:
            rep = BB.run(apply=True)
        finally:
            model_version.bump = orig
        self.assertEqual(rep["version"], "test", "un w applique incremente la version")
        self.assertIn("mlb_ml", rep.get("applique", {}))
        betting_config.reset()
        self.assertAlmostEqual(betting_config.blend_w("mlb_ml"), rep["applique"]["mlb_ml"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
