"""
Tests du suivi des paris (src/bet_tracker.py).

Les chiffres de ce module servent a decider de miser ou non: un yield ou un
intervalle faux vaut moins que pas de chiffre du tout. Les valeurs attendues
sont donc calculees a la main dans les tests, jamais reprises du code.

Lancer:  python3 -m unittest discover -s tests -v
"""
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import bet_tracker as BT   # noqa: E402


def bet(prob=55.0, odds=2.0, stake=1.0, result="pending", closing=None,
        market="props_k", sport="mlb", date="2026-09-01", selection="X"):
    return {"id": f"{date}|{sport}|{market}|{selection}", "date": date,
            "sport": sport, "market": market, "selection": selection,
            "model_prob": prob, "odds_taken": odds, "stake": stake,
            "book": "betano", "closing_odds": closing, "result": result}


class TestProfit(unittest.TestCase):

    def test_win_pays_the_net_price(self):
        self.assertAlmostEqual(BT.profit(bet(odds=2.5, stake=2, result="win")), 3.0)

    def test_loss_costs_the_stake(self):
        self.assertAlmostEqual(BT.profit(bet(stake=1.5, result="loss")), -1.5)

    def test_push_is_flat(self):
        self.assertEqual(BT.profit(bet(result="push")), 0.0)

    def test_pending_has_no_profit(self):
        self.assertIsNone(BT.profit(bet(result="pending")))


class TestYieldAndInterval(unittest.TestCase):

    def test_yield_is_profit_over_turnover(self):
        # 2 gagnants a 2.00 (+1 chacun), 2 perdants (-1 chacun): profit 0
        bets = [bet(odds=2.0, result="win"), bet(odds=2.0, result="win"),
                bet(result="loss"), bet(result="loss")]
        y = BT.yield_with_ci(bets)
        self.assertEqual(y["staked"], 4.0)
        self.assertEqual(y["profit"], 0.0)
        self.assertEqual(y["yield_pct"], 0.0)

    def test_yield_respects_unequal_stakes(self):
        # 5u gagnes a 2.00 -> +5 ; 1u perdue -> -1 ; mise 6 -> +66.67%
        bets = [bet(odds=2.0, stake=5, result="win"), bet(stake=1, result="loss")]
        y = BT.yield_with_ci(bets)
        self.assertAlmostEqual(y["yield_pct"], 400 / 6, places=2)

    def test_interval_matches_the_classic_sem_at_equal_stakes(self):
        # A mises egales, l'estimateur de ratio doit redonner l'erreur-type de
        # la moyenne des rendements: sd_population / sqrt(n).
        bets = [bet(odds=2.0, result="win")] * 6 + [bet(result="loss")] * 4
        y = BT.yield_with_ci(bets)
        rets = [1.0] * 6 + [-1.0] * 4
        mean = sum(rets) / len(rets)
        sem  = math.sqrt(sum((r - mean) ** 2 for r in rets)) / len(rets)
        # Les valeurs publiees sont arrondies au centieme de point.
        self.assertAlmostEqual(y["yield_pct"], mean * 100, places=2)
        self.assertAlmostEqual(y["se_pct"], sem * 100, places=2)
        self.assertAlmostEqual(y["ci_low"], (mean - BT.Z95 * sem) * 100, places=2)
        self.assertAlmostEqual(y["ci_high"], (mean + BT.Z95 * sem) * 100, places=2)

    def test_no_interval_from_a_single_bet(self):
        # A n = 1 le residu est nul: publier [Y ; Y] ferait passer un coup de
        # chance pour une mesure precise.
        y = BT.yield_with_ci([bet(odds=2.0, result="win")])
        self.assertEqual(y["yield_pct"], 100.0)
        self.assertIsNone(y["ci_low"])
        self.assertIsNone(y["se_pct"])
        self.assertFalse(y["reliable"])

    def test_small_sample_is_flagged_unreliable(self):
        y = BT.yield_with_ci([bet(odds=2.0, result="win")] * 29)
        self.assertFalse(y["reliable"])
        y30 = BT.yield_with_ci([bet(odds=2.0, result="win")] * 15
                               + [bet(result="loss")] * 15)
        self.assertTrue(y30["reliable"])

    def test_excludes_zero_only_when_the_interval_really_does(self):
        # 60 paris a 2.00, 40 gagnants: yield +20%, intervalle etroit -> conclusif
        strong = BT.yield_with_ci([bet(odds=2.0, result="win")] * 60
                                  + [bet(result="loss")] * 40)
        self.assertGreater(strong["ci_low"], 0)
        self.assertTrue(strong["excludes_zero"])
        # 50/50 sur 100 paris: yield 0, intervalle a cheval sur 0
        flat = BT.yield_with_ci([bet(odds=2.0, result="win")] * 50
                                + [bet(result="loss")] * 50)
        self.assertFalse(flat["excludes_zero"])

    def test_nothing_settled_gives_no_yield(self):
        y = BT.yield_with_ci([])
        self.assertIsNone(y["yield_pct"])
        self.assertFalse(y["reliable"])


