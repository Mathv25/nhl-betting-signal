"""
Tests des props joueurs NFL (src/nfl_props.py).

Aucun appel reseau: un faux client compte les requetes et renvoie des reponses
en dur. Ce qui est verifie en priorite, dans l'ordre des risques:

  1. le plafond de requetes — c'est la contrainte qui protege le quota du MLB
     et du NHL, et un depassement ne se voit qu'a la facture;
  2. le filtre du total, qui decide ou l'on depense;
  3. le devig, qui doit sommer a 1 comme partout ailleurs;
  4. la detection des ecarts de ligne (middle), invisible dans les probabilites.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import odds_api           # noqa: E402
import nfl_props as P     # noqa: E402


class FakeClient:
    """Client Odds API en dur: compte les requetes, ne parle a personne."""

    def __init__(self, payload=None):
        self.payload = payload
        self.calls   = []
        self.healthy = True
        self.remaining = 10000
        self._usage  = {"date": "2026-09-13", "remaining_at_start": 10000}
        self.persisted = 0

    def get(self, endpoint, params, cost=1):
        self.calls.append((endpoint, params.get("markets")))
        return self.payload

    def usage(self):
        return self._usage

    def persist_usage(self):
        self.persisted += 1


def prop_payload(joueur="Puka Nacua", lignes=None, market="player_reception_yds"):
    """lignes = {book: (point, cote_over, cote_under)}"""
    lignes = lignes or {"pinnacle": (67.5, 1.91, 1.95),
                        "draftkings": (67.5, 1.95, 1.87),
                        "fanduel": (67.5, 1.93, 1.90)}
    return {"bookmakers": [
        {"key": bk, "markets": [{"key": market, "outcomes": [
            {"name": "Over",  "description": joueur, "point": pt, "price": ov},
            {"name": "Under", "description": joueur, "point": pt, "price": un}]}]}
        for bk, (pt, ov, un) in lignes.items()]}


def game(event_id="e1", total=48.5, home="Los Angeles Rams", away="San Francisco 49ers"):
    return {"event_id": event_id, "home_team": home, "away_team": away,
            "commence": "2026-09-13T17:00:00Z",
            "markets": [{"market": "nfl_total", "point": total, "n_books": 12,
                         "prob_a": 50.0, "prob_b": 50.0, "source": "pinnacle"}]}


class TestGameSelection(unittest.TestCase):
    """
    Ou l'on depense les requetes. Les matchs a haut pointage concentrent le
    volume de verges, donc la valeur; les autres ne meritent pas une requete.
    """

    def test_low_scoring_games_are_skipped(self):
        games = [game("a", 41.0), game("b", 46.5), game("c", 47.0), game("d", 52.0)]
        gardes = [g["event_id"] for g in P.select_games(games)]
        self.assertEqual(gardes, ["d", "c"])          # 47.0 passe, 46.5 non

    def test_highest_totals_come_first(self):
        games = [game("a", 48.0), game("b", 55.0), game("c", 50.0)]
        self.assertEqual([g["event_id"] for g in P.select_games(games)],
                         ["b", "c", "a"])

    def test_never_more_than_the_cap(self):
        games = [game(f"g{i}", 50 + i) for i in range(12)]
        self.assertEqual(len(P.select_games(games)), P.max_games())

    def test_threshold_is_configurable(self):
        os.environ["NFL_PROPS_MIN_TOTAL"] = "52"
        try:
            self.assertEqual(P.min_total(), 52.0)
            self.assertEqual(len(P.select_games([game("a", 48.0)])), 0)
        finally:
            os.environ.pop("NFL_PROPS_MIN_TOTAL", None)

    def test_the_main_total_line_wins(self):
        # Deux lignes de total: on retient celle qu'appuient le plus de books.
        g = game("a", 44.0)
        g["markets"].append({"market": "nfl_total", "point": 47.5, "n_books": 20})
        self.assertEqual(P.game_total(g), 47.5)

    def test_a_game_without_total_is_skipped(self):
        g = game("a"); g["markets"] = []
        self.assertIsNone(P.game_total(g))
        self.assertEqual(P.select_games([g]), [])


class TestImminentOnly(unittest.TestCase):
    """
    Mode des matchs de semaine: un jeudi soir ne tombe dans aucune fenetre
    hebdomadaire, et scanner tout le calendrier pour lui depenserait des
    requetes sur des lignes de dimanche encore larges.
    """

    JEUDI = datetime(2026, 9, 10, 14)     # 14h ET, coup d'envoi a 20h35

    def _slate(self):
        ce_soir = game("tnf", 48.0)
        ce_soir["commence"] = "2026-09-11T00:35:00Z"      # jeudi 20h35 ET
        dimanche = game("sun", 52.0)
        dimanche["commence"] = "2026-09-13T17:00:00Z"
        return [ce_soir, dimanche]

    def test_only_the_imminent_game_is_kept(self):
        gardes = P.select_games(self._slate(), within_hours=12, when=self.JEUDI)
        self.assertEqual([g["event_id"] for g in gardes], ["tnf"])

    def test_without_the_option_everything_qualifies(self):
        gardes = P.select_games(self._slate(), when=self.JEUDI)
        self.assertEqual(len(gardes), 2)

    def test_a_game_already_played_is_dropped(self):
        vieux = game("hier", 50.0)
        vieux["commence"] = "2026-09-09T00:20:00Z"
        self.assertEqual(P.select_games([vieux], within_hours=12, when=self.JEUDI), [])

    def test_the_total_filter_still_applies(self):
        faible = game("tnf", 44.0)
        faible["commence"] = "2026-09-11T00:35:00Z"
        self.assertEqual(P.select_games([faible], within_hours=12, when=self.JEUDI), [])


class TestRequestBudget(unittest.TestCase):
    """
    Le plafond hebdomadaire. Un endpoint props coute une requete par match et
    par marche: trois marches sur seize matchs feraient 48 requetes par
    semaine, en concurrence avec le MLB et le NHL qui jouent tous les jours.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nflprops")
        os.environ["NFL_PROPS_PATH"] = os.path.join(self.dir, "props.json")
        os.environ["BETS_PATH"] = os.path.join(self.dir, "bets.json")

    def tearDown(self):
        for k in ("NFL_PROPS_PATH", "BETS_PATH", "NFL_PROPS_MAX_REQUESTS"):
            os.environ.pop(k, None)

    def _run(self, n_games, payload=None):
        client = FakeClient(payload if payload is not None else prop_payload())
        orig = odds_api.get_client
        odds_api.get_client = lambda key=None: client
        try:
            slate = {"games": [game(f"g{i}", 50.0) for i in range(n_games)]}
            etat = P.run("cle", slate, force=True)
        finally:
            odds_api.get_client = orig
        return client, etat

    def test_requests_stop_at_the_cap(self):
        os.environ["NFL_PROPS_MAX_REQUESTS"] = "4"
        client, etat = self._run(6)
        self.assertEqual(len(client.calls), 4)
        self.assertEqual(etat["requests"], 4)

    def test_priority_markets_are_covered_first(self):
        # Budget pour 2 requetes: les deux doivent porter sur le PREMIER
        # marche de la liste, pas sur deux marches d'un meme match.
        os.environ["NFL_PROPS_MAX_REQUESTS"] = "2"
        client, _ = self._run(4)
        self.assertEqual({m for _, m in client.calls}, {"player_reception_yds"})

    def test_the_cap_spans_runs_within_a_week(self):
        # Le compteur vit dans odds_usage.json: un second run de la meme
        # semaine ne repart pas de zero.
        os.environ["NFL_PROPS_MAX_REQUESTS"] = "3"
        client, _ = self._run(3)
        self.assertEqual(len(client.calls), 3)
        semaine = client.usage()["nfl_props"]["week"]
        self.assertEqual(client.usage()["nfl_props"]["requests"], 3)
        self.assertEqual(P.remaining_requests(client, semaine), 0)

    def test_a_new_week_resets_the_counter(self):
        client = FakeClient()
        client._usage["nfl_props"] = {"week": "2026-09-01", "requests": 40}
        self.assertEqual(P.remaining_requests(client, "2026-09-08"), P.max_requests())

    def test_full_budget_covers_every_market(self):
        client, etat = self._run(2)
        self.assertEqual(len(client.calls), 6)        # 2 matchs x 3 marches
        self.assertEqual({m for _, m in client.calls}, set(P.MARKETS))

    def test_usage_is_persisted(self):
        client, _ = self._run(1)
        self.assertGreaterEqual(client.persisted, 1)


