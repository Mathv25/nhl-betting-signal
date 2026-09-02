"""
NBA Odds Fetcher - The Odds API
Marches: player_points, player_rebounds, player_assists, player_threes
"""
import time
from datetime import datetime, timezone
from typing import Optional
import pytz

import odds_api

# BASE_URL vit dans odds_api (client partage).
SPORT     = "basketball_nba"

# Ordre de priorité: bet365 EU en premier, puis DraftKings US en fallback
BOOKMAKER_PRIORITY = [
    {"key": "bet365",     "region": "eu"},
    {"key": "draftkings", "region": "us"},
    {"key": "fanduel",    "region": "us"},
]

PROP_MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
]


class NBAOddsFetcher:

    def __init__(self, api_key: str):
        self.api_key   = api_key
        self.remaining = "?"
        self.client    = odds_api.get_client(api_key)
        self.prop_events_done = 0

    def _get(self, endpoint: str, params: dict, cost: int = 1) -> Optional[list]:
        """Passe par le client partage: cache + comptage et garde-fou de quota."""
        data = self.client.get(endpoint, params, cost=cost)
        if self.client.remaining is not None:
            self.remaining = self.client.remaining
        return data

    @staticmethod
    def _n_regions() -> int:
        return max(len([r for r in odds_api.regions().split(",") if r.strip()]), 1)

    def get_nba_games(self) -> list:
        """Retourne les matchs NBA du jour avec leurs event_id."""
        # Pas de filtre région — on veut tous les matchs du jour.
        # regions=eu s'applique seulement pour les props.
        # L'endpoint /events est gratuit (aucun credit).
        data = self._get(f"sports/{SPORT}/events", {
            "oddsFormat": "decimal",
        }, cost=0)
        if not data:
            print("  Aucun match NBA trouve.")
            return []

        tz = pytz.timezone("America/Toronto")
        today_et = datetime.now(tz).date()

        games = []
        for event in data:
            commence = event.get("commence_time", "")
            if commence:
                game_dt = datetime.fromisoformat(commence.replace("Z", "+00:00")).astimezone(tz)
                if game_dt.date() != today_et:
                    continue
            games.append({
                "event_id":      event.get("id", ""),
                "home_team":     event.get("home_team", ""),
                "away_team":     event.get("away_team", ""),
                "commence_time": commence,
            })

        print(f"  {len(games)} match(s) NBA ce soir (filtre date ET)")
        return games

    def get_player_props(self, event_id: str, market: str) -> list:
        """
        Retourne les props joueurs pour un match et un marche.
        Essaie bet365 EU en premier, puis DraftKings/FanDuel US en fallback.
        Retourne: liste de dicts {player, market, line, over_odds, over_implied, under_odds}
        """
        if not odds_api.props_enabled() or not odds_api.props_window_open() or not self.client.healthy:
            return []

        # 10 credits par (marche x region). L'ancienne cascade relancait un
        # appel complet par book: jusqu'a 4 x 10 credits pour un seul marche
        # d'un seul match. Un appel, tous les books, plafond d'evenements.
        params = {
            "regions":    odds_api.regions(),
            "markets":    market,
            "oddsFormat": "decimal",
        }
        cost      = odds_api.COST_PER_MARKET_REGION_PROP * self._n_regions()
        endpoint  = f"sports/{SPORT}/events/{event_id}/odds"
        cache_hit = self.client._cache_read(self.client._key(endpoint, params)) is not None
        if not cache_hit:
            new_event = event_id not in getattr(self, "_events_seen", set())
            if new_event and self.prop_events_done >= odds_api.max_prop_events():
                print(f"    [NBA Props] plafond ODDS_MAX_PROP_EVENTS="
                      f"{odds_api.max_prop_events()} atteint — {event_id[:8]} ignore")
                return []
            if not self.client.can_spend_props(cost):
                print(f"    [NBA Props] budget du jour atteint "
                      f"({self.client.spent_today() + self.client.prop_credits}/"
                      f"{self.client.day_budget()} credits) — {event_id[:8]} ignore")
                return []
            self.client.note_props(cost)
            if new_event:
                self._events_seen = getattr(self, "_events_seen", set())
                self._events_seen.add(event_id)
                self.prop_events_done += 1
            time.sleep(0.5)

        data = self._get(endpoint, params, cost=cost)
        if not data:
            return []

        # Un book a la fois, dans l'ordre de priorite, sur la MEME reponse.
        for entry in BOOKMAKER_PRIORITY:
            book   = entry["key"]
            region = entry["region"]

            props = []
            for bm in data.get("bookmakers", []):
                if bm.get("key") != book:
                    continue
                for mkt in bm.get("markets", []):
                    if mkt.get("key") != market:
                        continue

                    by_player = {}
                    for outcome in mkt.get("outcomes", []):
                        player = outcome.get("description", "")
                        side   = outcome.get("name", "")
                        if not player or not side:
                            continue
                        if player not in by_player:
                            by_player[player] = {}
                        by_player[player][side] = {
                            "odds":    outcome.get("price", 2.0),
                            "line":    outcome.get("point", 0),
                            "implied": round(1 / max(outcome.get("price", 2.0), 1.01) * 100, 1),
                        }

                    for player, sides in by_player.items():
                        over  = sides.get("Over", {})
                        under = sides.get("Under", {})
                        if not over or not over.get("line"):
                            continue
                        props.append({
                            "player":        player,
                            "market":        market,
                            "line":          over["line"],
                            "over_odds":     over["odds"],
                            "over_implied":  over["implied"],
                            "under_odds":    under.get("odds", 2.0),
                            "under_implied": under.get("implied", 52.4),
                        })

            if props:
                if book != "bet365":
                    print(f"    [NBA Props] bet365 vide — utilise {book} ({region})")
                return props

        return []
