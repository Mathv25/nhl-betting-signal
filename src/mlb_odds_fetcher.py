"""
MLB Odds Fetcher - The Odds API
Marches: pitcher_strikeouts, batter_hits, batter_total_bases, batter_home_runs
Filtre: matchs du jour en heure de l'Est seulement
"""
import time
from datetime import datetime
from typing import Optional
import pytz

import odds_api

# BASE_URL vit dans odds_api (client partage).
SPORT     = "baseball_mlb"
BOOKMAKER = "draftkings"
REGIONS   = "us"

# Attention au nom du marche: sur The Odds API, le marche des retraits au baton
# d'un LANCEUR est `pitcher_strikeouts`. `player_strikeouts` n'existe pas pour
# baseball_mlb (`batter_strikeouts` existe, mais c'est le frappeur qui se fait
# retirer — pas ce qu'on veut). L'alias est accepte et traduit.
K_MARKET       = "pitcher_strikeouts"
MARKET_ALIASES = {"player_strikeouts": K_MARKET, "strikeouts": K_MARKET}

PROP_MARKETS = [
    "pitcher_strikeouts",
    "batter_hits",
    "batter_total_bases",
    "batter_home_runs",
    "batter_runs_scored",
]


class MLBOddsFetcher:

    def __init__(self, api_key: str):
        self.api_key   = api_key
        self.remaining = "?"
        self.client    = odds_api.get_client(api_key)
        self.prop_events_done = 0
        self.prop_events_skipped = []

    def _get(self, endpoint: str, params: dict, cost: int = 1) -> Optional[dict]:
        """Passe par le client partage: cache 30 min + garde-fou de quota."""
        data = self.client.get(endpoint, params, cost=cost)
        if self.client.remaining is not None:
            self.remaining = self.client.remaining
        return data

    def get_mlb_games(self) -> list:
        """Retourne les matchs MLB du jour (heure ET) avec leurs event_id."""
        # Pas de filtre région ici — on veut TOUS les matchs du jour.
        # Le filtre regions=eu s'applique seulement aux props (get_player_props).
        # L'endpoint /events ne coute aucun credit.
        data = self._get(f"sports/{SPORT}/events", {
            "oddsFormat": "decimal",
        }, cost=0)
        if not data:
            print("  Aucun match MLB trouve.")
            return []

        tz       = pytz.timezone("America/Toronto")
        today_et = datetime.now(tz).date()

        games = []
        for event in data:
            commence = event.get("commence_time", "")
            if commence:
                game_dt = datetime.fromisoformat(
                    commence.replace("Z", "+00:00")
                ).astimezone(tz)
                if game_dt.date() != today_et:
                    continue
            games.append({
                "event_id":      event.get("id", ""),
                "home_team":     event.get("home_team", ""),
                "away_team":     event.get("away_team", ""),
                "commence_time": commence,
            })

        print(f"  {len(games)} match(s) MLB ce soir (filtre date ET)")
        return games

    def get_game_odds(self, bookmakers: str = None) -> dict:
        """
        Moneyline (h2h) et run line (spreads) pour tous les matchs du jour,
        en UN SEUL appel — beaucoup moins cher en quota que le per-event.

        Retourne {event_id: {home_team, away_team, commence_time,
                             ml: {equipe: cote},
                             spreads: {equipe: {point: cote}}}}

        Pour le -1.5 on cherche `spreads[favori][-1.5]`.
        """
        params = {
            "regions":    REGIONS,
            "markets":    "h2h,spreads",
            "oddsFormat": "decimal",
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
        # 1 credit par (marche x region): h2h + spreads sur une region = 2.
        cost = 2 * len([r for r in REGIONS.split(",") if r.strip()])
        data = self._get(f"sports/{SPORT}/odds", params, cost=cost)
        if not data:
            print("  Aucune cote de match (h2h/spreads) recuperee.")
            return {}

        tz       = pytz.timezone("America/Toronto")
        today_et = datetime.now(tz).date()

        out = {}
        for event in data:
            commence = event.get("commence_time", "")
            if commence:
                game_dt = datetime.fromisoformat(
                    commence.replace("Z", "+00:00")
                ).astimezone(tz)
                if game_dt.date() != today_et:
                    continue

            ml, spreads = {}, {}
            ml_books = {}   # {book: {equipe: cote}} — necessaire pour devigger
                            # DANS un book: le no-vig calcule sur la meilleure
                            # cote de chaque cote melange deux marges et tord la
                            # probabilite vers le book le plus genereux.
            for bm in event.get("bookmakers", []):
                book = bm.get("key", "")
                for mkt in bm.get("markets", []):
                    kind = mkt.get("key")
                    for oc in mkt.get("outcomes", []):
                        team  = oc.get("name", "")
                        price = oc.get("price")
                        if not team or not price:
                            continue
                        if kind == "h2h":
                            # On garde la MEILLEURE cote disponible: la valeur
                            # se trouve chez le book le plus généreux.
                            if price > ml.get(team, 0):
                                ml[team] = price
                            if book:
                                ml_books.setdefault(book, {})[team] = price
                        elif kind == "spreads":
                            point = oc.get("point")
                            if point is None:
                                continue
                            cur = spreads.setdefault(team, {})
                            if price > cur.get(point, 0):
                                cur[point] = price

            if not ml:
                continue
            out[event.get("id", "")] = {
                # L'event_id doit voyager DANS l'entree: les consommateurs
                # (modele ML, capture CLV) recoivent une entree isolee et sans
                # lui ils ne peuvent plus interroger l'API pour ce match.
                "event_id":      event.get("id", ""),
                "home_team":     event.get("home_team", ""),
                "away_team":     event.get("away_team", ""),
                "commence_time": commence,
                "ml":            ml,
                "ml_books":      ml_books,
                "spreads":       spreads,
            }

        print(f"  Cotes de match recuperees pour {len(out)} match(s) "
              f"(quota restant: {self.remaining})")
        return out

    def get_player_props(self, event_id: str, market: str) -> list:
        """
        Props joueurs d'un match, agregees sur TOUS les books disponibles.

        Change par rapport a la version DraftKings-seulement:
          - plus de filtre `bookmakers`, et regions us+eu par defaut, donc
            Pinnacle est dans la reponse quand il cote le marche;
          - `over_odds` est la MEILLEURE cote Over du marche (c'est chez ce
            book qu'on mise, donc c'est elle qui fixe l'EV), avec le nom du
            book dans `over_book`;
          - `over_implied` est la probabilite NO-VIG de reference (Pinnacle si
            dispo, sinon mediane des books), plus la prob brute 1/cote qui
            surestimait le marche de 2 a 5 points;
          - `books` garde le detail par book pour l'affichage.

        Cout: 10 credits par (marche x region). Un appel en us+eu = 20 credits,
        d'ou le plafond ODDS_MAX_PROP_EVENTS par execution.
        """
        market = MARKET_ALIASES.get(market, market)

        if not odds_api.props_enabled() or not odds_api.props_window_open():
            return []
        if not self.client.healthy:
            # Cle absente/refusee ou quota epuise: le calculateur manuel du
            # dashboard prend le relais.
            return []

        regs   = odds_api.regions()
        n_regs = len([r for r in regs.split(",") if r.strip()])
        cost   = odds_api.COST_PER_MARKET_REGION_PROP * max(n_regs, 1)

        params = {
            "regions":    regs,
            "markets":    market,
            "oddsFormat": "decimal",
        }
        # Le plafond compte les EVENEMENTS: plusieurs marches sur un evenement
        # deja paye passent par le cache.
        cache_hit = self.client._cache_read(self.client._key(
            f"sports/{SPORT}/events/{event_id}/odds", params)) is not None
        if not cache_hit:
            new_event = event_id not in getattr(self, "_events_seen", set())
            if new_event and self.prop_events_done >= odds_api.max_prop_events():
                self.prop_events_skipped.append(event_id)
                print(f"  [Odds API] props non demandees pour {event_id[:8]}: "
                      f"plafond ODDS_MAX_PROP_EVENTS={odds_api.max_prop_events()} atteint")
                return []
            # Rythme mensuel: refuser plutot que d'epuiser le quota du mois.
            if not self.client.can_spend_props(cost):
                if event_id not in self.prop_events_skipped:
                    self.prop_events_skipped.append(event_id)
                print(f"  [Odds API] props non demandees pour {event_id[:8]}: budget du jour "
                      f"atteint ({self.client.spent_today() + self.client.prop_credits}/"
                      f"{self.client.day_budget()} credits) — "
                      f"{len(self.prop_events_skipped)} evenement(s) ignore(s)")
                return []
            self.client.note_props(cost)
            if new_event:
                self._events_seen = getattr(self, "_events_seen", set())
                self._events_seen.add(event_id)
                self.prop_events_done += 1
            time.sleep(0.5)

        data = self._get(f"sports/{SPORT}/events/{event_id}/odds", params, cost=cost)
        if not data:
            return []

        # (joueur, ligne) -> [{book, over_odds, under_odds}]
        by_player_line: dict = {}
        for bm in data.get("bookmakers", []):
            book = bm.get("key", "")
            for mkt in bm.get("markets", []):
                if mkt.get("key") != market:
                    continue
                sides: dict = {}
                for outcome in mkt.get("outcomes", []):
                    player = outcome.get("description", "")
                    side   = outcome.get("name", "")
                    line   = outcome.get("point", 0)
                    price  = outcome.get("price")
                    if not player or not side or not line or not price:
                        continue
                    sides.setdefault((player, line), {})[side] = price
                for (player, line), faces in sides.items():
                    if "Over" not in faces:
                        continue
                    by_player_line.setdefault((player, line), []).append({
                        "book":       book,
                        "over_odds":  faces.get("Over"),
                        "under_odds": faces.get("Under"),
                    })

        props = []
        for (player, line), books in sorted(by_player_line.items()):
            agg = odds_api.summarize_two_way(books)
            if not agg["best_over_odds"]:
                continue
            props.append({
                "player":          player,
                "market":          market,
                "line":            line,
                # Rétrocompat: mêmes clés qu'avant, meilleur contenu.
                "over_odds":       agg["best_over_odds"],
                "over_implied":    agg["baseline_prob"],
                "under_odds":      agg["best_under_odds"] or 2.0,
                "under_implied":   round(100 - agg["baseline_prob"], 2),
                # Nouveau.
                "over_book":       agg["best_over_book"],
                "baseline_source": agg["baseline_source"],
                "n_books":         agg["n_books"],
                "n_novig":         agg["n_novig"],
                "books":           agg["books"],
            })

        if props:
            pin = sum(1 for p in props if p["baseline_source"] == odds_api.PINNACLE)
            print(f"  [Odds API] {market}: {len(props)} ligne(s) sur "
                  f"{max(p['n_books'] for p in props)} book(s) max, "
                  f"{pin} avec baseline Pinnacle (quota {self.remaining})")
        return props
