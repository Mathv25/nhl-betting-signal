"""
Estimation des parametres LNH (nhl_dc_fit.py) sur donnees synthetiques ou les
vrais parametres sont connus. Aucun appel reseau.
"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import nhl_dc_fit as F         # noqa: E402
import nhl_dixon_coles as DC   # noqa: E402


def draw(m, rnd):
    u, acc = rnd.random(), 0.0
    for h in range(len(m)):
        for a in range(len(m)):
            acc += m[h][a]
            if u <= acc:
                return h, a
    return len(m) - 1, len(m) - 1


class TestPrepare(unittest.TestCase):

    def setUp(self):
        self._en = F.empty_net_goals
        F.empty_net_goals = lambda g: (0, 0)       # pas de play-by-play en test

    def tearDown(self):
        F.empty_net_goals = self._en

    def test_regulation_score_from_ot_and_so(self):
        games = [{"id": 1, "home": "A", "away": "B", "hs": 3, "as": 2, "end": "OT", "season": "s"},
                 {"id": 2, "home": "A", "away": "B", "hs": 2, "as": 3, "end": "SO", "season": "s"},
                 {"id": 3, "home": "A", "away": "B", "hs": 4, "as": 1, "end": "REG", "season": "s"}]
        out = {g["id"]: g for g in F.prepare(games)}
        self.assertEqual((out[1]["reg_h"], out[1]["reg_a"]), (2, 2))
        self.assertEqual((out[2]["reg_h"], out[2]["reg_a"]), (2, 2))
        self.assertEqual(out[2]["official"], 4, "le but de fusillade n'est pas un but officiel")
        self.assertEqual((out[3]["reg_h"], out[3]["reg_a"]), (4, 1))


class TestFits(unittest.TestCase):

    def test_rho_is_recovered(self):
        rnd = random.Random(11)
        games, lam = [], {}
        for i in range(6000):
            lh, la = rnd.uniform(2.2, 3.4), rnd.uniform(2.0, 3.2)
            h, a = draw(DC.reg_matrix(lh, la, -0.08), rnd)
            games.append({"id": i, "pre_h": h, "pre_a": a})
            lam[i] = (lh, la)
        self.assertAlmostEqual(F.fit_rho(games, lam), -0.08, delta=0.04)

    def test_empty_net_rates(self):
        games = []
        for i in range(100):     # menait par 1: 40 buts dans un filet desert
            games.append({"pre_h": 3, "pre_a": 2, "en_h": 1 if i < 40 else 0, "en_a": 0, "end": "REG"})
        for i in range(100):     # menait par 2 (visiteur): 20
            games.append({"pre_h": 1, "pre_a": 3, "en_h": 0, "en_a": 1 if i < 20 else 0, "end": "REG"})
        q, q2 = F.fit_empty_net(games)
        self.assertAlmostEqual(q[1], 0.40)
        self.assertAlmostEqual(q[2], 0.20)

    def test_team_strengths_find_the_better_attack(self):
        rnd = random.Random(3)
        games = []
        for i in range(2000):
            home, away = rnd.sample(["A", "B", "C", "D"], 2)
            lh = 1.05 * (3.4 if home == "A" else 2.8) * 1.0
            la = (3.4 if away == "A" else 2.8)
            h, a = draw(DC.reg_matrix(lh, la, 0.0), rnd)
            games.append({"home": home, "away": away, "pre_h": h, "pre_a": a})
        st = F.team_strengths(games)
        self.assertGreater(st["att"]["A"], max(st["att"][t] for t in "BCD"))
        self.assertAlmostEqual(st["home"], 1.05, delta=0.06)


if __name__ == "__main__":
    unittest.main(verbosity=2)