class TestRecord(unittest.TestCase):

    def test_wr_comes_with_average_odds_and_breakeven(self):
        bets = [bet(odds=2.0, result="win")] * 5 + [bet(odds=2.0, result="loss")] * 5
        r = BT._wr_and_odds(bets)
        self.assertEqual(r["win_rate"], 50.0)
        self.assertEqual(r["avg_odds"], 2.0)
        self.assertEqual(r["breakeven_wr"], 50.0)
        self.assertEqual(r["wr_vs_breakeven"], 0.0)

    def test_same_wr_is_good_or_bad_depending_on_price(self):
        cheap = BT._wr_and_odds([bet(odds=1.60, result="win")] * 53
                                + [bet(odds=1.60, result="loss")] * 47)
        rich  = BT._wr_and_odds([bet(odds=2.10, result="win")] * 53
                                + [bet(odds=2.10, result="loss")] * 47)
        self.assertEqual(cheap["win_rate"], rich["win_rate"])
        self.assertLess(cheap["wr_vs_breakeven"], 0)      # 53% a 1.60 perd
        self.assertGreater(rich["wr_vs_breakeven"], 0)    # 53% a 2.10 gagne

    def test_average_odds_is_stake_weighted(self):
        r = BT._wr_and_odds([bet(odds=3.0, stake=3, result="win"),
                             bet(odds=1.0 + 1e-9, stake=1, result="loss")])
        self.assertAlmostEqual(r["avg_odds"], (3.0 * 3 + 1.0 * 1) / 4, places=3)


class TestCLV(unittest.TestCase):

    def test_clv_is_price_taken_over_price_at_close(self):
        # 2.00 pris pour 1.90 a la fermeture -> +5.26%
        c = BT.clv_stats([bet(odds=2.0, closing=1.90, result="win")])
        self.assertAlmostEqual(c["avg_clv_pct"], (2.0 / 1.9 - 1) * 100, places=2)
        self.assertEqual(c["pct_positive"], 100.0)

    def test_negative_clv_when_the_market_moved_against_us(self):
        c = BT.clv_stats([bet(odds=1.80, closing=2.00, result="loss")])
        self.assertLess(c["avg_clv_pct"], 0)
        self.assertEqual(c["beat_close"], 0)

    def test_pending_bets_count_if_the_close_is_known(self):
        # Le CLV se mesure sans attendre le resultat: c'est tout son interet.
        c = BT.clv_stats([bet(odds=2.0, closing=1.90, result="pending")])
        self.assertEqual(c["n"], 1)

    def test_missing_closes_are_counted_not_ignored(self):
        c = BT.clv_stats([bet(odds=2.0, closing=1.9), bet(odds=2.0, closing=None)])
        self.assertEqual(c["n"], 1)
        self.assertEqual(c["n_missing"], 1)


