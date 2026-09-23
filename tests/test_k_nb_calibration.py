"""
Binomiale negative K, calibration par barreau, journal des predictions et
dedoublonnage des cartes (chantier du 2026-09-23).

Lancer:  python3 -m unittest discover -s tests -v
Aucun appel reseau.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import mlb_k_distribution as KD          # noqa: E402
import k_calibration as KCAL             # noqa: E402
import predictions_log as PL             # noqa: E402


class TestNegativeBinomial(unittest.TestCase):
    MU, SIGMA = 6.86, 2.83

    def test_pmf_sums_to_one(self):
        total = sum(KD.nb_pmf(self.MU, self.SIGMA ** 2, k) for k in range(26))
        self.assertAlmostEqual(total, 1.0, delta=0.001)

    def test_easy_rung_is_high(self):
        self.assertGreater(KD.nb_at_least(self.MU, self.SIGMA ** 2, 3), 0.88)

    def test_median_rung_is_near_half(self):
        p7 = KD.nb_at_least(self.MU, self.SIGMA ** 2, 7)
        self.assertGreaterEqual(p7, 0.45)
        self.assertLessEqual(p7, 0.55)

    def test_at_least_is_one_minus_cdf(self):
        cdf = sum(KD.nb_pmf(self.MU, self.SIGMA ** 2, k) for k in range(7))
        self.assertAlmostEqual(KD.nb_at_least(self.MU, self.SIGMA ** 2, 7), 1 - cdf, places=9)

    def test_poisson_fallback_when_not_overdispersed(self):
        from scipy.stats import poisson
        for var in (6.0, 6.86):                 # var <= mu
            self.assertAlmostEqual(KD.nb_at_least(6.86, var, 7),
                                   float(poisson.sf(6, 6.86)), places=9)

    def test_model_uses_global_dispersion(self):
        m = KD.build_k_model(6.35)
        self.assertEqual(m["kind"], "nb")
        self.assertAlmostEqual(KD.moments(m)["var"], 6.35 + 6.35 ** 2 / KD.K_NB_R, places=3)

    def test_projection_carries_the_mu_factor(self):
        import mlb_props_analyzer as MPA
        proj = MPA._k_projection(6.0, 0.22, 0.22, 1.0)
        self.assertAlmostEqual(proj["adj"], round(6.0 * KD.K_MU_FACTOR, 2), places=6)


def _rows(k, pairs):
    return [{"marche": KCAL.MARKET, "k": k, "prob_brute": p,
             "resultat": "W" if y else "L"} for p, y in pairs]


class TestPAV(unittest.TestCase):

    def test_increasing(self):
        self.assertEqual(KCAL.pav([1, 3, 2, 4]), [1, 2.5, 2.5, 4])

    def test_decreasing(self):
        self.assertEqual(KCAL.pav([0.9, 0.5, 0.6, 0.2], increasing=False),
                         [0.9, 0.55, 0.55, 0.2])


class TestRungCalibration(unittest.TestCase):

    def test_below_threshold_stays_raw(self):
        cal = KCAL.Calibrator(rows=_rows(6, [(0.6, 0)] * (KCAL.MIN_N - 1)))
        self.assertFalse(cal.is_calibrated(6))
        p, pc, n = cal.rung(6, 0.6)
        self.assertEqual((p, pc, n), (0.6, None, KCAL.MIN_N - 1))

    def test_calibrated_rung_shrinks_toward_raw(self):
        # 100 predictions a 0.60, 40% de reussite reelle
        rows = _rows(6, [(0.6, 1)] * 40 + [(0.6, 0)] * 60)
        cal = KCAL.Calibrator(rows=rows)
        p, pc, n = cal.rung(6, 0.6)
        self.assertEqual(n, 100)
        self.assertAlmostEqual(pc, 0.40, places=6)
        w = 100 / (100 + KCAL.SHRINK)
        self.assertAlmostEqual(p, w * 0.40 + (1 - w) * 0.60, places=6)

    def test_ladder_stays_decreasing_after_calibration(self):
        # K>=5 recalibre tres bas, K>=6 non calibre: le PAV doit reordonner
        rows = _rows(5, [(0.7, 0)] * 200)
        cal = KCAL.Calibrator(rows=rows)
        raw = {4: 0.8, 5: 0.7, 6: 0.55, 7: 0.4}
        out = cal.ladder(raw)
        probs = [out[k]["prob"] for k in sorted(out)]
        for a, b in zip(probs, probs[1:]):
            self.assertGreaterEqual(a, b)
        self.assertTrue(out[5]["calibrated"])
        self.assertFalse(out[6]["calibrated"])
        self.assertEqual(out[6]["prob_raw"], 0.55)


class TestPredictionsLog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False).name
        os.remove(self.tmp)

    def tearDown(self):
        if os.path.exists(self.tmp):
            os.remove(self.tmp)

    def _row(self, prob, start):
        return {"id": "d|mlb|props_k|X Over 5.5 K", "sport": "mlb", "marche": "props_k",
                "selection": "X Over 5.5 K", "prob_modele": prob, "commence_time": start}

    def test_update_before_start_then_freeze(self):
        now = datetime(2026, 9, 23, 18, tzinfo=timezone.utc)
        start = (now + timedelta(hours=2)).isoformat()
        self.assertEqual(PL.upsert([self._row(0.5, start)], self.tmp, now)["added"], 1)
        self.assertEqual(PL.upsert([self._row(0.6, start)], self.tmp, now)["updated"], 1)
        later = now + timedelta(hours=3)
        self.assertEqual(PL.upsert([self._row(0.9, start)], self.tmp, later)["frozen"], 1)
        rows = PL.load(self.tmp)
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0]["prob_modele"]), 0.6)

    def test_columns_requested_are_present(self):
        for c in ("timestamp", "sport", "marche", "selection", "prob_modele",
                  "prob_marche_novig", "cote_prise", "book", "edge", "mise_u",
                  "cote_fermeture", "resultat", "version_modele"):
            self.assertIn(c, PL.COLUMNS)


def _signal_module():
    # `signal` est aussi un module de la stdlib, deja importe: on charge
    # src/signal.py par son chemin.
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "signal.py")
    spec = importlib.util.spec_from_file_location("nhl_signal_main", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDedupe(unittest.TestCase):

    def test_same_game_same_pitcher_once(self):
        sig = _signal_module()
        g = {"event_id": "e1", "home_team": "BAL", "away_team": "TOR",
             "bets": [{"player": "A"}, {"player": "A"}, {"player": "B"}]}
        out = sig.dedupe_mlb_cards([g, dict(g)])
        self.assertEqual(len(out), 1)
        self.assertEqual([b["player"] for b in out[0]["bets"]], ["A", "B"])

    def test_doubleheader_stays_two_games(self):
        sig = _signal_module()
        g1 = {"event_id": "e1", "bets": [{"player": "A"}]}
        g2 = {"event_id": "e2", "bets": [{"player": "A"}]}
        self.assertEqual(len(sig.dedupe_mlb_cards([g1, g2])), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
