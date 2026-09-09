"""
Tests du module NFL (src/nfl_analyzer.py).

Aucun appel reseau: les reponses de l'API sont ecrites en dur.

Ce qui est verifie en priorite, parce que c'est ce qui decide de miser:
  - le devig produit une paire de probabilites qui somme a 1 par match;
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


class TestDevigSumsToOne(unittest.TestCase):
    """
    Une paire de probabilites de marche doit sommer a 1. Si elle somme a plus,
    la vig est restee dedans et chaque edge calcule contre elle est surestime
    du meme montant.
    """

    def test_pair_sums_to_one(self):
        per_book = {"pinnacle": {"A": 1.90, "B": 1.98},
                    "draftkings": {"A": 1.85, "B": 1.95}}
        pair = NFL.devig_pair(per_book, "A", "B")
        self.assertAlmostEqual(pair["A"] + pair["B"], 1.0, places=9)

    def test_it_removes_the_vig_rather_than_keeping_it(self):
        # 1.90 / 1.98 implique 52.6% + 50.5% = 103.1%: 3.1 points de marge.
        per_book = {"pinnacle": {"A": 1.90, "B": 1.98}}
        pair = NFL.devig_pair(per_book, "A", "B")
        self.assertLess(pair["A"], 1 / 1.90)
        # La reference est publiee au centieme de point de pourcentage.
        self.assertAlmostEqual(pair["A"], (1 / 1.90) / (1 / 1.90 + 1 / 1.98), places=4)

    def test_pinnacle_is_the_reference_even_when_it_prices_worse(self):
        per_book = {"pinnacle": {"A": 1.90, "B": 1.98},
                    "fanduel": {"A": 2.10, "B": 1.75}}
        pair = NFL.devig_pair(per_book, "A", "B")
        self.assertEqual(pair["source"], "pinnacle")
        # Mais on parie au meilleur prix, qui vient d'ailleurs.
        self.assertEqual(pair["best"]["A"], (2.10, "fanduel"))

    def test_median_when_pinnacle_is_absent(self):
        per_book = {"a": {"A": 1.90, "B": 1.98}, "b": {"A": 1.88, "B": 2.00},
                    "c": {"A": 1.92, "B": 1.96}}
        pair = NFL.devig_pair(per_book, "A", "B")
        self.assertTrue(pair["source"].startswith("mediane"))
        self.assertAlmostEqual(pair["A"] + pair["B"], 1.0, places=9)

    def test_one_sided_market_produces_nothing(self):
        # Sans les deux faces on ne peut pas retirer la marge: mieux vaut ne
        # rien publier qu'une probabilite qui contient la vig.
        self.assertEqual(NFL.devig_pair({"a": {"A": 1.90}}, "A", "B"), {})

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
    """Le seuil doit filtrer dans les deux sens, sinon il ne sert a rien."""

    def _game(self, best_price):
        # Pinnacle fixe la reference a ~50%; un autre book offre `best_price`.
        # Quatre books au minimum, sinon le marche est juge trop mince et le
        # signal est refuse quel que soit l'ecart (voir TestThinMarkets).
        return event(h2h={"pinnacle": ml(1.95, 1.95),
                          "fanduel": ml(best_price, 1.80),
                          "draftkings": ml(1.94, 1.96),
                          "betmgm": ml(1.93, 1.97)})

    def test_a_price_matching_the_fair_line_is_not_a_signal(self):
        out = NFL.analyze_event(self._game(2.00), threshold=3.0)
        self.assertEqual(out["signals"], [])

    def test_a_price_beating_the_fair_line_is_a_signal(self):
        # 50% x 2.10 - 1 = +5%, au-dessus d'un seuil a 3%.
        out = NFL.analyze_event(self._game(2.10), threshold=3.0)
        sigs = [s for s in out["signals"] if s["market"] == "nfl_ml"]
        self.assertEqual(len(sigs), 1)
        self.assertAlmostEqual(sigs[0]["edge_pct"], 5.0, places=1)
        self.assertEqual(sigs[0]["book"], "fanduel")
        self.assertAlmostEqual(sigs[0]["fair_odds"], 2.00, places=2)

    def test_just_below_the_threshold_is_rejected(self):
        # 50% x 2.05 - 1 = +2.5%, sous un seuil a 3%.
        self.assertEqual(NFL.analyze_event(self._game(2.05), threshold=3.0)["signals"], [])
        # Le meme pari passe avec le seuil a 2%.
        self.assertEqual(len(NFL.analyze_event(self._game(2.05), threshold=2.0)["signals"]), 1)

    def test_threshold_comes_from_the_environment(self):
        os.environ["NFL_MIN_EDGE"] = "7"
        try:
            self.assertEqual(NFL.min_edge(), 7.0)
            self.assertEqual(NFL.analyze_event(self._game(2.10))["signals"], [])
        finally:
            os.environ.pop("NFL_MIN_EDGE", None)
        self.assertEqual(NFL.min_edge(), 3.0)

    def test_absurd_prices_do_not_become_signals(self):
        # Un carnet d'echange mince a 51.0 produirait un edge de +2450%.
        ev = event(h2h={"pinnacle": ml(1.95, 1.95), "dk": ml(1.98, 1.92),
                        "betmgm": ml(1.96, 1.94), "fd": ml(1.97, 1.93),
                        "echange": ml(51.0, 1.01)})
        for s in NFL.analyze_event(ev)["signals"]:
            self.assertLess(s["odds"], 5.0, "un prix injouable est devenu un signal")


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


class TestThinMarkets(unittest.TestCase):
    """
    Une mediane sur deux books n'est pas un consensus. Le premier run reel: 10
    signaux sur 18 reposaient sur 2 ou 3 books, et les matchs lointains
    affichaient 50.0%/50.0% — un seul book cotant les deux faces au meme prix.
    """

    def _ev(self, n_books):
        books = {"pinnacle": ml(1.95, 1.95)}
        for i in range(n_books - 1):
            books[f"book{i}"] = ml(2.15 if i == 0 else 1.94, 1.80)
        return event(h2h=books)

    def test_a_thin_market_produces_no_signal(self):
        # Deux books, un ecart enorme: refuse malgre l'edge apparent.
        out = NFL.analyze_event(self._ev(2), threshold=3.0)
        self.assertEqual(out["signals"], [])
        self.assertTrue(out["markets"], "le match reste analyse")

    def test_enough_books_lets_the_signal_through(self):
        out = NFL.analyze_event(self._ev(5), threshold=3.0)
        self.assertTrue(out["signals"])
        self.assertGreaterEqual(out["signals"][0]["n_books"], NFL.min_books())

    def test_threshold_is_configurable(self):
        os.environ["NFL_MIN_BOOKS"] = "2"
        try:
            self.assertEqual(NFL.min_books(), 2)
            self.assertTrue(NFL.analyze_event(self._ev(2), threshold=3.0)["signals"])
        finally:
            os.environ.pop("NFL_MIN_BOOKS", None)
        self.assertEqual(NFL.min_books(), 4)


class TestNoSignalIsAResult(unittest.TestCase):

    def test_an_aligned_market_yields_nothing(self):
        ev = event(h2h={"pinnacle": ml(1.95, 1.95), "dk": ml(1.94, 1.94),
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

    def _games(self, odds=2.10):
        ev = event(h2h={"pinnacle": ml(1.95, 1.95), "fanduel": ml(odds, 1.80),
                        "draftkings": ml(1.94, 1.96), "betmgm": ml(1.93, 1.97)})
        return [NFL.analyze_event(ev, threshold=3.0)]

    def test_signals_are_logged_as_paper(self):
        import bet_tracker as bt
        n = NFL.log_paper_bets(self._games(), "2026-09-08")
        self.assertEqual(n, 1)
        bet = bt.load()["bets"][0]
        self.assertTrue(bet["paper"])
        self.assertEqual(bet["stake"], 1.0)
        self.assertEqual(bet["market"], "nfl_ml")
        self.assertEqual(bet["book"], "fanduel")

    def test_the_same_signal_is_not_logged_twice(self):
        # Repere mardi puis revendredi: un seul pari, au premier prix.
        NFL.log_paper_bets(self._games(2.10), "2026-09-08")
        self.assertEqual(NFL.log_paper_bets(self._games(2.20), "2026-09-08"), 0)
        import bet_tracker as bt
        bets = bt.load()["bets"]
        self.assertEqual(len(bets), 1)
        self.assertEqual(bets[0]["odds_taken"], 2.10)

    def test_paper_bets_stay_out_of_the_real_yield(self):
        import bet_tracker as bt
        NFL.log_paper_bets(self._games(), "2026-09-08")
        bt.close_bet(bt.load()["bets"][0]["id"], result="win")
        st = bt.load()["stats"]
        self.assertEqual(st["n_counted"], 0)           # rien de reel
        self.assertEqual(st["paper"]["n_counted"], 1)  # compte a part

    def test_closing_odds_feed_the_clv(self):
        # Cas normal du dimanche: l'ecart s'est referme, le pari n'est PLUS un
        # signal. Sa cote de fermeture doit quand meme etre relevee, sinon son
        # CLV reste a jamais incalculable.
        import bet_tracker as bt
        NFL.log_paper_bets(self._games(2.10), "2026-09-08")
        ferme = self._games(1.95)
        self.assertEqual(ferme[0]["signals"], [], "le pari ne doit plus etre un signal")
        NFL.capture_closing(ferme, "2026-09-08")
        bet = bt.load()["bets"][0]
        self.assertEqual(bet["closing_odds"], 1.95)
        # 2.10 pris contre 1.95 a la fermeture: CLV positif.
        self.assertGreater(bt.load()["stats"]["clv"]["avg_clv_pct"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
