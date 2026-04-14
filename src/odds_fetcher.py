"""
Odds Fetcher - The Odds API -> DraftKings
Marches: h2h (moneyline), spreads (puck line), totals + player props NHL
"""

import requests
import time
from typing import Optional

BASE_URL  = "https://api.the-odds-api.com/v4"
SPORT     = "icehockey_nhl"
BOOKMAKER = "draftkings"
FMT_ODDS  = "decimal"
FMT_DATE  = "iso"
MAIN_MARKETS = "h2h,spreads,totals"

# Ordre de priorite: bet365 (UK) en premier car c'est la que l'utilisateur bet,
# puis DraftKings (US) en fallback si bet365 n'a pas encore poste les cotes.
BOOKMAKER_PRIORITY = [
    {"key": "bet365",       "region": "uk"},
    {"key": "draftkings",   "region": "us"},
    {"key": "fanduel",      "region": "us"},
    {"key": "betmgm",       "region": "us"},
]

# Marches props NHL disponibles sur The Odds API
NHL_PROP_MARKETS = [
    "player_shots_on_goal",
    "player_points",
    "player_goals",
]


class OddsFetcher:

    def __init__(self, api_key: str):
        self.api_key   = api_key
        self.remaining = "?"
        self.used      = "?"

    def _get(self, endpoint: str, params: dict) -> Optional[dict]:
        params["apiKey"] = self.api_key
        try:
            r = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
            self.remaining = r.headers.get("x-requests-remaining", "?")
            self.used      = r.headers.get("x-requests-used", "?")
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            print(f"  HTTP {e.response.status_code}: {endpoint}")
            return None
        except Exception as e:
            print(f"  Erreur reseau: {e}")
            return None

    def get_nhl_games_b365(self) -> list:
        """Fetch les cotes NHL.
        Essaie bet365 (UK) en priorite, puis DK/FD en fallback si pas encore disponible."""
        for entry in BOOKMAKER_PRIORITY:
            book   = entry["key"]
            region = entry["region"]
            print(f"  -> Tentative {book} ({region}): Moneyline + Puck Line + Totals...")
            raw = self._get(f"sports/{SPORT}/odds", {
                "regions":    region,
                "markets":    MAIN_MARKETS,
                "bookmakers": book,
                "oddsFormat": FMT_ODDS,
                "dateFormat": FMT_DATE,
            })
            print(f"  -> Requetes API restantes: {self.remaining} | utilisees: {self.used}")

            if not raw:
                print(f"  {book}: aucun match disponible.")
                continue

            games = []
            for event in raw:
                game = self._parse_event_for_book(event, book)
                if game:
                    game["markets"]["player_props"] = []
                    game["removed_props"] = []
                    games.append(game)

            if games:
                print(f"  {len(games)} match(s) avec cotes {book} ({region})")
                return games
            print(f"  {book}: reponse recue mais aucun match parse.")

        print("  Aucun match trouve sur tous les bookmakers.")
        return []

    def get_nhl_player_props(self, event_id: str, bookmaker: str = "bet365") -> dict:
        """Fetche les props joueurs NHL pour un match (tous les marches en un seul appel).
        Retourne dict {market_key: [{player, line, over_odds, over_implied, under_odds, under_implied}]}
        """
        time.sleep(0.5)
        region = next((e["region"] for e in BOOKMAKER_PRIORITY if e["key"] == bookmaker), "us")
        data = self._get(f"sports/{SPORT}/events/{event_id}/odds", {
            "regions":    region,
            "markets":    ",".join(NHL_PROP_MARKETS),
            "oddsFormat": FMT_ODDS,
            "bookmakers": bookmaker,
        })
        if not data:
            return {}

        result = {}
        for bm in data.get("bookmakers", []):
            if bm.get("key") != bookmaker:
                continue
            for mkt in bm.get("markets", []):
                market_key = mkt.get("key")
                if market_key not in NHL_PROP_MARKETS:
                    continue

                by_player = {}
                for outcome in mkt.get("outcomes", []):
                    player = outcome.get("description", "")
                    side   = outcome.get("name", "")
                    if not player or not side:
                        continue
                    if player not in by_player:
                        by_player[player] = {}
                    price = outcome.get("price", 2.0)
                    by_player[player][side] = {
                        "odds":    price,
                        "line":    outcome.get("point", 0),
                        "implied": round(1 / max(price, 1.01) * 100, 1),
                    }

                props = []
                for player, sides in by_player.items():
                    over  = sides.get("Over", {})
                    under = sides.get("Under", {})
                    if not over or not over.get("line"):
                        continue
                    props.append({
                        "player":        player,
                        "market":        market_key,
                        "line":          over["line"],
                        "over_odds":     over["odds"],
                        "over_implied":  over["implied"],
                        "under_odds":    under.get("odds", 2.0),
                        "under_implied": under.get("implied", 52.4),
                    })

                if props:
                    result[market_key] = props

        return result

    def _parse_event_for_book(self, event: dict, book: str) -> Optional[dict]:
        bk = next(
            (b for b in event.get("bookmakers", []) if b["key"] == book),
            None
        )
        if not bk:
            return None

        game = {
            "id":            event["id"],
            "home_team":     event["home_team"],
            "away_team":     event["away_team"],
            "commence_time": event["commence_time"],
            "bookmaker":     book,
            "markets":       {},
        }

        for market in bk.get("markets", []):
            k = market["key"]
            if k == "h2h":
                game["markets"]["moneyline"] = self._parse_h2h(market, game)
            elif k == "spreads":
                game["markets"]["puck_line"] = self._parse_spreads(market, game)
            elif k == "totals":
                game["markets"]["totals"] = self._parse_totals(market)

        return game

    def _parse_event(self, event: dict) -> Optional[dict]:
        return self._parse_event_for_book(event, BOOKMAKER)

    def _parse_h2h(self, market, game):
        out = {}
        for o in market.get("outcomes", []):
            side = "home" if o["name"] == game["home_team"] else "away"
            out[side] = {
                "team":         o["name"],
                "odds_decimal": round(o["price"], 3),
                "implied_prob": round(1 / o["price"] * 100, 2),
            }
        return out

    def _parse_spreads(self, market, game):
        out = {}
        for o in market.get("outcomes", []):
            side = "home" if o["name"] == game["home_team"] else "away"
            out[side] = {
                "team":         o["name"],
                "spread":       o.get("point", -1.5),
                "odds_decimal": round(o["price"], 3),
                "implied_prob": round(1 / o["price"] * 100, 2),
            }
        return out

    def _parse_totals(self, market):
        out = {}
        for o in market.get("outcomes", []):
            d = o["name"].lower()
            out[d] = {
                "line":         o.get("point"),
                "odds_decimal": round(o["price"], 3),
                "implied_prob": round(1 / o["price"] * 100, 2),
            }
        return out