class TestDevigAndSignals(unittest.TestCase):

    def test_over_under_probabilities_sum_to_one(self):
        joueurs = P.parse_market(prop_payload(), "player_reception_yds")
        import nfl_analyzer as NFL
        par_book = {bk: {"Over": c["Over"], "Under": c["Under"]}
                    for bk, c in joueurs["Puka Nacua"][67.5].items()}
        pair = NFL.devig_pair(par_book, "Over", "Under")
        self.assertAlmostEqual(pair["Over"] + pair["Under"], 1.0, places=9)
        self.assertEqual(pair["source"], "pinnacle")

    def test_a_generous_book_becomes_a_signal(self):
        # Pinnacle a 1.91/1.95 fixe la reference; un book paie 2.20 le Over.
        lignes = {"pinnacle": (67.5, 1.91, 1.95), "draftkings": (67.5, 2.20, 1.75),
                  "fanduel": (67.5, 1.92, 1.94)}
        joueurs = P.parse_market(prop_payload(lignes=lignes), "player_reception_yds")
        sigs = P.analyze_player("Puka Nacua", joueurs["Puka Nacua"],
                                "player_reception_yds", game())
        cotes = [s for s in sigs if s["type"] == "cote"]
        self.assertEqual(len(cotes), 1)
        self.assertEqual(cotes[0]["book"], "draftkings")
        self.assertEqual(cotes[0]["side"], "Over")
        self.assertGreater(cotes[0]["edge_pct"], 3.0)

    def test_an_aligned_market_produces_nothing(self):
        joueurs = P.parse_market(prop_payload(), "player_reception_yds")
        sigs = P.analyze_player("Puka Nacua", joueurs["Puka Nacua"],
                                "player_reception_yds", game())
        self.assertEqual([s for s in sigs if s["type"] == "cote"], [])

    def test_a_thin_market_is_refused(self):
        lignes = {"pinnacle": (67.5, 1.91, 1.95), "dk": (67.5, 2.30, 1.70)}
        joueurs = P.parse_market(prop_payload(lignes=lignes), "player_reception_yds")
        sigs = P.analyze_player("Puka Nacua", joueurs["Puka Nacua"],
                                "player_reception_yds", game())
        self.assertEqual([s for s in sigs if s["type"] == "cote"], [])


