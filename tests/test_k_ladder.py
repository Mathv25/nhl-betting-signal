"""
Tests du modele K en deux etapes (src/mlb_k_distribution.py) et de son
branchement dans le ladder de l'analyzer.

Lancer:  python3 -m unittest discover -s tests -v
   ou:   python3 tests/test_k_ladder.py

Aucun appel reseau: on injecte des listes d'IP en dur.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import mlb_k_distribution as KD          # noqa: E402
import mlb_props_analyzer as MPA         # noqa: E402

# 15 departs reels de Logan Webb (2026) — inclut deux sorties courtes (3.0, 2.2)
WEBB_IP = [7.0, 4.0, 4.333, 7.0, 8.0, 8.0, 8.0, 7.0, 3.0,
           7.0, 6.667, 6.0, 6.0, 6.0, 8.0]

# Lanceur a duree tres reguliere: variance d'IP quasi nulle
STABLE_IP = [6.0] * 15

LADDER_MIN, LADDER_MAX = 3, 10


def poisson_at_least(n, lam):
    """P(K >= n) d'un Poisson simple, pour comparaison (serie exacte)."""
    import math
    cdf = sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(n))
    return max(0.0, 1.0 - cdf) * 100


class TestIPDistribution(unittest.TestCase):

    def test_empirical_is_a_distribution(self):
        dist = KD.empirical_ip_distribution(WEBB_IP)
        self.assertTrue(dist)
        self.assertAlmostEqual(sum(p for _, p in dist), 1.0, places=9)
        for ip, p in dist:
            self.assertGreater(p, 0.0)
            self.assertGreaterEqual(ip, 1.0 / 3.0)
            self.assertLessEqual(ip, KD.IP_MAX)

    def test_empirical_mean_matches_sample(self):
        dist = KD.empirical_ip_distribution(WEBB_IP)
        expected = sum(WEBB_IP) / len(WEBB_IP)
        self.assertAlmostEqual(KD.dist_mean(dist), expected, delta=0.05)

    def test_recentring_hits_the_target_mean(self):
        for target in (4.0, 5.0, 5.5, 6.5, 7.5):
            dist = KD.empirical_ip_distribution(WEBB_IP, mean_ip=target)
            self.assertAlmostEqual(KD.dist_mean(dist), target, delta=0.05,
                                   msg=f"recentrage rate pour IP moy {target}")
            self.assertAlmostEqual(sum(p for _, p in dist), 1.0, places=9)

    def test_binomial_fallback_is_centred_and_truncated(self):
        for target in (4.0, 5.3, 6.5):
            dist = KD.binomial_ip_distribution(target)
            self.assertAlmostEqual(sum(p for _, p in dist), 1.0, places=9)
            self.assertAlmostEqual(KD.dist_mean(dist), target, delta=0.05)
            self.assertGreaterEqual(min(ip for ip, _ in dist), KD.IP_MIN)
            self.assertLessEqual(max(ip for ip, _ in dist), KD.IP_MAX)

    def test_few_starts_uses_binomial(self):
        model = KD.build_k_model(6.0, [6.0, 5.0], mean_ip=5.5)
        self.assertEqual(model["source"], "binomiale tronquee")
        model15 = KD.build_k_model(6.0, WEBB_IP, mean_ip=6.4)
        self.assertTrue(model15["source"].startswith("empirique"))

    def test_no_ip_data_still_builds(self):
        model = KD.build_k_model(6.0, None, None)
        self.assertEqual(model["source"], "binomiale tronquee")
        self.assertGreater(model["mean_ip"], 0)
        self.assertGreater(KD.p_at_least(model, 3), 0)


