"""
Tests du module NFL (src/nfl_analyzer.py).

Aucun appel reseau: les reponses de l'API sont ecrites en dur.

Ce qui est verifie en priorite, parce que c'est ce qui decide de miser:
  - la reference est Pinnacle devigge par Shin, sinon la mediane sharp;
  - seul le prix bet365 (ALLOWED_BOOKS) peut produire un signal « a miser »;
  - au-dela de 8% d'edge: « A VERIFIER », jamais « a miser »;
  - le seuil filtre reellement, dans les deux sens;
  - la cadence ne depense rien hors des trois fenetres de la semaine.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import nfl_analyzer as NFL   # noqa: E402
import odds_api              # noqa: E402


def event(h2h=None, spreads=None, totals=None,
          home="Seattle Seahawks", away="New England Patriots"):
    """Construit un evenement au format The Odds API."""
    books = {}
    for key, per_book in (("h2h", h2h or {}), ("spreads", spreads or {}),
                          ("totals", totals or {})):
        for book, outcomes in per_book.items():
            books.setdefault(book, {})[key] = outcomes
    return {
        "id": "evt-1", "home_team": home, "away_team": away,
        "commence_time": "2026-09-10T00:20:00Z",
        "bookmakers": [
            {"key": bk, "markets": [
                {"key": mk, "outcomes": oc} for mk, oc in mkts.items()]}
            for bk, mkts in books.items()
        ],
    }


def ml(price_home, price_away, home="Seattle Seahawks", away="New England Patriots"):
    return [{"name": home, "price": price_home}, {"name": away, "price": price_away}]


class TestReference(unittest.TestCase):
    """
    La probabilite juste vient de Pinnacle (Shin), sinon de la mediane des
    books sharp. Les autres books ne comptent pas, les exchanges non plus.
    """

    def test_pair_sums_to_one(self):
        per_book = {"pinnacle": {"A": 1.90, "B": 1.98},
                    "draftkings": {"A": 1.85, "B": 1.95}}
        pair = NFL.reference_pair(per_book, "A", "B")
        self.assertAlmostEqual(pair["A"] + pair["B"], 1.0, places=9)

    def test_shin_is_the_default_method(self):
        per_book = {"pinnacle": {"A": 7.0, "B": 1.10}}
        pair = NFL.reference_pair(per_book, "A", "B")
        self.assertIn("shin", pair["source"])
        self.assertAlmostEqual(pair["A"], odds_api.devig([7.0, 1.10], "shin")[0], places=6)

    def test_shin_gives_the_longshot_less_than_multiplicative(self):
        # Le multiplicatif surestime les outsiders: c'est la raison du changement.
        mult = odds_api.devig([7.0, 1.10], "multiplicative")[0]
        shin = odds_api.devig([7.0, 1.10], "shin")[0]
        power = odds_api.devig([7.0, 1.10], "power")[0]
        self.assertLess(shin, mult)
        self.assertLess(power, mult)
        for m in ("shin", "power", "multiplicative"):
            self.assertAlmostEqual(sum(odds_api.devig([7.0, 1.10], m)), 1.0, places=9)

    def test_power_is_available(self):
        pair = NFL.reference_pair({"pinnacle": {"A": 7.0, "B": 1.10}}, "A", "B", method="power")
        self.assertIn("power", pair["source"])

    def test_pinnacle_is_the_reference_even_when_it_prices_worse(self):
        per_book = {"pinnacle": {"A": 1.90, "B": 1.98},
                    "fanduel": {"A": 2.10, "B": 1.75}}
        pair = NFL.reference_pair(per_book, "A", "B")
        self.assertTrue(pair["source"].startswith("pinnacle"))
        # fanduel n'est pas un book jouable: aucun prix « chez moi »
        self.assertEqual(pair["mine"], {})

    def test_sharp_median_when_pinnacle_is_absent(self):
        per_book = {"lowvig": {"A": 1.90, "B": 1.98}, "betonlineag": {"A": 1.88, "B": 2.00},
                    "draftkings": {"A": 3.00, "B": 1.40}}
        pair = NFL.reference_pair(per_book, "A", "B")
        self.assertTrue(pair["source"].startswith("mediane sharp"))
        self.assertEqual(sorted(pair["ref_books"]), ["betonlineag", "lowvig"])
        # draftkings n'entre pas dans la reference
        lo = odds_api.devig([1.90, 1.98], "shin")[0]
        hi = odds_api.devig([1.88, 2.00], "shin")[0]
        self.assertAlmostEqual(pair["A"], (lo + hi) / 2, places=6)

    def test_no_sharp_book_means_no_reference(self):
        per_book = {"draftkings": {"A": 1.90, "B": 1.98}, "fanduel": {"A": 1.88, "B": 2.0}}
        self.assertEqual(NFL.reference_pair(per_book, "A", "B"), {})

    def test_one_sided_market_produces_nothing(self):
        self.assertEqual(NFL.reference_pair({"pinnacle": {"A": 1.90}}, "A", "B"), {})

    def test_every_market_of_a_game_sums_to_one(self):
        ev = event(
            h2h={"pinnacle": ml(1.90, 1.98)},
            spreads={"pinnacle": [
                {"name": "Seattle Seahawks", "price": 1.91, "point": -3.5},
                {"name": "New England Patriots", "price": 1.95, "point": 3.5}]},
            totals={"pinnacle": [
                {"name": "Over", "price": 1.92, "point": 44.5},
                {"name": "Under", "price": 1.94, "point": 44.5}]},
        )
        out = NFL.analyze_event(ev)
        self.assertEqual(len(out["markets"]), 3)
        for m in out["markets"]:
            self.assertAlmostEqual(m["prob_a"] + m["prob_b"], 100.0, places=2,
                                   msg=f"{m['market']} ne somme pas a 100%")


class TestThreshold(unittest.TestCase):
    """Seul bet365 peut produire un signal; le seuil filtre dans les deux sens."""

    def _game(self, b365_price, other_price=3.00):
        # Pinnacle fixe la reference a 50%; un autre book offre un prix enorme
        # qui ne doit JAMAIS compter; bet365 offre `b365_price`.
        return event(h2h={"pinnacle": ml(1.95, 1.95),
                          "fanduel": ml(other_price, 1.40),
                          "bet365": ml(b365_price, 1.80)})

    def test_a_price_matching_the_fair_line_is_not_a_signal(self):
        out = NFL.analyze_event(self._game(2.00), threshold=3.0)
        self.assertEqual(out["signals"], [])

    def test_a_bet365_price_beating_the_fair_line_is_a_signal(self):
        # 50% x 2.10 - 1 = +5%: au-dessus de 3%, sous 8% -> a miser.
        out = NFL.analyze_event(self._game(2.10), threshold=3.0)
        sigs = [s for s in out["signals"] if s["market"] == "nfl_ml"]
        self.assertEqual(len(sigs), 1)
        self.assertAlmostEqual(sigs[0]["edge_pct"], 5.0, places=1)
        self.assertEqual(sigs[0]["book"], "bet365")
        self.assertEqual(sigs[0]["statut"], "a_miser")
        self.assertAlmostEqual(sigs[0]["fair_odds"], 2.00, places=2)

    def test_a_better_price_elsewhere_is_never_a_signal(self):
        out = NFL.analyze_event(event(h2h={"pinnacle": ml(1.95, 1.95),
                                           "fanduel": ml(2.50, 1.60)}), threshold=3.0)
        self.assertEqual(out["signals"], [])
        px = out["prices"]["Seattle Seahawks ML"]
        self.assertEqual(px["statut"], "a_saisir")
        self.assertEqual(px["my_odds"], 0)
        self.assertAlmostEqual(px["target_odds"], 2.06, places=2)

    def test_above_eight_percent_is_to_verify_never_to_bet(self):
        # 50% x 2.20 - 1 = +10%
        out = NFL.analyze_event(self._game(2.20), threshold=3.0)
        sig = [s for s in out["signals"] if s["market"] == "nfl_ml"][0]
        self.assertEqual(sig["statut"], "a_verifier")
        self.assertEqual(sig["stake_units"], 0)

    def test_just_below_the_threshold_is_rejected(self):
        # 50% x 2.05 - 1 = +2.5%, sous un seuil a 3%.
        self.assertEqual(NFL.analyze_event(self._game(2.05), threshold=3.0)["signals"], [])
        self.assertEqual(len(NFL.analyze_event(self._game(2.05), threshold=2.0)["signals"]), 1)

    def test_threshold_comes_from_the_environment(self):
        os.environ["NFL_MIN_EDGE"] = "7"
        try:
            self.assertEqual(NFL.min_edge(), 7.0)
            self.assertEqual(NFL.analyze_event(self._game(2.10))["signals"], [])
        finally:
            os.environ.pop("NFL_MIN_EDGE", None)
        self.assertEqual(NFL.min_edge(), 3.0)

    def test_exchanges_are_ignored_everywhere(self):
        ev = event(h2h={"smarkets": ml(1.95, 1.95), "matchbook": ml(2.40, 1.60),
                        "betfair_ex_uk": ml(2.60, 1.55)})
        out = NFL.analyze_event(ev)
        self.assertEqual(out["markets"], [], "un exchange n'est pas une reference")

    def test_no_minimum_number_of_books(self):
        # Pinnacle + bet365 suffisent: plus de minimum de 4 books.
        out = NFL.analyze_event(event(h2h={"pinnacle": ml(1.95, 1.95),
                                           "bet365": ml(2.10, 1.80)}), threshold=3.0)
        self.assertEqual(len(out["signals"]), 1)


class TestNoSignalIsAResult(unittest.TestCase):

    def test_an_aligned_market_yields_nothing(self):
        ev = event(h2h={"pinnacle": ml(1.95, 1.95), "bet365": ml(1.94, 1.94),
                        "fanduel": ml(1.93, 1.96)})
        out = NFL.analyze_event(ev)
        self.assertEqual(out["signals"], [])
        self.assertTrue(out["markets"], "le match doit rester analyse")


class TestPaperLogging(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nfl-test")
        os.environ["BETS_PATH"] = os.path.join(self.dir, "bets.json")
        os.environ["NFL_SIGNALS_PATH"] = os.path.join(self.dir, "nfl.json")

    def tearDown(self):
        os.environ.pop("BETS_PATH", None)
        os.environ.pop("NFL_SIGNALS_PATH", None)

    def _games(self, odds=2.10, pin=1.95):
        ev = event(h2h={"pinnacle": ml(pin, pin), "bet365": ml(odds, 1.80)})
        return [NFL.analyze_event(ev, threshold=3.0)]

    def test_signals_are_logged_as_paper(self):
        import bet_tracker as bt
        n = NFL.log_paper_bets(self._games(), "2026-09-08")
        self.assertEqual(n, 1)
        bet = bt.load()["bets"][0]
        self.assertTrue(bet["paper"])
        self.assertEqual(bet["stake"], 1.0)
        self.assertEqual(bet["market"], "nfl_ml")
        self.assertEqual(bet["book"], "bet365")

    def test_to_verify_is_never_logged(self):
        self.assertEqual(NFL.log_paper_bets(self._games(2.30), "2026-09-08"), 0)

    def test_the_same_signal_is_not_logged_twice(self):
        NFL.log_paper_bets(self._games(2.10), "2026-09-08")
        self.assertEqual(NFL.log_paper_bets(self._games(2.12), "2026-09-08"), 0)
        import bet_tracker as bt
        bets = bt.load()["bets"]
        self.assertEqual(len(bets), 1)
        self.assertEqual(bets[0]["odds_taken"], 2.10)

    def test_paper_bets_stay_out_of_the_real_yield(self):
        import bet_tracker as bt
        NFL.log_paper_bets(self._games(), "2026-09-08")
        bt.close_bet(bt.load()["bets"][0]["id"], result="win")
        st = bt.load()["stats"]
        self.assertEqual(st["n_counted"], 0)
        self.assertEqual(st["paper"]["n_counted"], 1)

    def test_closing_is_the_fair_reference_price(self):
        # Dimanche: Pinnacle a bouge a 1.85/2.05, le pari n'est plus un signal.
        # La fermeture retenue est le prix JUSTE (Shin) de la reference.
        import bet_tracker as bt
        NFL.log_paper_bets(self._games(2.10), "2026-09-08")
        ferme = [NFL.analyze_event(event(h2h={"pinnacle": ml(1.85, 2.05)}), threshold=3.0)]
        NFL.capture_closing(ferme, "2026-09-08")
        bet = bt.load()["bets"][0]
        fair = 1.0 / odds_api.devig([1.85, 2.05], "shin")[0]
        self.assertAlmostEqual(bet["closing_odds"], round(fair, 3), places=3)
        # 2.10 pris contre ~1.95 juste a la fermeture: CLV positif.
        self.assertGreater(bt.load()["stats"]["clv"]["avg_clv_pct"], 0)


class TestCadence(unittest.TestCase):
    """Hors des trois fenetres, la NFL ne doit couter aucun credit."""

    def test_the_three_windows_are_open(self):
        self.assertTrue(NFL.should_fetch(datetime(2026, 9, 8, 10))[0])    # mardi
        self.assertTrue(NFL.should_fetch(datetime(2026, 9, 11, 10))[0])   # vendredi
        self.assertTrue(NFL.should_fetch(datetime(2026, 9, 13, 9))[0])    # dimanche 9h
        self.assertTrue(NFL.should_fetch(datetime(2026, 9, 13, 11, 59))[0])

    def test_everything_else_is_closed(self):
        for d in (datetime(2026, 9, 7, 12),    # lundi
                  datetime(2026, 9, 9, 12),    # mercredi
                  datetime(2026, 9, 10, 12),   # jeudi
                  datetime(2026, 9, 12, 12),   # samedi
                  datetime(2026, 9, 13, 8),    # dimanche trop tot
                  datetime(2026, 9, 13, 12)):  # dimanche trop tard
            self.assertFalse(NFL.should_fetch(d)[0], f"{d} ne devrait pas ouvrir")

    def test_one_fetch_per_window(self):
        # signal.py tourne toutes les heures: sans identifiant de fenetre, un
        # mardi couterait 24 releves au lieu d'une.
        a = NFL.window_id(datetime(2026, 9, 8, 9))
        b = NFL.window_id(datetime(2026, 9, 8, 17))
        self.assertEqual(a, b)
        self.assertNotEqual(a, NFL.window_id(datetime(2026, 9, 11, 9)))
        self.assertIsNone(NFL.window_id(datetime(2026, 9, 9, 12)))

    def test_only_sunday_morning_captures_the_close(self):
        self.assertTrue(NFL.is_closing_window(datetime(2026, 9, 13, 10)))
        self.assertFalse(NFL.is_closing_window(datetime(2026, 9, 8, 10)))

    def test_the_week_is_labelled_by_its_tuesday(self):
        for d in (datetime(2026, 9, 8, 10), datetime(2026, 9, 11, 10),
                  datetime(2026, 9, 13, 10)):
            self.assertEqual(NFL.week_label(d), "2026-09-08")


class TestWeekHorizon(unittest.TestCase):
    """
    L'API renvoie tous les matchs a venir. Le premier run reel en a ramene 270,
    de septembre a janvier, et a enregistre des paris papier sur des matchs de
    decembre. On ne garde que la semaine en cours.
    """

    MERCREDI = datetime(2026, 9, 9, 16)     # avant l'ouvreur du soir

    def test_this_weeks_games_are_kept(self):
        for iso in ("2026-09-10T00:20:00Z",   # ce soir 20h20 ET
                    "2026-09-11T00:35:00Z",   # jeudi soir
                    "2026-09-13T17:00:00Z",   # dimanche 13h ET
                    "2026-09-15T00:15:00Z"):  # lundi soir
            self.assertTrue(NFL.in_current_week(iso, self.MERCREDI), iso)

    def test_later_games_are_dropped(self):
        for iso in ("2026-09-20T17:00:00Z",   # semaine suivante
                    "2026-12-25T18:00:00Z",   # decembre
                    "2027-01-10T18:00:00Z"):
            self.assertFalse(NFL.in_current_week(iso, self.MERCREDI), iso)

    def test_the_window_closes_on_tuesday_morning(self):
        end = NFL.week_end(self.MERCREDI)
        self.assertEqual(end.weekday(), 1)
        self.assertEqual(end.hour, 6)

    def test_garbage_dates_are_dropped(self):
        self.assertFalse(NFL.in_current_week("", self.MERCREDI))
        self.assertFalse(NFL.in_current_week("pas une date", self.MERCREDI))


if __name__ == "__main__":
    unittest.main(verbosity=2)
