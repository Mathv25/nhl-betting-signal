"""
Onglet NFL refait (2026-10-04): mediane implicite, p a une ligne bet365
differente, edge, Kelly, statuts, saisie/fermeture et parite Python/JS.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import nfl_prop_model as M      # noqa: E402
import nfl_tab                  # noqa: E402
import performance as PERF      # noqa: E402
import predictions_log as PL    # noqa: E402
import record_prediction as RP  # noqa: E402


def bucket(lo, hi, ratios, valide=True):
    """Tranche synthetique: quantiles exacts d'une liste de ratios."""
    r = sorted(ratios)
    n = len(r)
    q = []
    for k in range(201):
        x = k / 200 * (n - 1)
        i = int(x)
        j = min(i + 1, n - 1)
        q.append(r[i] + (x - i) * (r[j] - r[i]))
    return {"lo": lo, "hi": hi, "n": n, "q": q, "valide": valide}


UNIF = [i / 1000 * 2 for i in range(1001)]          # ratio ~ U(0, 2)
CAL = {"buckets": [bucket(0, 50, UNIF), bucket(50, 1e9, UNIF)]}


class MedianeImplicite(unittest.TestCase):
    def test_round_trip_reproduces_pinnacle(self):
        cm = M.load_calibration()["markets"]["nfl_prop_reception_yds"]
        for line, p in ((45.5, 0.5), (45.5, 0.56), (72.5, 0.44)):
            m = M.implied_median(cm, line, p)
            self.assertAlmostEqual(M.prob_at(cm, m, line, "Over"), p, places=3)

    def test_higher_over_prob_means_higher_median(self):
        cm = M.load_calibration()["markets"]["nfl_prop_reception_yds"]
        self.assertGreater(M.implied_median(cm, 60.5, 0.58), M.implied_median(cm, 60.5, 0.50))

    def test_uniform_distribution_analytic(self):
        # ratio ~ U(0,2): P(Over L) = 1 - L/(2m) -> 50 % a L = m
        self.assertAlmostEqual(M.implied_median(CAL, 40.5, 0.5), 40.5, places=1)

    def test_degenerate_inputs(self):
        self.assertIsNone(M.implied_median(CAL, 40.5, 0.0))
        self.assertIsNone(M.implied_median(CAL, 0, 0.5))
        self.assertIsNone(M.implied_median({}, 40.5, 0.5))


class ProbHorsLigne(unittest.TestCase):
    def test_easier_line_has_higher_probability(self):
        cm = M.load_calibration()["markets"]["nfl_prop_reception_yds"]
        m = M.implied_median(cm, 60.5, 0.5)
        self.assertGreater(M.prob_at(cm, m, 56.5, "Over"), M.prob_at(cm, m, 60.5, "Over"))
        self.assertGreater(M.prob_at(cm, m, 64.5, "Under"), M.prob_at(cm, m, 60.5, "Under"))

    def test_half_line_sides_sum_to_one(self):
        self.assertAlmostEqual(M.prob_at(CAL, 40, 37.5, "Over") + M.prob_at(CAL, 40, 37.5, "Under"), 1.0)

    def test_whole_line_excludes_push(self):
        o, u = M.prob_at(CAL, 40, 40, "Over"), M.prob_at(CAL, 40, 40, "Under")
        self.assertLess(o + u, 1.0)
        self.assertAlmostEqual(o, 1 - 40.5 / 80, places=3)

    def test_no_jump_across_tranches(self):
        cm = M.load_calibration()["markets"]["nfl_prop_reception_yds"]
        ps = [M.prob_at(cm, m, 45.5, "Over") for m in range(40, 70)]
        self.assertTrue(all(abs(a - b) < 0.02 for a, b in zip(ps, ps[1:])))

    def test_zero_atom_counted(self):
        b = bucket(0, 1e9, [0.0] * 300 + [1.0] * 700)
        self.assertAlmostEqual(M.survival(b, 0.0), 0.7, delta=0.01)   # resolution 0.5 %
        self.assertEqual(M.survival(b, -1), 1.0)


class EdgeKellyStatut(unittest.TestCase):
    def test_edge(self):
        self.assertAlmostEqual(M.edge(1.90, 0.565), 0.0735)

    def test_kelly_quarter_and_cap(self):
        self.assertAlmostEqual(M.kelly_pct(0.55, 2.0, cap_pct=99), 2.5)       # f=0.10 -> 1/4
        self.assertEqual(M.kelly_pct(0.565, 1.90), 2.0)                       # plafond 2 %
        self.assertEqual(M.kelly_pct(0.50, 1.90), 0.0)                        # edge negatif

    def test_status_rules(self):
        self.assertEqual(M.prop_status(0.565, 1.90), "a_miser")
        self.assertEqual(M.prop_status(0.53, 2.00), "sous_seuil")              # p < 55 %
        self.assertEqual(M.prop_status(0.70, 1.55), "sous_seuil")              # cote < 1.60
        self.assertEqual(M.prop_status(0.50, 2.20), "sous_seuil")              # cote > 2.10
        self.assertEqual(M.prop_status(0.62, 1.90), "a_verifier")              # edge > 12 %