class TestCalibration(unittest.TestCase):

    def test_buckets_are_five_points_wide(self):
        self.assertEqual(BT.bucket_label(50.0), "50-55")
        self.assertEqual(BT.bucket_label(54.9), "50-55")
        self.assertEqual(BT.bucket_label(55.0), "55-60")
        self.assertEqual(BT.bucket_label(72.3), "70-75")

    def test_overconfidence_shows_as_a_negative_gap(self):
        # Le modele annonce 60% et gagne 4 fois sur 10: -20 points.
        bets = ([bet(prob=60.0, result="win")] * 4
                + [bet(prob=60.0, result="loss")] * 6)
        row = BT.calibration(bets)[0]
        self.assertEqual(row["bucket"], "60-65")
        self.assertEqual(row["n"], 10)
        self.assertEqual(row["expected"], 60.0)
        self.assertEqual(row["observed"], 40.0)
        self.assertEqual(row["gap"], -20.0)
        self.assertTrue(row["thin"])          # 10 paris: tranche trop mince

    def test_buckets_come_out_sorted_and_only_when_populated(self):
        bets = [bet(prob=72.0, result="win"), bet(prob=52.0, result="loss"),
                bet(prob=61.0, result="win")]
        labels = [r["bucket"] for r in BT.calibration(bets)]
        self.assertEqual(labels, ["50-55", "60-65", "70-75"])

    def test_thin_flag_lifts_at_twenty(self):
        self.assertTrue(BT.calibration([bet(result="win")] * 19)[0]["thin"])
        self.assertFalse(BT.calibration([bet(result="win")] * 20)[0]["thin"])

    def test_pending_and_push_stay_out_of_the_curve(self):
        bets = [bet(prob=60.0, result="win"), bet(prob=60.0, result="pending"),
                bet(prob=60.0, result="push")]
        row = BT.calibration(bets)[0]
        self.assertEqual(row["n"], 1)


class TestByMarket(unittest.TestCase):

    def test_roi_never_appears_without_wr_and_odds(self):
        bets = [bet(market="props_k", odds=2.0, result="win"),
                bet(market="props_k", odds=2.0, result="loss"),
                bet(market="moneyline", odds=1.7, result="win")]
        rows = {r["market"]: r for r in BT.by_market(bets)}
        for r in rows.values():
            self.assertIsNotNone(r["roi_pct"])
            self.assertIsNotNone(r["win_rate"])
            self.assertIsNotNone(r["avg_odds"])
            self.assertIsNotNone(r["breakeven_wr"])
        self.assertEqual(rows["props_k"]["n"], 2)
        self.assertEqual(rows["props_k"]["roi_pct"], 0.0)

    def test_markets_are_ordered_by_volume(self):
        bets = ([bet(market="moneyline", result="win")]
                + [bet(market="props_k", result="win")] * 3)
        self.assertEqual([r["market"] for r in BT.by_market(bets)],
                         ["props_k", "moneyline"])


class TestStorage(unittest.TestCase):

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(prefix="bets-test"), "bets.json")

    def test_add_then_read_back(self):
        b = BT.add_bet("2026-09-02", "mlb", "props_k", "Skubal Over 6.5 K",
                       58, 1.95, "betano", 1.0, path=self.path)
        self.assertEqual(b["id"], "2026-09-02|mlb|props_k|Skubal Over 6.5 K")
        data = BT.load(self.path)
        self.assertEqual(len(data["bets"]), 1)
        self.assertEqual(data["bets"][0]["result"], "pending")
        self.assertEqual(data["stats"]["n_pending"], 1)

    def test_stats_are_refreshed_on_every_write(self):
        BT.add_bet("2026-09-02", "mlb", "props_k", "A", 58, 2.0, "b",
                   result="win", path=self.path)
        self.assertEqual(BT.load(self.path)["stats"]["yield"]["profit"], 1.0)
        BT.add_bet("2026-09-02", "mlb", "props_k", "B", 58, 2.0, "b",
                   result="loss", path=self.path)
        self.assertEqual(BT.load(self.path)["stats"]["yield"]["profit"], 0.0)

    def test_close_fills_price_and_result_independently(self):
        b = BT.add_bet("2026-09-02", "mlb", "props_k", "A", 58, 1.95, "b",
                       path=self.path)
        BT.close_bet(b["id"], closing_odds=1.83, path=self.path)
        mid = BT.load(self.path)["bets"][0]
        self.assertEqual(mid["closing_odds"], 1.83)
        self.assertEqual(mid["result"], "pending")     # resultat encore inconnu
        BT.close_bet(b["id"], result="win", path=self.path)
        self.assertEqual(BT.load(self.path)["bets"][0]["result"], "win")

    def test_two_identical_bets_are_two_bets(self):
        for _ in range(2):
            BT.add_bet("2026-09-02", "mlb", "props_k", "A", 58, 1.95, "b",
                       path=self.path)
        ids = [b["id"] for b in BT.load(self.path)["bets"]]
        self.assertEqual(len(set(ids)), 2)

    def test_closing_an_unknown_id_fails_loudly(self):
        with self.assertRaises(KeyError):
            BT.close_bet("inexistant", result="win", path=self.path)

    def test_missing_file_reads_as_empty(self):
        data = BT.load(os.path.join(self.path, "nulle-part.json"))
        self.assertEqual(data["bets"], [])


