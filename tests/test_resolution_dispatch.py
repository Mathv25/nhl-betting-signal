"""
Test de la repartition des resolveurs MLB (src/backtester.resolve_mlb_bet).

Ce test existe pour un bug precis et couteux: un pari d'equipe envoye dans le
resolveur de PROPS y cherche un joueur nomme "Boston Red Sox" dans le
boxscore, ne le trouve pas, et renvoie VOID. Resultat, 176 paris d'equipe sur
181 ont ete annules sans que rien ne le signale — un VOID n'est ni une perte
ni une erreur — et le modele moneyline n'a jamais recu un seul resultat.

Le bug avait deux tetes: le filtre du controle d'alignement, puis la boucle de
re-verification qui re-annulait les paris deja corriges. D'ou une fonction de
repartition unique, testee ici sans reseau.

Lancer:  python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import backtester as B   # noqa: E402


class TestResolutionDispatch(unittest.TestCase):

    def setUp(self):
        self.calls = []
        self._orig = (B.resolve_mlb_team_bet, B.resolve_mlb_prop)

        def fake_team(bet, date):
            self.calls.append(("team", bet.get("name"), date))
            return "W"

        def fake_prop(prop, date):
            self.calls.append(("prop", prop.get("player"), date))
            # Le vrai resolveur renvoie VOID quand le joueur est introuvable:
            # c'est exactement ce qu'on ne veut plus voir pour une equipe.
            return "VOID" if " " in (prop.get("player") or "") and prop.get("stat_key") == "moneyline" else "L"

        B.resolve_mlb_team_bet, B.resolve_mlb_prop = fake_team, fake_prop

    def tearDown(self):
        B.resolve_mlb_team_bet, B.resolve_mlb_prop = self._orig

    def _bet(self, **kw):
        base = {"sport": "mlb", "bet_type": "prop", "market_type": "strikeouts",
                "name": "Tarik Skubal", "game": "Detroit Tigers @ Minnesota Twins",
                "bet": "Tarik Skubal — Retraits au baton Over 6.5",
                "line": 6.5, "date": "2026-09-02"}
        base.update(kw)
        return base

    def test_team_bet_goes_to_the_team_resolver(self):
        out = B.resolve_mlb_bet(self._bet(
            bet_type="team", market_type="moneyline", name="Boston Red Sox",
            game="Seattle Mariners @ Boston Red Sox", bet="Boston Red Sox — ML"))
        self.assertEqual(out, "W")
        self.assertEqual(self.calls[0][0], "team")

    def test_run_line_also_goes_to_the_team_resolver(self):
        B.resolve_mlb_bet(self._bet(
            bet_type="team", market_type="run_line_-1.5", name="Chicago Cubs",
            game="Milwaukee Brewers @ Chicago Cubs", bet="Chicago Cubs — -1.5"))
        self.assertEqual(self.calls[0][0], "team")

    def test_a_team_bet_never_reaches_the_prop_resolver(self):
        # La regression exacte: si elle repasse par les props, on recupere VOID.
        out = B.resolve_mlb_bet(self._bet(
            bet_type="team", market_type="moneyline", name="Boston Red Sox",
            game="Seattle Mariners @ Boston Red Sox", bet="Boston Red Sox — ML"))
        self.assertNotEqual(out, "VOID")
        self.assertNotIn("prop", [c[0] for c in self.calls])

    def test_player_prop_goes_to_the_prop_resolver(self):
        B.resolve_mlb_bet(self._bet())
        self.assertEqual(self.calls[0][0], "prop")
        self.assertEqual(self.calls[0][1], "Tarik Skubal")

    def test_date_falls_back_to_the_bet_own_date(self):
        B.resolve_mlb_bet(self._bet())
        self.assertEqual(self.calls[0][2], "2026-09-02")
        self.calls.clear()
        B.resolve_mlb_bet(self._bet(), "2026-08-31")
        self.assertEqual(self.calls[0][2], "2026-08-31")

    def test_line_is_recovered_from_the_label_when_absent(self):
        # Les vieux enregistrements n'ont pas toujours le champ `line`.
        B.resolve_mlb_bet(self._bet(line=0))
        self.assertEqual(self.calls[0][0], "prop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
