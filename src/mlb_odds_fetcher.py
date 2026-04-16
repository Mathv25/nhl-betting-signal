"""
MLB Odds Fetcher - The Odds API
Marches: pitcher_strikeouts, batter_hits, batter_total_bases, batter_home_runs
Filtre: matchs du jour en heure de l'Est seulement
"""
import requests
import time
from datetime import datetime
from typing import Optional
import pytz

BASE_URL  = "https://api.the-odds-api.com/v4"
SPORT     = "baseball_mlb"
BOOKMAKER = "draftkings"
REGIONS   = "us"

PROP_MARKETS = [
    "pitcher_strikeouts",
    "batter_hits",
    "batter_total_bases",
    "batter_home_runs",
]


class MLBOddsFetcher:

    def __init__(self, api_key: str):
        self.api_key   = api_key
        self.remaining = "?"

    def _get(self, endpoint: str, params: dict) -> Optional[dict]:
        params["apiKey"] = self.api_key
        try:
            r = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
            self.remaining = r.headers.get("x-requests-remaining", "?")
            if r.status_code == 200:
                return r.json()
            if r.status_code not in (422, 404):
                print(f"  MLB Odds API {r.status_code}: {endpoint}")
            return None
        except Exception as e:
            print(f"  MLB Odds API erreur: {e}")
            return None

    def get_mlb_games(self) -> list:
        """Retourne les matchs MLB du jour (heure ET) avec leurs event_id."""
        data = self._get(f"sports/{SPORT}/events", {
            "regions":    REGIONS,
            "oddsFormat": "decimal",
        })
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

    def get_player_props(self, event_id: str, market: str) -> list:
        """Retourne les props joueurs pour un match et un marche donnes."""
        time.sleep(0.5)
        data = self._get(f"sports/{SPORT}/events/{event_id}/odds", {
            "regions":    REGIONS,
            "markets":    market,
            "oddsFormat": "decimal",
            "bookmakers": BOOKMAKER,
        })
        if not data:
            return []

        props = []
        for bm in data.get("bookmakers", []):
            if bm.get("key") != BOOKMAKER:
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

        return props