class TestLadderMonotonicity(unittest.TestCase):
    """P(K>=3) > P(K>=4) > ... > P(K>=10), strictement."""

    def _assert_strictly_decreasing(self, probs, label):
        for a, b in zip(probs, probs[1:]):
            self.assertGreater(a, b, msg=f"{label}: ladder non decroissant ({a} <= {b})")

    def test_strictly_decreasing_empirical(self):
        for lam in (4.0, 5.39, 5.86, 7.5, 9.5):
            model = KD.build_k_model(lam, WEBB_IP, mean_ip=6.4)
            probs = [c["prob"] for c in KD.ladder(model, LADDER_MIN, LADDER_MAX)]
            self.assertEqual(len(probs), LADDER_MAX - LADDER_MIN + 1)
            self._assert_strictly_decreasing(probs, f"lambda={lam} empirique")

    def test_strictly_decreasing_binomial_and_degenerate(self):
        for ip_values, mean_ip, label in ((None, 5.3, "binomiale"),
                                          (STABLE_IP, 6.0, "IP constant")):
            for lam in (4.0, 6.0, 9.0):
                model = KD.build_k_model(lam, ip_values, mean_ip=mean_ip)
                probs = [c["prob"] for c in KD.ladder(model, LADDER_MIN, LADDER_MAX)]
                self._assert_strictly_decreasing(probs, f"{label} lambda={lam}")

    def test_probabilities_are_valid_percentages(self):
        model = KD.build_k_model(5.86, WEBB_IP, mean_ip=6.4)
        for c in KD.ladder(model, 1, 20):
            self.assertGreaterEqual(c["prob"], 0.0)
            self.assertLessEqual(c["prob"], 100.0)

    def test_calibrated_ladder_stays_ordered(self):
        """La calibration est affine croissante: elle ne doit pas casser l'ordre."""
        model = KD.build_k_model(5.86, WEBB_IP, mean_ip=6.4)
        probs = [c["prob"] for c in MPA._k_curve(model)]
        for a, b in zip(probs, probs[1:]):
            self.assertGreaterEqual(a, b)
        self.assertGreater(probs[0], probs[-1])


class TestCoherenceWithLambda(unittest.TestCase):

    def test_expected_value_equals_lambda(self):
        """E[K] = rate * E[IP] doit retomber exactement sur lambda_ajuste."""
        for lam in (4.0, 5.39, 5.86, 7.5, 9.5):
            for ip_values, mean_ip in ((WEBB_IP, 6.4), (None, 5.3), (STABLE_IP, 6.0)):
                model = KD.build_k_model(lam, ip_values, mean_ip=mean_ip)
                self.assertAlmostEqual(KD.moments(model)["mean"], lam, delta=0.02,
                                       msg=f"E[K] != lambda pour {lam}")

    def test_ladder_sums_back_to_lambda(self):
        """
        Verification independante du ladder lui-meme via l'identite
        E[K] = somme_{n>=1} P(K >= n): si un barreau est decale (l'ancien bug
        du +0.5 sur la ligne), cette somme ne retombe plus sur lambda.
        """
        for lam in (4.0, 5.86, 7.5, 9.5):
            model = KD.build_k_model(lam, WEBB_IP, mean_ip=6.4)
            total = sum(KD.p_at_least(model, n) / 100.0 for n in range(1, 80))
            self.assertAlmostEqual(total, lam, delta=0.05,
                                   msg=f"somme des P(K>=n) = {total:.3f} != lambda {lam}")

    def test_median_rung_brackets_lambda(self):
        """Le barreau juste sous lambda doit etre > 50%, celui juste au-dessus < 50%."""
        lam = 6.0
        model = KD.build_k_model(lam, WEBB_IP, mean_ip=6.4)
        self.assertGreater(KD.p_at_least(model, 4), 50.0)
        self.assertLess(KD.p_at_least(model, 8), 50.0)

    def test_higher_lambda_shifts_every_rung_up(self):
        low  = KD.build_k_model(5.0, WEBB_IP, mean_ip=6.4)
        high = KD.build_k_model(7.0, WEBB_IP, mean_ip=6.4)
        for n in range(LADDER_MIN, LADDER_MAX + 1):
            self.assertGreater(KD.p_at_least(high, n), KD.p_at_least(low, n),
                               msg=f"K>={n} ne monte pas avec lambda")


