"""
Point 3 (2026-09-23): journal des predictions, fermeture Pinnacle, resultats,
CLV et onglet Performance. Aucun appel reseau (faux client, scores en dur).
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import close_and_settle as CS    # noqa: E402
import odds_api                  # noqa: E402
import performance as PERF       # noqa: E402
import prediction_capture as PC  # noqa: E402
import import_results as IMP     # noqa: E402

NOW = datetime(2026, 9, 23, 22, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, events):
        self.events, self.calls = events, []

    def get(self, endpoint, params, cost=1):
        self.calls.append((endpoint, params, cost))
        return self.events


def pin_event(start, home_p=1.80, away_p=2.10, over=1.95, under=1.87, point=8.5):
    return {"id": "ev1", "home_team": "Boston Red Sox", "away_team": "Cleveland Guardians",
            "commence_time": start, "bookmakers": [{"key": "pinnacle", "markets": [
                {"key": "h2h", "outcomes": [{"name": "Boston Red Sox", "price": home_p},
                                            {"name": "Cleveland Guardians", "price": away_p}]},
                {"key": "totals", "outcomes": [{"name": "Over", "price": over, "point": point},
                                               {"name": "Under", "price": under, "point": point}]}]}]}


def row(**kw):
    r = {"sport": "mlb", "marche": "mlb_ml", "selection": "Boston Red Sox ML",
         "match": "Cleveland Guardians @ Boston Red Sox", "event_id": "ev1",
         "commence_time": (NOW + timedelta(minutes=20)).isoformat(), "date": "2026-09-23"}
    r.update(kw)
    return r


class TestClosing(unittest.TestCase):

    def test_closes_only_games_starting_soon(self):
        soon, later = row(), row(commence_time=(NOW + timedelta(hours=2)).isoformat())
        started = row(commence_time=(NOW - timedelta(minutes=5)).isoformat())
        cl = FakeClient([pin_event(soon["commence_time"])])
        n = CS.close([soon, later, started], now=NOW, client=cl)
        self.assertEqual(n, 1)
        self.assertTrue(soon.get("cote_fermeture"))
        self.assertFalse(later.get("cote_fermeture"))
        self.assertFalse(started.get("cote_fermeture"), "une cote en direct n'est pas une fermeture")

    def test_one_cheap_call_filtered_on_pinnacle(self):
        cl = FakeClient([pin_event(row()["commence_time"])])
        CS.close([row(), row(selection="Cleveland Guardians ML")], now=NOW, client=cl)
        self.assertEqual(len(cl.calls), 1)
        _, params, cost = cl.calls[0]
        self.assertEqual(params["bookmakers"], "pinnacle")
        self.assertEqual(cost, 2)

    def test_nothing_to_close_costs_nothing(self):
        cl = FakeClient([])
        CS.close([row(commence_time=(NOW + timedelta(hours=5)).isoformat())], now=NOW, client=cl)
        self.assertEqual(cl.calls, [])

    def test_fair_closing_is_shin_and_clv_uses_it(self):
        r = row(cote_prise="2.00", cote_reference="1.90")
        CS.close([r], now=NOW, client=FakeClient([pin_event(r["commence_time"])]))
        p = odds_api.devig([1.80, 2.10], "shin")[0]
        self.assertAlmostEqual(float(r["cote_fermeture"]), round(1 / p, 3), places=3)
        self.assertAlmostEqual(r["clv"], round(2.00 / r["cote_fermeture"] - 1, 4), places=4)
        self.assertAlmostEqual(r["clv_reference"], round(1.90 / r["cote_fermeture"] - 1, 4), places=4)

    def test_total_on_another_line_is_not_closed(self):
        r = row(marche="mlb_total", selection="Over 9.5")
        CS.close([r], now=NOW, client=FakeClient([pin_event(r["commence_time"], point=8.5)]))
        self.assertFalse(r.get("cote_fermeture"))

    def test_props_k_are_never_closed(self):
        r = row(marche="props_k", selection="X Over 5.5 K")
        cl = FakeClient([pin_event(r["commence_time"])])
        CS.close([r], now=NOW, client=cl)
        self.assertEqual(cl.calls, [])


class TestSettlement(unittest.TestCase):
    G = {"home": "Boston Red Sox", "away": "Cleveland Guardians", "hs": 5, "as": 3}

    def _res(self, marche, sel, g=None):
        return CS.settle_game_row(row(marche=marche, selection=sel), g or self.G)

    def test_moneyline(self):
        self.assertEqual(self._res("mlb_ml", "Boston Red Sox ML"), "W")
        self.assertEqual(self._res("mlb_ml", "Cleveland Guardians ML"), "L")

    def test_spread_and_push(self):
        self.assertEqual(self._res("mlb_rl", "Boston Red Sox -1.5"), "W")
        self.assertEqual(self._res("mlb_rl", "Cleveland Guardians +1.5"), "L")
        self.assertEqual(self._res("nfl_spread", "Boston Red Sox -2"), "P")

    def test_totals(self):
        self.assertEqual(self._res("mlb_total", "Over 7.5"), "W")
        self.assertEqual(self._res("mlb_total", "Under 7.5"), "L")
        self.assertEqual(self._res("mlb_total", "Over 8"), "P")

    def test_k_prop_and_non_starter(self):
        orig_k, orig_g = CS.pitcher_ks, CS._game_result
        try:
            CS._game_result = lambda r: self.G
            r1 = row(marche="props_k", joueur="A", k="6", selection="A Over 5.5 K",
                     commence_time=(NOW - timedelta(hours=6)).isoformat())
            r2 = dict(r1, joueur="B", selection="B Over 5.5 K")
            CS.pitcher_ks = lambda name, day: (7, True) if name == "A" else (0, False)
            CS.settle([r1, r2], now=NOW)
            self.assertEqual(r1["resultat"], "W")
            self.assertEqual(r2["resultat"], "VOID")
        finally:
            CS.pitcher_ks, CS._game_result = orig_k, orig_g

    def test_not_settled_before_the_game_is_over(self):
        r = row(commence_time=(NOW - timedelta(hours=1)).isoformat())
        CS.settle([r], now=NOW)
        self.assertFalse(r.get("resultat"))


class TestPerformance(unittest.TestCase):

    def test_ci_and_median(self):
        m = PERF.mean_ci([0.1, -0.1, 0.02, 0.04])
        self.assertAlmostEqual(m["mean"], 0.015, places=6)
        self.assertAlmostEqual(m["median"], 0.03, places=6)
        self.assertLess(m["ci_low"], m["mean"])
        self.assertGreater(m["ci_high"], m["mean"])

    def test_roi_uses_real_stakes_only(self):
        rows = [{"marche": "mlb_ml", "resultat": "W", "cote_prise": "2.0", "mise_u": "1"},
                {"marche": "mlb_ml", "resultat": "L", "cote_prise": "2.0", "mise_u": "2"},
                {"marche": "mlb_ml", "resultat": "W", "cote_reference": "5.0", "mise_u": "0"}]
        st = PERF.group_stats(rows)
        self.assertEqual(st["roi"]["n"], 2)
        self.assertAlmostEqual(st["roi"]["roi"], (1 - 2) / 3, places=6)

    def test_brier_model_vs_market_on_same_rows(self):
        rows = [{"marche": "nfl_ml", "resultat": "W", "prob_modele": "0.6", "prob_marche_novig": "0.5"},
                {"marche": "nfl_ml", "resultat": "L", "prob_modele": "0.3", "prob_marche_novig": "0.5"},
                {"marche": "nfl_ml", "resultat": "W", "prob_modele": "0.9"}]
        b = PERF.group_stats(rows)["brier"]
        self.assertEqual(b["n"], 2)
        self.assertAlmostEqual(b["modele"], (0.16 + 0.09) / 2, places=6)
        self.assertAlmostEqual(b["marche"], 0.25, places=6)

    def test_groups_and_epochs(self):
        rows = [{"marche": "nfl_spread", "resultat": "W", "prob_modele": "0.5"},
                {"marche": "props_k", "resultat": "L", "prob_modele": "0.5",
                 "version_modele": PERF.HIST}]
        rep = PERF.compute(rows)
        self.assertIn("NFL", rep["epoques"]["journal"]["groupes"])
        self.assertIn("Props K", rep["epoques"]["historique"]["groupes"])
        self.assertNotIn("win_rate", str(rep), "pas de taux de reussite comme indicateur")


class TestCapture(unittest.TestCase):

    def test_started_games_are_not_logged(self):
        g_live = {"commence": (NOW - timedelta(hours=1)).isoformat(), "home_team": "H", "away_team": "A",
                  "event_id": "x", "prob_marche": {}, "bets": [{"marche": "moneyline", "equipe": "H",
                                                                 "probabilite": 26.9, "prob_modele": 57.2, "cote": 10.0, "tier": "🟢"}]}
        g_pre = dict(g_live, commence=(NOW + timedelta(hours=1)).isoformat(), event_id="y")
        rows = PC.mlb_ml_rows([g_live, g_pre], "2026-09-23", NOW)
        self.assertEqual([r["event_id"] for r in rows], ["y"])
        self.assertEqual(rows[0]["cote_reference"], 10.0)
        self.assertEqual(rows[0]["selectionne"], 1)
        # modele seul dans prob_modele, melange dans prob_finale
        self.assertEqual(rows[0]["prob_modele"], 0.572)
        self.assertEqual(rows[0]["prob_finale"], 0.269)

    def test_stale_nfl_state_is_not_relogged(self):
        st = {"stale": True, "games": [{"commence": (NOW + timedelta(days=2)).isoformat(),
                                        "prices": {"X ML": {"market": "nfl_ml", "prob": 50}}}]}
        self.assertEqual(PC.nfl_rows(st, "2026-09-23", NOW), [])


class TestImport(unittest.TestCase):

    def test_placeholder_odds_are_ignored(self):
        r = IMP.convert({"result": "W", "sport": "mlb", "market_type": "strikeouts", "name": "X",
                         "line": 5.5, "our_prob": 60, "b365_odds": 1.909, "date": "2026-06-10"})
        self.assertEqual(r["cote_reference"], "")
        self.assertEqual(r["version_modele"], PERF.HIST)
        self.assertNotIn("prob_brute", r, "l'historique n'entre pas dans la calibration par barreau")

    def test_pending_bets_are_skipped(self):
        self.assertIsNone(IMP.convert({"result": "?", "sport": "mlb", "market_type": "moneyline"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
