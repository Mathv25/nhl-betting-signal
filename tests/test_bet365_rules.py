"""
Regle « bet365 seulement » (2026-09-23): config, saisie manuelle, fusion du
journal, lignes du modele LNH. Aucun appel reseau.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import betting_config           # noqa: E402
import odds_api                 # noqa: E402
import predictions_log as PL     # noqa: E402
import record_prediction as RP   # noqa: E402


class TestConfig(unittest.TestCase):

    def test_bet365_is_the_only_allowed_book(self):
        self.assertEqual(betting_config.allowed_books(), ["bet365"])
        self.assertEqual(odds_api.my_books(), ["bet365"])

    def test_exchanges_are_recognised(self):
        for b in ("smarkets", "matchbook", "betfair_ex_uk", "betfair_ex_eu", "betfair_ex_au"):
            self.assertTrue(betting_config.is_exchange(b))
        self.assertFalse(betting_config.is_exchange("pinnacle"))

    def test_my_books_env_is_gone(self):
        os.environ["MY_BOOKS"] = "fanduel"
        try:
            self.assertEqual(odds_api.my_books(), ["bet365"])
        finally:
            os.environ.pop("MY_BOOKS", None)


class TestRecord(unittest.TestCase):

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        os.remove(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def _p(self, **kw):
        base = {"sport": "nfl", "marche": "nfl_ml", "selection": "Seahawks ML",
                "date": "2026-09-27", "prob_modele": 0.50, "cote_prise": 2.10, "mise_u": 1}
        base.update(kw)
        return base

    def test_edge_and_status(self):
        row = RP.record(self._p(), self.path)
        self.assertAlmostEqual(float(row["edge"]), 5.0, places=2)
        self.assertEqual(row["statut"], "a_miser")
        self.assertEqual(row["book"], "bet365")

    def test_above_eight_is_to_verify(self):
        self.assertEqual(RP.record(self._p(cote_prise=2.30), self.path)["statut"], "a_verifier")

    def test_uncalibrated_k_rung_is_informative(self):
        row = RP.record(self._p(sport="mlb", marche="props_k", selection="X Over 5.5 K",
                                cote_prise=2.10, calibre=False), self.path)
        self.assertEqual(row["statut"], "informatif")

    def test_other_books_are_refused(self):
        with self.assertRaises(ValueError):
            RP.record(self._p(book="fanduel"), self.path)

    def test_existing_ladder_row_is_completed(self):
        PL.upsert([{"id": "2026-09-27|nfl|nfl_ml|Seahawks ML", "sport": "nfl",
                    "marche": "nfl_ml", "selection": "Seahawks ML", "prob_modele": 0.5}],
                  self.path)
        RP.record(self._p(), self.path)
        rows = PL.load(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0]["cote_prise"]), 2.10)


class TestMerge(unittest.TestCase):
    """Un run du signal ne doit jamais effacer une cote saisie pendant qu'il tournait."""

    def test_recorded_odds_survive_a_signal_run(self):
        d = tempfile.mkdtemp()
        base, ours = os.path.join(d, "base.csv"), os.path.join(d, "ours.csv")
        start = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        row = {"id": "a", "sport": "mlb", "marche": "props_k", "selection": "a",
               "prob_modele": 0.5, "commence_time": start}
        PL.save([dict(row, cote_prise=2.0, book="bet365", mise_u=1)], base)   # saisie sur main
        PL.save([dict(row, prob_modele=0.55), dict(row, id="b", selection="b")], ours)  # run du bot
        st = PL.merge_file(ours, base, "prediction")
        rows = {r["id"]: r for r in PL.load(base)}
        self.assertEqual(st["added"], 1)
        self.assertEqual(rows["a"]["cote_prise"], "2")
        self.assertEqual(float(rows["a"]["prob_modele"]), 0.55)
        self.assertIn("b", rows)


class TestNHLModelLines(unittest.TestCase):

    def test_lines_have_fair_and_minimum_odds(self):
        import edge_calculator as EC
        calc = EC.EdgeCalculator.__new__(EC.EdgeCalculator)
        lines = calc.model_lines(3.2, 2.8, "Home", "Away")
        ml = [l for l in lines if l["marche"] == "nhl_ml"]
        self.assertEqual(len(ml), 2)
        self.assertAlmostEqual(ml[0]["prob"] + ml[1]["prob"], 1.0, places=3)
        for l in lines:
            self.assertAlmostEqual(l["fair_odds"], 1 / l["prob"], places=2)
            self.assertGreaterEqual(l["min_odds"], (1 + EC.MIN_EDGE_PCT / 100) / l["prob"] - 0.01)


if __name__ == "__main__":
    unittest.main(verbosity=2)