class TestOverdispersion(unittest.TestCase):
    """Le point du chantier: la variance doit depasser celle d'un Poisson."""

    def test_variance_exceeds_poisson(self):
        lam   = 5.86
        model = KD.build_k_model(lam, WEBB_IP, mean_ip=6.4)
        mom   = KD.moments(model)
        self.assertGreater(mom["var"], mom["poisson_var"])
        self.assertGreater(mom["overdispersion"], 1.10)

    def test_no_overdispersion_when_ip_is_constant(self):
        """Sans variance d'IP, on doit retomber exactement sur le Poisson simple."""
        lam   = 6.0
        model = KD.build_k_model(lam, STABLE_IP, mean_ip=6.0)
        mom   = KD.moments(model)
        self.assertAlmostEqual(mom["var"], mom["poisson_var"], delta=0.01)
        for n in range(LADDER_MIN, LADDER_MAX + 1):
            self.assertAlmostEqual(KD.p_at_least(model, n), poisson_at_least(n, lam),
                                   delta=0.5, msg=f"K>={n} devrait etre Poisson pur")

    def test_tails_are_fatter_than_poisson(self):
        lam   = 5.86
        model = KD.build_k_model(lam, WEBB_IP, mean_ip=6.4)
        # Queue haute plus epaisse
        self.assertGreater(KD.p_at_least(model, 10), poisson_at_least(10, lam))
        # Queue basse aussi: moins de masse sur les barreaux faciles
        self.assertLess(KD.p_at_least(model, 3), poisson_at_least(3, lam))


class TestSingleSourceOfTruth(unittest.TestCase):
    """Le ladder, le filtre de surprice et l'edge doivent lire le meme modele."""

    def test_p_over_matches_ladder_rung(self):
        model = KD.build_k_model(5.86, WEBB_IP, mean_ip=6.4)
        for c in MPA._k_curve(model):
            self.assertAlmostEqual(
                MPA._k_prob_over(model, c["line"]), c["prob"], places=6,
                msg=f"P(Over {c['line']}) != barreau K>={c['k_exact']}")

    def test_over_line_reads_as_next_integer(self):
        model = KD.build_k_model(6.0, WEBB_IP, mean_ip=6.4)
        # Over 4.5 == K >= 5 (et non K >= 4, ni P(K > 5) comme avant le fix)
        self.assertAlmostEqual(KD.p_over(model, 4.5), KD.p_at_least(model, 5), places=9)
        self.assertNotAlmostEqual(KD.p_over(model, 4.5), KD.p_at_least(model, 6), places=2)

    def test_best_line_comes_from_the_same_curve(self):
        model = KD.build_k_model(6.5, WEBB_IP, mean_ip=6.4)
        best  = MPA._k_best_line(model)
        self.assertIsNotNone(best)
        rung = next(c for c in MPA._k_curve(model) if c["k_exact"] == best["k_exact"])
        self.assertAlmostEqual(best["prob"], rung["prob"], places=6)
        # La ligne retenue doit rester jouable au-dessus du plancher de cote
        self.assertGreaterEqual(best["min_odds"], MPA.MIN_ODDS)

    def test_dk_edge_uses_the_model_probability(self):
        model = KD.build_k_model(6.0, WEBB_IP, mean_ip=6.4)
        lines = [{"line": 4.5, "over_implied": 50.0, "over_odds": 2.0},
                 {"line": 5.5, "over_implied": 40.0, "over_odds": 2.4}]
        best = MPA._best_dk_edge(model, lines)
        self.assertIsNotNone(best)
        self.assertAlmostEqual(best["our_prob"], MPA._k_prob_over(model, best["line"]),
                               places=6)

    def test_lambda_is_the_regressed_projection(self):
        """build_k_model de l'analyzer doit centrer le modele sur adj_mean."""
        proj = MPA._k_projection(5.82, 0.238, 0.2207, 1.00)   # ~ Logan Webb
        model = KD.build_k_model(proj["adj"], WEBB_IP, mean_ip=6.4)
        self.assertAlmostEqual(model["lambda"], proj["adj"], places=6)
        self.assertAlmostEqual(KD.moments(model)["mean"], proj["adj"], delta=0.02)
        # ... et surement pas sur la projection brute
        self.assertNotAlmostEqual(model["lambda"], proj["adj_raw"], places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