class TestInputValidation(unittest.TestCase):
    """
    Les refus sont volontairement bruyants: une cote a 0 ou une probabilite en
    fraction passerait inapercue et faussererait tous les agregats en aval.
    """

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(prefix="bets-test"), "bets.json")

    def _add(self, **kw):
        args = dict(date="2026-09-02", sport="mlb", market="props_k",
                    selection="A", model_prob=58, odds_taken=1.95, book="b",
                    path=self.path)
        args.update(kw)
        return BT.add_bet(**args)

    def test_probability_as_a_fraction_is_refused(self):
        with self.assertRaises(ValueError):
            self._add(model_prob=0.58)

    def test_impossible_probability_is_refused(self):
        with self.assertRaises(ValueError):
            self._add(model_prob=140)

    def test_odds_below_one_are_refused(self):
        with self.assertRaises(ValueError):
            self._add(odds_taken=0)
        with self.assertRaises(ValueError):
            self._add(odds_taken=0.95)

    def test_bad_date_is_refused(self):
        with self.assertRaises(ValueError):
            self._add(date="02-09-2026")

    def test_unknown_result_is_refused(self):
        with self.assertRaises(ValueError):
            self._add(result="gagne")

    def test_empty_selection_is_refused(self):
        with self.assertRaises(ValueError):
            self._add(selection="")


class TestCLIConverters(unittest.TestCase):
    """
    Les convertisseurs du CLI: ils refusent a la SAISIE, pas a l'ecriture,
    pour ne pas faire perdre une entree complete sur une faute au 5e champ.
    """

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".."))
        import track
        cls.T = track

    def test_percentage_refuses_a_fraction(self):
        self.assertEqual(self.T.pct("58"), 58.0)
        with self.assertRaises(ValueError):
            self.T.pct("0.58")
        with self.assertRaises(ValueError):
            self.T.pct("140")

    def test_american_odds_are_translated(self):
        self.assertEqual(self.T.decimal_odds("+150"), 2.5)
        self.assertEqual(self.T.decimal_odds("-200"), 1.5)
        self.assertEqual(self.T.decimal_odds("+95"), 1.95)

    def test_decimal_odds_pass_through(self):
        self.assertEqual(self.T.decimal_odds("1.95"), 1.95)
        self.assertEqual(self.T.decimal_odds(" 2.10 "), 2.10)

    def test_impossible_odds_are_refused(self):
        with self.assertRaises(ValueError):
            self.T.decimal_odds("0.9")
        with self.assertRaises(ValueError):
            self.T.decimal_odds("1")

    def test_stake_must_be_positive(self):
        self.assertEqual(self.T.positive("1.5"), 1.5)
        with self.assertRaises(ValueError):
            self.T.positive("0")
        with self.assertRaises(ValueError):
            self.T.positive("-2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