class TestLineDiscrepancy(unittest.TestCase):
    """
    L'ecart de ligne n'apparait dans aucune probabilite: 67.5 chez l'un et
    72.5 chez l'autre se voit seulement en comparant les lignes.
    """

    def _sigs(self, lignes):
        joueurs = P.parse_market(prop_payload(lignes=lignes), "player_reception_yds")
        return P.analyze_player("Puka Nacua", joueurs["Puka Nacua"],
                                "player_reception_yds", game())

    def test_a_middle_between_two_books_is_detected(self):
        lignes = {"draftkings": (67.5, 1.91, 1.95), "pinnacle": (72.5, 1.90, 1.92),
                  "fanduel": (70.5, 1.90, 1.92)}
        m = [s for s in self._sigs(lignes) if s["type"] == "ligne"]
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["over"]["ligne"], 67.5)     # Over: la plus basse
        self.assertEqual(m[0]["over"]["book"], "draftkings")
        self.assertEqual(m[0]["under"]["ligne"], 72.5)    # Under: la plus haute
        self.assertEqual(m[0]["under"]["book"], "pinnacle")
        self.assertEqual(m[0]["fenetre"], 5.0)

    def test_one_book_alone_is_never_a_middle(self):
        """
        Cas reel du 10 septembre. Bovada publie une echelle de lignes
        alternatives correctement cotees; en prendre les deux extremites
        fabriquait une fenetre de 60 verges qui n'existe pas — le book accepte
        volontiers les deux cotes a ces prix.
        """
        echelle = {f"bovada@{pt}": (pt, 1.41, 1.43)
                   for pt in (232.5, 242.5, 252.5, 262.5, 272.5, 282.5, 292.5)}
        # Toutes les offres viennent du meme book: on renomme les cles apres coup.
        par_ligne = {}
        for pt in (232.5, 242.5, 252.5, 262.5, 272.5, 282.5, 292.5):
            par_ligne[pt] = {"bovada": {"Over": 1.41, "Under": 1.43}}
        sigs = P.analyze_player("Matthew Stafford", par_ligne,
                                "player_pass_yds", game())
        self.assertEqual([s for s in sigs if s["type"] == "ligne"], [])

    def test_the_main_line_of_each_book_is_compared(self):
        """
        Meme cas, avec les vrais books autour. La fenetre doit etre l'ecart
        REEL entre books (258.5 chez fanduel, 263.5 chez betmgm), pas
        l'amplitude de l'echelle de bovada.
        """
        par_ligne = {}
        for pt in (232.5, 242.5, 252.5, 262.5, 272.5, 282.5, 292.5):
            par_ligne.setdefault(pt, {})["bovada"] = {"Over": 1.41, "Under": 1.43}
        for bk, pt in (("betmgm", 263.5), ("pinnacle", 263.5), ("draftkings", 262.5),
                       ("fanduel", 258.5), ("betrivers", 261.5)):
            par_ligne.setdefault(pt, {})[bk] = {"Over": 1.90, "Under": 1.92}
        m = [s for s in P.analyze_player("Matthew Stafford", par_ligne,
                                         "player_pass_yds", game())
             if s["type"] == "ligne"]
        self.assertEqual(len(m), 1)
        self.assertEqual(m[0]["fenetre"], 5.0)
        self.assertEqual(m[0]["over"]["ligne"], 258.5)
        self.assertEqual(m[0]["over"]["book"], "fanduel")
        self.assertEqual(m[0]["under"]["ligne"], 263.5)
        self.assertNotEqual(m[0]["under"]["book"], m[0]["over"]["book"])

    def test_a_single_line_has_no_middle(self):
        self.assertEqual([s for s in self._sigs(
            {"a": (67.5, 1.91, 1.95), "b": (67.5, 1.90, 1.92),
             "c": (67.5, 1.92, 1.93)}) if s["type"] == "ligne"], [])


