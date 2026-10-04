"""
Saisie bet365 en NFL: props joueurs et cotes boostees.

bet365 n'est pas dans le flux, donc tout passe par la page. Ce qui est
verifie, par ordre de risque:

  1. la borne de probabilite quand la ligne bet365 differe de Pinnacle — un
     mauvais sens transformerait une ligne plus difficile en faux +EV;
  2. le statut d'un boost: jambes correlees jamais « a miser »;
  3. le reglement des props (feuille ESPN) et des boosts (jambe par jambe);
  4. la page elle-meme: les lignes et le constructeur de boost sont rendus.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import nfl_props as P               # noqa: E402
import record_prediction as RP      # noqa: E402
import close_and_settle as CS       # noqa: E402
import prediction_capture as PC     # noqa: E402


def par_ligne(**books):
    """books = {book: (ligne, over, under)} -> format parse_market."""
    out = {}
    for bk, (pt, ov, un) in books.items():
        out.setdefault(float(pt), {})[bk] = {"Over": ov, "Under": un}
    return out


GAME = {"event_id": "e1", "home_team": "Buffalo Bills", "away_team": "Los Angeles Chargers",
        "commence": "2026-09-27T17:00:00Z"}


class TestReferenceLines(unittest.TestCase):

    def test_reference_is_pinnacle_novig(self):
        ref = P.reference_lines("Josh Allen", par_ligne(pinnacle=(250.5, 1.87, 1.95),
                                                        draftkings=(250.5, 1.80, 2.00)),
                                "player_pass_yds", GAME)
        self.assertEqual(ref["ligne"], 250.5)
        self.assertAlmostEqual(ref["p_over"] + ref["p_under"], 1.0, places=3)
        self.assertGreater(ref["p_over"], 0.5)           # 1.87 < 1.95: Over favori
        self.assertIn("pinnacle", ref["source"])
        self.assertEqual(ref["marche"], "nfl_prop_pass_yds")
        self.assertGreater(ref["target_over"], 1 / ref["p_over"])

    def test_no_sharp_book_no_reference(self):
        # bet365 et DraftKings ne sont pas des references.
        self.assertEqual(P.reference_lines("X", par_ligne(draftkings=(50.5, 1.9, 1.9)),
                                           "player_rush_yds", GAME), {})


class TestBoundProb(unittest.TestCase):
    REFS = [{"ligne": 64.5, "p_over": 0.56}, {"ligne": 67.5, "p_over": 0.50}]

    def test_same_line_is_exact(self):
        self.assertEqual(P.bound_prob(self.REFS, "Over", 67.5), 0.50)
        self.assertEqual(P.bound_prob(self.REFS, "Under", 67.5), 0.50)

    def test_easier_over_uses_next_reference_above(self):
        # Over 66.5 est plus facile qu'Over 67.5: au moins 50%.
        self.assertEqual(P.bound_prob(self.REFS, "Over", 66.5), 0.50)
        self.assertEqual(P.bound_prob(self.REFS, "Over", 60.5), 0.56)

    def test_easier_under_uses_next_reference_below(self):
        self.assertEqual(P.bound_prob(self.REFS, "Under", 70.5), 0.50)
        self.assertEqual(P.bound_prob(self.REFS, "Under", 65.5), 0.44)

    def test_harder_line_is_not_comparable(self):
        # Over 70.5 est plus difficile que toute reference: on ne sait pas.
        self.assertIsNone(P.bound_prob(self.REFS, "Over", 70.5))
        self.assertIsNone(P.bound_prob(self.REFS, "Under", 60.5))


class TestBoostStatus(unittest.TestCase):

    def test_independent_boost_above_threshold_is_bettable(self):
        self.assertEqual(RP.status_for({"marche": "nfl_boost", "correle": "0"}, 13.0), "a_miser")

    def test_boost_is_never_suspect(self):
        # Un boost est au-dessus du juste par construction: pas de « a verifier ».
        self.assertEqual(RP.status_for({"marche": "nfl_boost", "correle": False}, 25.0), "a_miser")

    def test_correlated_boost_is_informative(self):
        self.assertEqual(RP.status_for({"marche": "nfl_boost", "correle": "1"}, 30.0), "informatif")

    def test_small_boost_is_below_threshold(self):
        self.assertEqual(RP.status_for({"marche": "nfl_boost"}, 1.0), "sous_seuil")

    def test_boost_recorded_with_legs(self):
        legs = [{"marche": "nfl_ml", "selection": "Buffalo Bills ML",
                 "match": "Los Angeles Chargers @ Buffalo Bills", "p": 0.7534}]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.csv")
            row = RP.record({"sport": "nfl", "marche": "nfl_boost", "selection": "Boost: Buffalo Bills ML",
                             "date": "2026-09-27", "prob_finale": 0.7534, "cote_prise": 1.50,
                             "mise_u": 0.5, "legs": json.dumps(legs), "correle": "0"}, path)
            self.assertEqual(row["statut"], "a_miser")
            self.assertAlmostEqual(row["edge"], 13.01, places=1)
            import predictions_log as PL
            saved = PL.load(path)[0]
            self.assertEqual(json.loads(saved["legs"])[0]["selection"], "Buffalo Bills ML")


BOX = {"stats": {("receiving", "khalil shakir"): {"receivingYards": "71"},
                 ("passing", "josh allen"): {"passingYards": "250"}},
       "joueurs": {"khalil shakir", "josh allen", "dalton kincaid"}}


class TestSettleProps(unittest.TestCase):

    def setUp(self):
        self._box = CS.nfl_box
        CS.nfl_box = lambda match, ct: BOX

    def tearDown(self):
        CS.nfl_box = self._box

    def row(self, marche, sel):
        return {"sport": "nfl", "marche": marche, "selection": sel,
                "match": "Los Angeles Chargers @ Buffalo Bills",
                "commence_time": "2026-09-27T17:00:00Z"}

    def test_over_and_under(self):
        self.assertEqual(CS.settle_nfl_prop(self.row("nfl_prop_reception_yds", "Khalil Shakir Over 64.5")), "W")
        self.assertEqual(CS.settle_nfl_prop(self.row("nfl_prop_reception_yds", "Khalil Shakir Under 64.5")), "L")

    def test_integer_line_push(self):
        self.assertEqual(CS.settle_nfl_prop(self.row("nfl_prop_pass_yds", "Josh Allen Over 250")), "P")

    def test_played_without_catch_is_zero_yards(self):
        self.assertEqual(CS.settle_nfl_prop(self.row("nfl_prop_reception_yds", "Dalton Kincaid Over 30.5")), "L")

    def test_did_not_play_is_void(self):
        self.assertEqual(CS.settle_nfl_prop(self.row("nfl_prop_rush_yds", "James Cook Over 60.5")), "VOID")


class TestSettleBoost(unittest.TestCase):

    def setUp(self):
        self._leg = CS.settle_leg

    def tearDown(self):
        CS.settle_leg = self._leg

    def boost(self, results):
        legs = [{"selection": f"leg{i}"} for i in range(len(results))]
        CS.settle_leg = lambda leg: results[int(leg["selection"][3:])]
        return CS.settle_boost({"legs": json.dumps(legs)})

    def test_all_win(self):
        self.assertEqual(self.boost(["W", "W"]), "W")

    def test_one_loss_loses_even_if_other_unknown(self):
        self.assertEqual(self.boost(["L", None]), "L")

    def test_unknown_waits(self):
        self.assertIsNone(self.boost(["W", None]))

    def test_push_leg_voids(self):
        # bet365 recalcule a la cote non boostee: inconnue, on n'invente pas.
        self.assertEqual(self.boost(["W", "P"]), "VOID")


LINE = {"joueur": "Ja'Marr Chase", "market": "player_reception_yds",
        "marche": "nfl_prop_reception_yds", "marche_lbl": "verges de reception",
        "ligne": 80.5, "p_over": 0.52, "p_under": 0.48, "target_over": 1.98, "target_under": 2.15,
        "source": "pinnacle (shin)", "n_books": 1,
        "refs": [{"ligne": 80.5, "p_over": 0.52}],
        "game": "Cincinnati Bengals @ Pittsburgh Steelers",
        "commence": "2099-09-27T17:00:00Z", "event_id": "e9"}

STATE = {"week": "2099-09-22", "min_edge": 3.0, "n_signals": 0, "games": [
    {"event_id": "e9", "home_team": "Pittsburgh Steelers", "away_team": "Cincinnati Bengals",
     "commence": "2099-09-27T17:00:00Z", "signals": [], "markets": [],
     "prices": {"Cincinnati Bengals ML": {"market": "nfl_ml", "prob": 61.2, "fair_odds": 1.63,
                                          "target_odds": 1.68, "statut": "a_saisir"}}}],
    "props": {"week": "2099-09-22", "min_edge": 3.0, "signals": [], "lines": [LINE]}}


class TestCaptureAndPage(unittest.TestCase):

    def test_prop_lines_are_journaled_both_sides(self):
        rows = PC.nfl_prop_rows(STATE, "2099-09-27", datetime(2099, 9, 26, tzinfo=timezone.utc))
        self.assertEqual({r["selection"] for r in rows},
                         {"Ja'Marr Chase Over 80.5", "Ja'Marr Chase Under 80.5"})
        self.assertTrue(all(r["marche"] == "nfl_prop_reception_yds" for r in rows))

    def test_page_renders_prop_entry_and_boost_builder(self):
        from report_generator import ReportGenerator
        html = ReportGenerator()._nfl_section(STATE)
        self.assertIn("nfxPropUpd(this)", html)
        self.assertIn("Ja&#x27;Marr Chase", html)          # apostrophe echappee
        self.assertIn('data-marche="nfl_boost"', html)
        legs = json.loads(html.split("var NFL_LEGS=", 1)[1].split(";</script>", 1)[0])
        self.assertIn("Cincinnati Bengals ML (Cincinnati Bengals @ Pittsburgh Steelers)", legs)
        self.assertIn("Ja'Marr Chase Over 80.5 verges de reception", legs)


if __name__ == "__main__":
    unittest.main()