class Calibration(unittest.TestCase):
    def test_every_production_tranche_is_validated_or_flagged(self):
        cal = M.load_calibration()
        for mk in ("nfl_prop_reception_yds", "nfl_prop_rush_yds", "nfl_prop_pass_yds"):
            for b in cal["markets"][mk]["buckets"]:
                self.assertIn("valide", b)
                self.assertEqual(len(b["q"]), 201)
                self.assertEqual(b["q"], sorted(b["q"]))

    def test_report_has_out_of_sample_thresholds(self):
        here = os.path.dirname(os.path.abspath(__file__))
        rep = json.load(open(os.path.join(here, "..", "docs", "nfl_calibration_report.json")))
        seuils = {l["seuil"] for l in rep["markets"]["nfl_prop_reception_yds"]["lignes"]}
        self.assertEqual(seuils, {0.8, 0.9, 1.1, 1.2})
        self.assertNotIn(rep["meta"]["test"], rep["meta"]["calibration"])


@unittest.skipUnless(shutil.which("node"), "node absent")
class PariteJS(unittest.TestCase):
    def test_js_matches_python(self):
        cal = M.load_calibration()["markets"]
        cases = [("nfl_prop_reception_yds", 49.3, 43.5, "Over"), ("nfl_prop_reception_yds", 73.9, 70, "Under"),
                 ("nfl_prop_rush_yds", 65.3, 60.5, "Over"), ("nfl_prop_pass_yds", 256.8, 249.5, "Under")]
        js = ("var NFL_ST={KELLY_FRACTION:0.25,MAX_BET_PCT:2};" + nfl_tab.JS.split("document.addEventListener")[0]
              + "var C=" + json.dumps(cal) + ";console.log(JSON.stringify(" + json.dumps(cases)
              + ".map(function(c){return nfxProbAt(C[c[0]],c[1],c[2],c[3]);})));")
        out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
        for (mk, m, L, side), pj in zip(cases, out):
            self.assertAlmostEqual(pj, M.prob_at(cal[mk], m, L, side), places=9)


class Onglet(unittest.TestCase):
    LINE = {"joueur": "A", "market": "player_reception_yds", "marche": "nfl_prop_reception_yds",
            "marche_lbl": "verges de reception", "ligne": 45.5, "p_over": 0.5, "p_under": 0.5,
            "game": "X @ Y", "commence": "2099-01-01T18:00:00Z", "event_id": "e"}

    def test_low_median_players_are_hidden(self):
        cal = M.load_calibration()
        small = dict(self.LINE, joueur="B", ligne=9.5)
        rows = nfl_tab.prop_rows([self.LINE, small], cal)
        self.assertEqual([r["joueur"] for r in rows], ["A"])
        self.assertGreater(rows[0]["mediane"], M.MIN_MEDIAN)

    def test_main_lines_are_folded_and_have_no_entry(self):
        st = {"games": [{"away_team": "X", "home_team": "Y", "commence": "2099-01-01T18:00:00Z",
                         "prices": {"Y ML": {"market": "nfl_ml", "prob": 60.0, "fair_odds": 1.667}}}],
              "props": {"lines": [self.LINE]}}
        html = nfl_tab.render(st)
        main = html.split("Lignes principales", 1)[1].split("</details>", 1)[0]
        self.assertIn("marché efficace", main)
        self.assertNotIn("rec-odds", main)
        self.assertIn('data-nfx="1"', html)


class Journal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "p.csv")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def pay(self, **kw):
        p = {"sport": "nfl", "marche": "nfl_prop_reception_yds", "selection": "A Over 41.5",
             "date": "2099-01-01", "prob_modele": 0.565, "prob_finale": 0.565, "cote_prise": 1.90,
             "mise_u": 2.0, "ligne": 41.5, "ligne_reference": 45.5, "valide": "1", "src": "props"}
        p.update(kw)
        return p

    def test_prop_status_and_stored_fields(self):
        row = RP.record(self.pay(), self.path)
        self.assertEqual(row["statut"], "a_miser")
        saved = PL.load(self.path)[0]
        self.assertEqual(float(saved["ligne_reference"]), 45.5)
        self.assertEqual(saved["source"], "saisie manuelle · props")

    def test_unvalidated_tranche_is_informative(self):
        self.assertEqual(RP.record(self.pay(valide="0"), self.path)["statut"], "informatif")

    def test_suspect_edge(self):
        self.assertEqual(RP.record(self.pay(prob_finale=0.62, prob_modele=0.62), self.path)["statut"], "a_verifier")

    def test_closing_clv_and_performance(self):
        row = RP.record(self.pay(), self.path)
        RP.record({"action": "fermeture", "id": row["id"], "cote_fermeture": 1.80}, self.path)
        rows = PL.load(self.path)
        self.assertAlmostEqual(float(rows[0]["clv"]), 1.90 / 1.80 - 1, places=4)
        src = PERF.nfl_sources(rows)["Props (ligne ajustee)"]
        self.assertEqual(src["n"], 1)
        self.assertAlmostEqual(src["clv_moyen"], 1.90 / 1.80 - 1, places=4)
        self.assertEqual(len(PERF.nfl_open(rows)), 1)

    def test_closing_unknown_id_is_refused(self):
        with self.assertRaises(ValueError):
            RP.record({"action": "fermeture", "id": "nope", "cote_fermeture": 1.8}, self.path)


if __name__ == "__main__":
    unittest.main()
