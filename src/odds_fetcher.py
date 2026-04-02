"""
Odds Fetcher - The Odds API -> DraftKings
Marches: h2h (moneyline), spreads (puck line), totals
Props et periodes retires (non disponibles plan gratuit)
"""

import requests
import time
from typing import Optional

BASE_URL  = "https://api.the-odds-api.com/v4"
SPORT     = "icehockey_nhl"
BOOKMAKER = "draftkings"
REGIONS   = "us"
FMT_ODDS  = "decimal"
FMT_DATE  = "iso"
MAIN_MARKETS = "h2h,spreads,totals"


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
        print("  -> Moneyline + Puck Line + Totals...")
        raw = self._get(f"sports/{SPORT}/odds", {
            "regions":    REGIONS,
            "markets":    MAIN_MARKETS,
            "bookmakers": BOOKMAKER,
            "oddsFormat": FMT_ODDS,
            "dateFormat": FMT_DATE,
        })

        if not raw:
            return []

        print(f"  -> Requetes API restantes: {self.remaining} | utilisees: {self.used}")

        games = []
        for event in raw:
            game = self._parse_event(event)
            if game:
                game["markets"]["player_props"] = []
                game["removed_props"] = []
                games.append(game)

        print(f"  {len(games)} match(s) avec cotes DraftKings")
        return games

    def _parse_event(self, event: dict) -> Optional[dict]:
        bk = next(
            (b for b in event.get("bookmakers", []) if b["key"] == BOOKMAKER),
            None
        )
        if not bk:
            return None

        game = {
            "id":            event["id"],
            "home_team":     event["home_team"],
            "away_team":     event["away_team"],
            "commence_time": event["commence_time"],
            "bookmaker":     BOOKMAKER,
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
