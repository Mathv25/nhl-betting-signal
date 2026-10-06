"""Validation avant publication: rien d'un autre jour, rien de manquant sans le dire."""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import publish_check as PC  # noqa: E402

NOW = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)          # 16h ET
NHL = [{"away": "UTA", "home": "NJD", "start": "2026-10-06T23:00:00Z", "upcoming": True},
       {"away": "OTT", "home": "DET", "start": "2026-10-06T23:00:00Z", "upcoming": True}]
MLB = [{"away": "New York Yankees", "home": "Tampa Bay Rays", "start": "2026-10-07T00:00:00Z", "upcoming": True}]


def out(**kw):
    o = {"date": "2026-10-06",
         "signals": [{"game": {"away_team": "Utah Mammoth", "home_team": "New Jersey Devils",
                               "commence_time": "2026-10-06T23:00:00Z"}},
                     {"game": {"away_team": "Ottawa Senators", "home_team": "Detroit Red Wings",
                               "commence_time": "2026-10-06T23:00:00Z"}}],
         "nhl_sog": {"date": "2026-10-06", "joueurs": [
             {"joueur": "Jack Hughes", "match": "UTA @ NJD", "commence": "2026-10-06T23:00:00Z"},
             {"joueur": "Alex DeBrincat", "match": "OTT @ DET", "commence": "2026-10-06T23:00:00Z"}]},
         "mlb_ml_analysis": [{"away_team": "New York Yankees", "home_team": "Tampa Bay Rays",
                              "commence": "2026-10-07T00:00:00Z", "bets": []}],
         "mlb_analysis": []}
    o.update(kw)
    return o


class Validation(unittest.TestCase):
    def test_everything_present_is_ok(self):
        v = PC.validate(out(), NOW, NHL, MLB)
        self.assertTrue(v["ok"], v)

    def test_yesterdays_sog_is_removed_and_flagged(self):
        o = out(nhl_sog={"date": "2026-10-05", "joueurs": [
            {"joueur": "X", "match": "EDM @ VAN", "commence": "2026-10-05T23:00:00Z"}]})
        v = PC.validate(o, NOW, NHL, MLB)
        self.assertFalse(v["ok"])
        self.assertEqual(o["nhl_sog"]["joueurs"], [])

    def test_missing_nhl_game_is_an_error(self):
        o = out()
        o["signals"] = o["signals"][:1]
        v = PC.validate(o, NOW, NHL, MLB)
        sec = next(s for s in v["sections"] if s["nom"] == "LNH")
        self.assertIn("OTT @ DET", " ".join(sec["erreurs"]))

    def test_wrong_day_signal(self):
        self.assertFalse(PC.validate(out(date="2026-10-05"), NOW, NHL, MLB)["ok"])

    def test_missing_mlb_game_is_an_error(self):
        self.assertFalse(PC.validate(out(mlb_ml_analysis=[]), NOW, NHL, MLB)["ok"])

    def test_unreachable_schedule_only_warns(self):
        v = PC.validate(out(), NOW, None, None)
        self.assertTrue(v["ok"])
        self.assertTrue(any(s["avertissements"] for s in v["sections"]))


if __name__ == "__main__":
    unittest.main()
