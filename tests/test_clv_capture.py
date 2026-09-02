"""
Tests de la capture CLV (src/clv_capture.py).

Ces tests existent parce que la capture a tourne des mois en produisant 0 CLV
sur 1267 bets: les entrees de signal.json n'avaient pas d'event_id, donc chaque
bet etait silencieusement ignore. On verifie ici le chemin complet sur des
reponses d'API en dur, sans reseau.

Lancer:  python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import odds_api                  # noqa: E402
import clv_capture as CLV        # noqa: E402


class FakeClient:
    """Client Odds API en dur: repond par endpoint, compte les appels."""

    def __init__(self, payloads):
        self.payloads  = payloads
        self.calls     = []
        self.remaining = 400
        self.used      = 100
        self.healthy   = True

    def get(self, endpoint, params, cost=1):
        self.calls.append((endpoint, params.get("markets"), cost))
        return self.payloads.get(endpoint)

    # rythme de depense: le vrai client refuse au-dela du budget d'execution
    def can_spend_props(self, cost):
        return True

    def note_props(self, cost):
        self.prop_credits = getattr(self, "prop_credits", 0) + cost

    def day_budget(self):
        return None

    def spent_today(self):
        return 0

    def persist_usage(self):
        pass

    # utilises par le plafond d'evenements
    def _key(self, endpoint, params):
        return endpoint + str(sorted((params or {}).items()))

    def _cache_read(self, key):
        return None

    def log_status(self, label=""):
        pass


def _prop_payload():
    """Un marche pitcher_strikeouts sur deux books, lignes 5.5 et 6.5."""
    def outcomes(line, over, under):
        return [
            {"name": "Over",  "description": "Walbert Urena", "point": line, "price": over},
            {"name": "Under", "description": "Walbert Urena", "point": line, "price": under},
        ]
    return {
        "bookmakers": [
            {"key": "draftkings", "markets": [
                {"key": "pitcher_strikeouts",
                 "outcomes": outcomes(5.5, 2.00, 1.80) + outcomes(6.5, 2.90, 1.42)}]},
            {"key": "pinnacle", "markets": [
                {"key": "pitcher_strikeouts",
                 "outcomes": outcomes(5.5, 1.95, 1.95)}]},
        ]
    }


def _h2h_payload():
    return [{
        "id": "evt-ml", "home_team": "Boston Red Sox", "away_team": "Seattle Mariners",
        "bookmakers": [
            {"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Boston Red Sox", "price": 1.70},
                {"name": "Seattle Mariners", "price": 2.30}]}]},
            {"key": "draftkings", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Boston Red Sox", "price": 1.66},
                {"name": "Seattle Mariners", "price": 2.35}]}]},
        ],
    }]


class TestClosingIndexes(unittest.TestCase):

    def test_prop_index_is_novig_and_keeps_best_price(self):
        c = FakeClient({"sports/baseball_mlb/events/evt-1/odds": _prop_payload()})
        idx = CLV.prop_closing_index(c, "baseball_mlb", "evt-1", "pitcher_strikeouts")
        lines = idx["walbert urena"]
        self.assertEqual(set(lines), {5.5, 6.5})

        # 5.5: Pinnacle cote les deux faces a 1.95 -> baseline no-vig 50%,
        # mais on parie chez DK a 2.00 (meilleure cote).
        self.assertEqual(lines[5.5]["cote"], 2.00)
        self.assertEqual(lines[5.5]["book"], "draftkings")
        self.assertEqual(lines[5.5]["source"], "pinnacle")
        self.assertAlmostEqual(lines[5.5]["novig"], 50.0, places=1)
        self.assertAlmostEqual(lines[5.5]["brute"], 50.0, places=1)

        # 6.5: seul DK, no-vig de DK = 1/2.90 / (1/2.90 + 1/1.42) = 32.9%,
        # la brute (34.5%) est plus haute — c'est exactement la vig.
        self.assertAlmostEqual(lines[6.5]["novig"], 32.87, places=1)
        self.assertGreater(lines[6.5]["brute"], lines[6.5]["novig"])

    def test_prop_index_costs_one_call_for_all_lines(self):
        c = FakeClient({"sports/baseball_mlb/events/evt-1/odds": _prop_payload()})
        CLV.prop_closing_index(c, "baseball_mlb", "evt-1", "pitcher_strikeouts")
        self.assertEqual(len(c.calls), 1)
        self.assertEqual(c.calls[0][2], 10 * CLV._n_regions())   # 10 credits/marche/region

    def test_h2h_index_is_slate_wide_and_cheap(self):
        c = FakeClient({"sports/baseball_mlb/odds": _h2h_payload()})
        idx = CLV.h2h_closing_index(c, "baseball_mlb")
        entry = idx[("seattle mariners", "boston red sox")]
        self.assertEqual(len(c.calls), 1)
        self.assertEqual(c.calls[0][2], 1 * CLV._n_regions())    # 1 credit, pas 10
        # Pinnacle 1.70 / 2.30 -> no-vig Boston = (1/1.70)/(1/1.70+1/2.30)
        self.assertAlmostEqual(entry["Boston Red Sox"]["novig"], 57.5, places=1)
        self.assertEqual(entry["Boston Red Sox"]["source"], "pinnacle")
        # Meilleure cote = DK 2.35 cote Seattle
        self.assertEqual(entry["Seattle Mariners"]["cote"], 2.35)


class TestCaptureCLV(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="clv-test")
        self.results_path = os.path.join(self.dir, "results.json")
        self.signal_path  = os.path.join(self.dir, "signal.json")
        self._orig = (CLV.RESULTS_PATH, CLV.SIGNAL_PATH, odds_api.get_client)
        CLV.RESULTS_PATH, CLV.SIGNAL_PATH = self.results_path, self.signal_path

        self.client = FakeClient({
            "sports/baseball_mlb/events/evt-1/odds": _prop_payload(),
            "sports/baseball_mlb/odds":              _h2h_payload(),
        })
        odds_api.get_client = lambda key=None: self.client

        json.dump({
            "mlb_analysis": [{"event_id": "evt-1",
                              "home_team": "Los Angeles Angels",
                              "away_team": "New York Yankees", "bets": []}],
            "mlb_ml_analysis": [{"event_id": "evt-ml",
                                 "home_team": "Boston Red Sox",
                                 "away_team": "Seattle Mariners", "bets": []}],
        }, open(self.signal_path, "w"))

    def tearDown(self):
        CLV.RESULTS_PATH, CLV.SIGNAL_PATH, odds_api.get_client = self._orig

    def _write_bets(self, bets):
        json.dump({"bets": bets}, open(self.results_path, "w"))

    def _reload(self):
        return json.load(open(self.results_path))["bets"]

    def test_novig_opening_is_compared_to_novig_closing(self):
        # Ouverture no-vig 55% vs fermeture no-vig 50% -> CLV +5, pas +4.4
        # (ce que donnerait la fermeture brute).
        self._write_bets([{
            "date": "2026-09-01", "result": "?", "sport": "mlb", "bet_type": "prop",
            "market_type": "strikeouts", "game": "New York Yankees @ Los Angeles Angels",
            "name": "Walbert Urena", "line": 5.5,
            "b365_implied": 55.0, "opening_basis": "novig",
        }])
        CLV.capture_clv("cle", "2026-09-01")
        b = self._reload()[0]
        self.assertEqual(b["clv_basis"], "novig")
        self.assertAlmostEqual(b["clv"], 5.0, places=1)
        self.assertEqual(b["closing_book"], "draftkings")
        self.assertEqual(b["closing_odds"], 2.00)

    def test_raw_opening_is_compared_to_raw_closing(self):
        self._write_bets([{
            "date": "2026-09-01", "result": "?", "sport": "mlb", "bet_type": "team",
            "market_type": "moneyline", "game": "Seattle Mariners @ Boston Red Sox",
            "name": "Boston Red Sox", "line": 0,
            "b365_implied": 61.0, "opening_basis": "brute",
        }])
        CLV.capture_clv("cle", "2026-09-01")
        b = self._reload()[0]
        self.assertEqual(b["clv_basis"], "brute")
        # brute = 1/1.70 = 58.8% (meilleure cote Boston) -> CLV = 61.0 - 58.8
        self.assertAlmostEqual(b["clv"], 2.2, places=1)

    def test_moneyline_slate_is_fetched_once_for_many_bets(self):
        self._write_bets([
            {"date": "2026-09-01", "result": "?", "sport": "mlb", "bet_type": "team",
             "market_type": "moneyline", "game": "Seattle Mariners @ Boston Red Sox",
             "name": "Boston Red Sox", "b365_implied": 61.0, "opening_basis": "brute"},
            {"date": "2026-09-01", "result": "?", "sport": "mlb", "bet_type": "team",
             "market_type": "moneyline", "game": "Seattle Mariners @ Boston Red Sox",
             "name": "Seattle Mariners", "b365_implied": 42.0, "opening_basis": "brute"},
        ])
        CLV.capture_clv("cle", "2026-09-01")
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(sum(1 for b in self._reload() if b.get("clv") is not None), 2)

    def test_moved_line_is_not_captured(self):
        # Le marche a bouge de 5.5 a 7.5: comparer deux lignes differentes
        # produirait un CLV enorme et faux. On prefere ne rien ecrire.
        self._write_bets([{
            "date": "2026-09-01", "result": "?", "sport": "mlb", "bet_type": "prop",
            "market_type": "strikeouts", "game": "New York Yankees @ Los Angeles Angels",
            "name": "Walbert Urena", "line": 7.5,
            "b365_implied": 55.0, "opening_basis": "novig",
        }])
        CLV.capture_clv("cle", "2026-09-01")
        self.assertIsNone(self._reload()[0].get("clv"))

    def test_missing_event_id_is_reported_not_silent(self):
        json.dump({"mlb_analysis": [{"home_team": "Los Angeles Angels",
                                     "away_team": "New York Yankees", "bets": []}]},
                  open(self.signal_path, "w"))
        self._write_bets([{
            "date": "2026-09-01", "result": "?", "sport": "mlb", "bet_type": "prop",
            "market_type": "strikeouts", "game": "New York Yankees @ Los Angeles Angels",
            "name": "Walbert Urena", "line": 5.5,
            "b365_implied": 55.0, "opening_basis": "novig",
        }])
        CLV.capture_clv("cle", "2026-09-01")
        self.assertIsNone(self._reload()[0].get("clv"))
        self.assertEqual(len(self.client.calls), 0)   # aucun credit brule


if __name__ == "__main__":
    unittest.main(verbosity=2)