class TestCadence(unittest.TestCase):

    def test_only_sunday_morning(self):
        self.assertTrue(P.should_run(datetime(2026, 9, 13, 9))[0])
        self.assertTrue(P.should_run(datetime(2026, 9, 13, 11, 59))[0])
        self.assertFalse(P.should_run(datetime(2026, 9, 13, 8))[0])
        self.assertFalse(P.should_run(datetime(2026, 9, 13, 12))[0])

    def test_tuesday_is_refused(self):
        # Les lignes d'ouverture sont larges et bougent trop.
        self.assertFalse(P.should_run(datetime(2026, 9, 8, 10))[0])

    def test_no_other_day_opens(self):
        for d in range(7):
            if d == 6:
                continue
            self.assertFalse(P.should_run(datetime(2026, 9, 7 + d, 10))[0])


class TestPaperTracking(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nflprops")
        os.environ["BETS_PATH"] = os.path.join(self.dir, "bets.json")

    def tearDown(self):
        os.environ.pop("BETS_PATH", None)

    def _sig(self):
        return {"type": "cote", "joueur": "Puka Nacua", "market": "player_reception_yds",
                "selection": "Puka Nacua Over 67.5", "side": "Over", "ligne": 67.5,
                "prob": 52.0, "odds": 2.20, "book": "draftkings", "edge_pct": 14.4,
                "source": "pinnacle", "n_books": 3, "game": "SF @ LAR"}

    def test_a_signal_is_logged_as_paper(self):
        import bet_tracker as bt
        self.assertEqual(P.log_paper([self._sig()], "2026-09-08"), 1)
        bet = bt.load()["bets"][0]
        self.assertTrue(bet["paper"])
        self.assertEqual(bet["market"], "nfl_prop_reception_yds")
        self.assertEqual(bet["stake"], 1.0)

    def test_logging_is_idempotent(self):
        P.log_paper([self._sig()], "2026-09-08")
        self.assertEqual(P.log_paper([self._sig()], "2026-09-08"), 0)

    def test_middles_are_not_logged(self):
        # Deux paris a deux prix chez deux books: le tracker, concu pour un
        # pari et une cote, les representerait mal.
        milieu = {**self._sig(), "type": "ligne"}
        self.assertEqual(P.log_paper([milieu], "2026-09-08"), 0)

    def test_closing_is_captured(self):
        import bet_tracker as bt
        P.log_paper([self._sig()], "2026-09-08")
        self.assertEqual(P.capture_closing([self._sig()], "2026-09-08"), 1)
        self.assertEqual(bt.load()["bets"][0]["closing_odds"], 2.20)
        # Un pari deja ferme n'est pas reecrit.
        self.assertEqual(P.capture_closing([self._sig()], "2026-09-08"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
