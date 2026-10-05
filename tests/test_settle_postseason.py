"""Reglement des props K en series (2026-10-05): l'API MLB ne renvoie les
departs de series que si gameType les demande — sinon tout etait VOID."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import close_and_settle as CS  # noqa: E402


class PostseasonK(unittest.TestCase):
    def setUp(self):
        self.orig_get, self.calls = CS._get_json, []
        CS._k_cache.clear()

        def fake(url, params=None, *a, **k):
            self.calls.append(params or {})
            if "postseason" not in str(params.get("gameType", "")) and "F" not in str(params.get("gameType", "")):
                return {"stats": [{"splits": []}]}          # comportement reel sans gameType
            return {"stats": [{"splits": [{"date": "2026-10-01", "stat": {"strikeOuts": 7, "gamesStarted": 1}}]}]}
        CS._get_json = fake
        import mlb_rolling_stats
        self.orig_pid, mlb_rolling_stats._search_player_id = mlb_rolling_stats._search_player_id, lambda n: 1

    def tearDown(self):
        CS._get_json = self.orig_get
        import mlb_rolling_stats
        mlb_rolling_stats._search_player_id = self.orig_pid
        CS._k_cache.clear()

    def test_wild_card_start_is_found(self):
        self.assertEqual(CS.pitcher_ks("Aaron Nola", "2026-10-01"), (7, True))
        for t in ("R", "F", "D", "L", "W"):
            self.assertIn(t, self.calls[0]["gameType"].split(","))


if __name__ == "__main__":
    unittest.main()
