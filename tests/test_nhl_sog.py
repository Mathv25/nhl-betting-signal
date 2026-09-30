"""
Module SOG (tirs au but LNH). Aucun appel reseau.

Par ordre de risque:
  1. aucune fuite: la projection d'un match n'utilise jamais ce match ni un
     match du meme jour;
  2. la force (5v5 / avantage) lue dans situationCode, du point de vue du tireur;
  3. les distributions (P(Over) coherent, binomiale negative -> Poisson quand
     r est grand).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import nhl_sog_data as D       # noqa: E402
import nhl_sog_model as M      # noqa: E402
import nhl_sog_backtest as B   # noqa: E402


class TestStrength(unittest.TestCase):

    def test_even_strength(self):
        self.assertEqual(D.strength("1551", True), "5v5")
        self.assertEqual(D.strength("1551", False), "5v5")

    def test_power_play_from_shooter_side(self):
        # 1451: exterieur 4 patineurs, domicile 5 -> avantage du domicile
        self.assertEqual(D.strength("1451", True), "pp")
        self.assertEqual(D.strength("1451", False), "autre")      # tireur en desavantage

    def test_empty_net_is_not_power_play(self):
        # 0651: l'exterieur a retire son gardien (6 patineurs contre 5).
        # Un tir du domicile vise un filet desert: « autre », pas du 5v5.
        self.assertEqual(D.strength("0651", True), "autre")
        # et le 6e attaquant de l'exterieur n'est pas un avantage numerique
        self.assertEqual(D.strength("0651", False), "autre")

    def test_parse_pbp_counts(self):
        pbp = {"homeTeam": {"id": 1, "abbrev": "AAA"}, "awayTeam": {"id": 2, "abbrev": "BBB"},
               "rosterSpots": [{"playerId": 10, "teamId": 1}, {"playerId": 20, "teamId": 2}],
               "plays": [
                   {"typeDescKey": "shot-on-goal", "situationCode": "1551", "details": {"shootingPlayerId": 10}},
                   {"typeDescKey": "missed-shot", "situationCode": "1551", "details": {"shootingPlayerId": 10}},
                   {"typeDescKey": "goal", "situationCode": "1451", "details": {"scoringPlayerId": 10}},
                   {"typeDescKey": "blocked-shot", "situationCode": "1551", "details": {"shootingPlayerId": 20}},
                   {"typeDescKey": "hit", "situationCode": "1551", "details": {}},
               ]}
        pl, tm = D.parse_pbp(pbp)
        self.assertEqual(pl[10], {"icf_5v5": 2, "sog_5v5": 1, "icf_pp": 1, "sog_pp": 1})
        self.assertEqual(pl[20]["icf_5v5"], 1)
        self.assertEqual(tm[1]["sog"], 2)          # tir cadre + but
        self.assertEqual(tm[1]["goals"], 1)
        self.assertEqual(tm[2]["icf_5v5"], 1)


class TestDistributions(unittest.TestCase):

    def test_over_decreases_with_line(self):
        ps = [M.p_over(L, 3.2, "nb", 20) for L in (1.5, 2.5, 3.5, 4.5)]
        self.assertTrue(all(a > b for a, b in zip(ps, ps[1:])))

    def test_nb_tends_to_poisson(self):
        self.assertAlmostEqual(M.p_over(2.5, 3.0, "nb", 1e6), M.p_over(2.5, 3.0, "poisson"), places=4)

    def test_nb_is_wider(self):
        # Surdispersion: plus de masse dans les queues que Poisson.
        self.assertGreater(M.p_over(6.5, 3.0, "nb", 5), M.p_over(6.5, 3.0, "poisson"))

    def test_fit_r_recovers_poisson_like_data(self):
        import random
        random.seed(1)

        def pois(l):
            k, p, L = 0, 1.0, 2.718281828 ** (-l)
            while True:
                p *= random.random()
                if p < L:
                    return k
                k += 1
        pairs = [(pois(3.0), 3.0) for _ in range(3000)]
        self.assertGreater(M.fit_nb_r(pairs), 30)      # donnees Poisson -> r grand


def row(pid, gid, day, sog, team="AAA", opp="BBB", home=1):
    return {"season": "x", "gameId": gid, "gameDate": day, "playerId": pid, "name": f"P{pid}",
            "pos": "C", "team": team, "opp": opp, "home": home, "sog": sog, "icf": sog * 2,
            "missed": sog // 2, "blocked": sog // 2, "toi": 1200.0, "toi_ev": 1000.0,
            "toi_pp": 150.0, "toi_sh": 0.0, "icf_5v5": sog, "sog_5v5": sog // 2,
            "icf_pp": sog // 2, "sog_pp": 0}


def trow(gid, day, team, opp, home):
    return {"season": "x", "gameId": gid, "gameDate": day, "team": team, "opp": opp, "home": home,
            "gf": 3, "ga": 3, "sog_for": 30, "sog_against": 30, "sog_for_5v5": 20,
            "sog_against_5v5": 20, "icf_against_5v5": 40, "pp_toi": 240.0}


class TestNoLeak(unittest.TestCase):

    def season(self, last_day_sog):
        players, teams = [], []
        for i in range(15):
            day = f"2025-11-{i + 1:02d}"
            players.append(row(1, 100 + i, day, 4))
            teams += [trow(100 + i, day, "AAA", "BBB", 1), trow(100 + i, day, "BBB", "AAA", 0)]
        # Meme jour que le match projete: un autre joueur, sog variable
        day = "2025-11-15"
        players.append(row(2, 200, day, last_day_sog, team="CCC", opp="DDD"))
        return players, teams

    def test_same_day_games_do_not_leak(self):
        old = (M.MIN_GP, M.MIN_SOG_PG, M.MIN_ICF_PG)
        M.MIN_GP, M.MIN_SOG_PG, M.MIN_ICF_PG = 3, 0, 0
        try:
            a = [x for x in B.walk(*self.season(0)) if x["gameId"] == 114]
            b = [x for x in B.walk(*self.season(15)) if x["gameId"] == 114]
            self.assertEqual(a[0]["lam"], b[0]["lam"])
            # et le resultat du match lui-meme n'entre pas dans sa projection
            p, t = self.season(0)
            for r in p:
                if r["gameId"] == 114:
                    r["sog"] = 40
            c = [x for x in B.walk(p, t) if x["gameId"] == 114]
            self.assertEqual(a[0]["lam"], c[0]["lam"])
        finally:
            M.MIN_GP, M.MIN_SOG_PG, M.MIN_ICF_PG = old


if __name__ == "__main__":
    unittest.main()


import record_prediction as RP    # noqa: E402
import close_and_settle as CS     # noqa: E402
import prediction_capture as PC   # noqa: E402


class TestSogStatus(unittest.TestCase):
    BASE = {"marche": "nhl_sog", "valide": "1", "alignement": "confirme"}

    def st(self, p, pi, **kw):
        return RP.status_for(dict(self.BASE, prob_finale=p, prob_marche_novig=pi, **kw), 0.0)

    def test_bettable_needs_edge_and_prob(self):
        self.assertEqual(self.st(0.62, 0.56), "a_miser")        # +6 pts, 62%
        self.assertEqual(self.st(0.62, 0.59), "sous_seuil")     # +3 pts seulement
        self.assertEqual(self.st(0.56, 0.50), "sous_seuil")     # proba < 58%

    def test_not_validated_is_informative(self):
        self.assertEqual(self.st(0.70, 0.50, valide="0"), "informatif")

    def test_unconfirmed_lineup_is_informative(self):
        self.assertEqual(self.st(0.70, 0.50, alignement="incertain"), "informatif")

    def test_no_suspect_rule(self):
        # +15 pts d'ecart: pas « a verifier » pour les tirs.
        self.assertEqual(self.st(0.72, 0.57), "a_miser")


class TestSogSettle(unittest.TestCase):
    BOX = {"gameState": "OFF", "playerByGameStats": {
        "homeTeam": {"forwards": [{"playerId": 8479318, "sog": 4}], "defense": []},
        "awayTeam": {"forwards": [], "defense": [{"playerId": 8480000, "sog": 0}]}}}

    def setUp(self):
        CS._nhl_box["g1"] = self.BOX

    def r(self, sel, pid):
        return {"event_id": "g1", "player_id": pid, "selection": sel}

    def test_over_under(self):
        self.assertEqual(CS.settle_nhl_sog(self.r("Auston Matthews Over 3.5 SOG", 8479318)), "W")
        self.assertEqual(CS.settle_nhl_sog(self.r("Auston Matthews Under 3.5 SOG", "8479318.0")), "L")

    def test_zero_shots_is_a_loss_not_void(self):
        self.assertEqual(CS.settle_nhl_sog(self.r("X Over 0.5 SOG", 8480000)), "L")

    def test_absent_is_void(self):
        self.assertEqual(CS.settle_nhl_sog(self.r("Y Over 2.5 SOG", 1)), "VOID")


class TestSogJournal(unittest.TestCase):

    def test_main_line_both_sides(self):
        from datetime import datetime, timezone
        st = {"valide": False, "distribution": "nb", "joueurs": [
            {"joueur": "Nathan MacKinnon", "playerId": 8477492, "lam": 3.9, "match": "COL @ DAL",
             "commence": "2099-10-10T00:00:00Z", "event_id": 7,
             "p_over": {"3.5": 0.6, "4.5": 0.4}}]}
        rows = PC.nhl_sog_rows(st, "2099-10-09", datetime(2099, 10, 9, tzinfo=timezone.utc))
        self.assertEqual({r["selection"] for r in rows},
                         {"Nathan MacKinnon Over 3.5 SOG", "Nathan MacKinnon Under 3.5 SOG"})
        self.assertTrue(all(r["statut"] == "informatif" and r["player_id"] == 8477492 for r in rows))
