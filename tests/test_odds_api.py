"""
Tests du client partage The Odds API (src/odds_api.py) et de l'accrochage des
cotes sur le ladder K (mlb_props_analyzer._attach_odds_to_curve).

Lancer:  python3 -m unittest discover -s tests -v
   ou:   python3 tests/test_odds_api.py

Aucun appel reseau: le garde-fou de quota est teste en forcant `remaining`, et
le cache est redirige vers un repertoire temporaire.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import odds_api as O                     # noqa: E402
import mlb_props_analyzer as MPA         # noqa: E402


class TestNoVigMath(unittest.TestCase):

    def test_implied_handles_garbage(self):
        self.assertEqual(O.implied(None), 0.0)
        self.assertEqual(O.implied(0), 0.0)
        self.assertEqual(O.implied("abc"), 0.0)
        self.assertAlmostEqual(O.implied(2.0), 0.5)

    def test_novig_splits_the_overround(self):
        self.assertAlmostEqual(O.novig_two_way(1.90, 1.90), 0.50)
        self.assertAlmostEqual(O.novig_two_way(1.50, 2.50), 0.625)

    def test_novig_needs_both_faces(self):
        # Sans le Under on ne peut pas retirer la marge: mieux vaut None que
        # 1/cote, qui surestime le marche de la vig entiere.
        self.assertIsNone(O.novig_two_way(1.50, None))
        self.assertIsNone(O.novig_two_way(None, 1.50))

    def test_novig_is_below_raw_implied(self):
        self.assertLess(O.novig_two_way(1.80, 1.90), O.implied(1.80))

    def test_ev_is_p_times_odds_minus_one(self):
        self.assertEqual(O.ev_pct(55, 2.00), 10.0)
        self.assertEqual(O.ev_pct(45, 2.00), -10.0)
        self.assertEqual(O.ev_pct(55, 1.00), 0)      # cote impossible


class TestSummarizeTwoWay(unittest.TestCase):

    BOOKS = [
        {"book": "draftkings", "over_odds": 1.95, "under_odds": 1.85},
        {"book": "pinnacle",   "over_odds": 1.88, "under_odds": 2.02},
        {"book": "fanduel",    "over_odds": 2.05, "under_odds": 1.78},
    ]

    def test_best_price_and_pinnacle_baseline_are_independent(self):
        # On mise chez le book le plus cher (fanduel) mais on juge la
        # probabilite du marche avec Pinnacle, meme s'il cote moins bien.
        s = O.summarize_two_way(self.BOOKS)
        self.assertEqual(s["best_over_odds"], 2.05)
        self.assertEqual(s["best_over_book"], "fanduel")
        self.assertEqual(s["baseline_source"], O.PINNACLE)
        self.assertAlmostEqual(s["baseline_prob"],
                               round(O.novig_two_way(1.88, 2.02) * 100, 2), places=2)
        self.assertEqual((s["n_books"], s["n_novig"]), (3, 3))

    def test_median_when_pinnacle_absent(self):
        s = O.summarize_two_way([b for b in self.BOOKS if b["book"] != O.PINNACLE])
        self.assertTrue(s["baseline_source"].startswith("mediane"))

    def test_single_sided_market_flags_the_vig(self):
        s = O.summarize_two_way([{"book": "dk", "over_odds": 1.80}])
        self.assertEqual(s["baseline_source"], "brute (vig incluse)")
        self.assertAlmostEqual(s["baseline_prob"], round(O.implied(1.80) * 100, 2), places=2)

    def test_empty_is_all_zeros(self):
        s = O.summarize_two_way([])
        self.assertEqual(s["n_books"], 0)
        self.assertEqual(s["best_over_odds"], 0)


class TestAttachOddsToCurve(unittest.TestCase):

    def setUp(self):
        self.curve = [{"line": 5.5, "k_exact": 6, "prob": 55.0},
                      {"line": 6.5, "k_exact": 7, "prob": 40.0}]

    def test_only_coted_rungs_are_touched(self):
        lines = [{"line": 5.5, "over_odds": 2.10, "over_implied": 48.0,
                  "over_book": "pinnacle", "baseline_source": "pinnacle", "n_books": 3}]
        n = MPA._attach_odds_to_curve(self.curve, lines)
        self.assertEqual(n, 1)
        self.assertEqual(self.curve[0]["ev_pct"], 15.5)      # 55% x 2.10 - 1
        self.assertEqual(self.curve[0]["edge_pct"], 14.6)    # (55-48)/48
        self.assertEqual(self.curve[0]["best_book"], "pinnacle")
        self.assertNotIn("best_odds", self.curve[1])

    def test_unusable_prices_are_skipped(self):
        self.assertEqual(MPA._attach_odds_to_curve(self.curve, [{"line": 5.5, "over_odds": 0}]), 0)
        self.assertEqual(MPA._attach_odds_to_curve(self.curve, [{"line": 5.5, "over_odds": 1.0}]), 0)
        self.assertEqual(MPA._attach_odds_to_curve(self.curve, []), 0)


class TestQuotaGuard(unittest.TestCase):

    def setUp(self):
        O.reset_client()
        self._cache = tempfile.mkdtemp(prefix="odds-cache-test")
        os.environ["ODDS_CACHE_DIR"] = self._cache

    def tearDown(self):
        O.reset_client()
        os.environ.pop("ODDS_CACHE_DIR", None)

    def test_call_refused_before_eating_the_reserve(self):
        c = O.get_client("cle-de-test")
        c.remaining = O.quota_reserve() + 5
        out = c.get("sports/baseball_mlb/events/x/odds",
                    {"markets": "pitcher_strikeouts", "regions": "us"}, cost=10)
        self.assertIsNone(out)
        self.assertEqual((c.refused, c.calls), (1, 0))

    def test_unhealthy_states_stop_spending(self):
        c = O.get_client("cle-de-test")
        self.assertTrue(c.healthy)
        c.key_invalid = True
        self.assertFalse(c.healthy)
        self.assertIsNone(c.get("sports/x/odds", {"regions": "us"}, cost=1))
        self.assertEqual(c.calls, 0)

    def test_cache_serves_without_a_call(self):
        c = O.get_client("cle-de-test")
        params = {"regions": "us", "markets": "h2h"}
        c._cache_write(c._key("sports/x/odds", params), [{"id": "abc"}])
        self.assertEqual(c.get("sports/x/odds", params, cost=2), [{"id": "abc"}])
        self.assertEqual((c.calls, c.cache_hits), (0, 1))

    def test_missing_key_never_calls(self):
        c = O.get_client("")
        self.assertIsNone(c.get("sports/x/odds", {"regions": "us"}))
        self.assertEqual(c.calls, 0)
        self.assertFalse(c.healthy)


class TestSpendingPace(unittest.TestCase):
    """
    Le rythme est ce qui empeche un cron horaire d'epuiser un quota MENSUEL.
    Il se calcule sur le quota reellement restant (en-tete de l'API), donc il
    ne suppose aucun palier d'abonnement, et il se plafonne a la JOURNEE: un
    plafond par execution, multiplie par 24 crons, redonne une depense
    mensuelle enorme.
    """

    def setUp(self):
        from datetime import date
        O.reset_client()
        self.jan2 = date(2026, 1, 2)     # 30 jours restants
        self.dir  = tempfile.mkdtemp(prefix="odds-usage-test")
        os.environ["ODDS_USAGE_PATH"] = os.path.join(self.dir, "odds_usage.json")

    def tearDown(self):
        O.reset_client()
        os.environ.pop("ODDS_USAGE_PATH", None)

    def test_days_left_counts_today(self):
        from datetime import date
        self.assertEqual(O.days_left_in_month(date(2026, 1, 31)), 1)
        self.assertEqual(O.days_left_in_month(date(2026, 1, 1)), 31)
        self.assertEqual(O.days_left_in_month(date(2026, 2, 28)), 1)   # 2026 non bissextile

    def test_daily_budget_spreads_what_is_left_over_the_month(self):
        # 20 000 credits, 30 jours -> ~665 credits par jour
        self.assertEqual(O.daily_budget(20000, self.jan2), (20000 - 40) // 30)
        # Petit palier: 460 utilisables / 30 jours = 15 credits/jour, moins
        # qu'un seul appel props (10 a 20) -> props effectivement coupees.
        self.assertEqual(O.daily_budget(500, self.jan2), 15)

    def test_budget_never_negative(self):
        self.assertEqual(O.daily_budget(10, self.jan2), 0)     # sous la reserve

    def test_unknown_quota_imposes_no_pace(self):
        self.assertIsNone(O.daily_budget(None))
        c = O.get_client("cle")
        self.assertIsNone(c.day_budget())
        self.assertTrue(c.can_spend_props(200))

    def test_pace_refuses_once_the_day_budget_is_spent(self):
        c = O.get_client("cle")
        c.remaining = 20000
        budget = c.day_budget()
        self.assertGreater(budget, 100)
        self.assertTrue(c.can_spend_props(20))
        c.note_props(budget)
        self.assertFalse(c.can_spend_props(20))

    def test_budget_is_frozen_for_the_run(self):
        # Il ne doit pas glisser a mesure que `remaining` baisse, sinon la
        # depense autorisee change au milieu de l'execution.
        c = O.get_client("cle")
        c.remaining = 20000
        first = c.day_budget()
        c.remaining = 12000
        self.assertEqual(c.day_budget(), first)

    def test_small_plan_spends_nothing_on_props(self):
        # Sur un petit palier le budget du jour vaut moins qu'un seul appel
        # props (10 a 20 credits): refuser est le bon comportement. L'ancienne
        # exception "premier appel" laissait passer 20 credits par execution
        # horaire, soit ~14 000 par mois.
        #
        # On teste la propriete, pas un nombre fige: le budget depend du nombre
        # de jours restants dans le mois, donc une valeur en dur casse le
        # lendemain (460/29 = 15 le 2 du mois, 460/28 = 16 le 3).
        c = O.get_client("cle")
        c.remaining = 500
        budget = c.day_budget()
        self.assertEqual(budget, O.daily_budget(500))
        self.assertLess(budget, 20)
        self.assertFalse(c.can_spend_props(20))

    def test_spending_of_earlier_runs_counts_against_today(self):
        # Une execution precedente a deja depense 600 credits aujourd'hui:
        # la suivante doit le voir, sinon chaque cron repart avec le budget
        # complet (le disque de CI est vide a chaque fois, le depot non).
        O.save_usage({"date": O.today_et(), "remaining_at_start": 20000})
        c = O.get_client("cle")
        c.remaining = 19400
        self.assertEqual(c.spent_today(), 600)
        budget = c.day_budget()
        self.assertTrue(c.can_spend_props(budget - 600))
        self.assertFalse(c.can_spend_props(budget - 600 + 1))

    def test_a_new_day_resets_the_counter(self):
        O.save_usage({"date": "2020-01-01", "remaining_at_start": 20000})
        c = O.get_client("cle")
        c.remaining = 5000
        self.assertEqual(c.spent_today(), 0)
        self.assertEqual(c.usage()["remaining_at_start"], 5000)

    def test_plan_renewal_mid_month_is_absorbed(self):
        # Le quota remonte (renouvellement): sans ce cas, spent_today
        # deviendrait negatif ou le budget resterait bloque sur l'ancien.
        O.save_usage({"date": O.today_et(), "remaining_at_start": 300})
        c = O.get_client("cle")
        c.remaining = 20000
        self.assertEqual(c.spent_today(), 0)
        self.assertEqual(c.usage()["remaining_at_start"], 20000)

    def test_persist_then_reload_keeps_the_day(self):
        c = O.get_client("cle")
        c.remaining = 20000
        c.usage()
        c.remaining = 19500
        c.persist_usage()
        st = O.load_usage()
        self.assertEqual(st["date"], O.today_et())
        self.assertEqual(st["remaining_at_start"], 20000)
        self.assertEqual(st["spent_today"], 500)


class TestPropsWindow(unittest.TestCase):
    """La fenetre horaire evite de bruler le budget du jour la nuit."""

    def tearDown(self):
        os.environ.pop("ODDS_PROPS_HOURS_ET", None)
        O._window_warned = False

    def test_default_window_covers_the_slate_not_the_night(self):
        self.assertTrue(O.props_window_open(10))
        self.assertTrue(O.props_window_open(19))
        self.assertTrue(O.props_window_open(23))
        self.assertFalse(O.props_window_open(3))
        self.assertFalse(O.props_window_open(9))

    def test_window_is_configurable(self):
        os.environ["ODDS_PROPS_HOURS_ET"] = "16-22"
        self.assertEqual(O.props_window(), (16, 22))
        self.assertFalse(O.props_window_open(10))
        self.assertTrue(O.props_window_open(16))

    def test_garbage_setting_falls_back_to_default(self):
        os.environ["ODDS_PROPS_HOURS_ET"] = "n'importe quoi"
        self.assertEqual(O.props_window(), (10, 23))

    def test_switch_is_independent_of_the_window(self):
        os.environ["ODDS_PROPS_ENABLED"] = "0"
        try:
            self.assertFalse(O.props_enabled())
        finally:
            os.environ.pop("ODDS_PROPS_ENABLED", None)
        self.assertTrue(O.props_enabled())


class TestMoneylineMarketProbs(unittest.TestCase):
    """
    devig DANS un book vs devig sur les meilleures cotes du marche. La seconde
    methode melange deux marges: la probabilite penche vers le book qui a
    l'ecart le plus genereux, et on s'attribue cet ecart comme s'il venait du
    marche.
    """

    def setUp(self):
        import mlb_ml_analyzer
        self.M = mlb_ml_analyzer

    def test_pinnacle_book_is_the_baseline(self):
        entry = {
            "ml": {"Boston Red Sox": 1.66, "Seattle Mariners": 2.35},
            "ml_books": {
                "pinnacle":   {"Boston Red Sox": 1.70, "Seattle Mariners": 2.30},
                "draftkings": {"Boston Red Sox": 1.66, "Seattle Mariners": 2.35},
            },
        }
        p_home, p_away, src = self.M.market_probs(entry, "Boston Red Sox", "Seattle Mariners")
        self.assertEqual(src, "pinnacle")
        self.assertAlmostEqual(p_home, 0.575, places=3)
        self.assertAlmostEqual(p_home + p_away, 1.0, places=6)

    def test_falls_back_to_best_prices_without_book_detail(self):
        entry = {"ml": {"A": 2.00, "B": 2.00}}
        p_a, p_b, src = self.M.market_probs(entry, "A", "B")
        self.assertAlmostEqual(p_a, 0.5)
        self.assertIn("meilleures cotes", src)

    def test_no_odds_gives_nothing(self):
        p_a, p_b, src = self.M.market_probs({}, "A", "B")
        self.assertIsNone(p_a)
        self.assertIsNone(p_b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
