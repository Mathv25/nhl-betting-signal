"""
NBA Odds Fetcher — The Odds API
Memes marches que NHL: player props points/rebounds/assists/3pts
"""

import requests
import time

API_BASE = "https://api.the-odds-api.com/v4"

# Marches NBA props disponibles sur The Odds API
NBA_PROP_MARKETS = [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
    "player_blocks",
    "player_steals",
    "player_points_rebounds_assists",
]

class NBAOddsFetcher:

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_nba_games(self) -> list:
        """Recupere les matchs NBA du jour avec cotes DraftKings."""
        print("  NBA: Recuperation des matchs...")
        url = f"{API_BASE}/sports/basketball_nba/odds"
        params = {
            "apiKey":   self.api_key,
            "regions":  "us",
            "markets":  "h2h,spreads,totals",
            "bookmakers": "draftkings",
            "oddsFormat": "decimal",
        }
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            raw = r.json()
            remaining = r.headers.get("x-requests-remaining", "?")
            print(f"  NBA: {len(raw)} matchs | API restantes: {remaining}")
            return [self._parse_game(g) for g in raw]
        except Exception as e:
            print(f"  NBA odds erreur: {e}")
            return []

    def get_player_props(self, event_id: str, market: str) -> list:
        """Recupere les props joueurs pour un marche specifique."""
        url = f"{API_BASE}/sports/basketball_nba/events/{event_id}/odds"
        params = {
            "apiKey":     self.api_key,
            "regions":    "us",
            "markets":    market,
            "bookmakers": "draftkings",
            "oddsFormat": "decimal",
        }
        try:
            time.sleep(0.5)
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            props = []
            for bm in data.get("bookmakers", []):
                for mkt in bm.get("markets", []):
                    for outcome in mkt.get("outcomes", []):
                        player = outcome.get("description", "")
                        name   = outcome.get("name", "").lower()
                        line   = outcome.get("point")
                        odds   = outcome.get("price", 0)
                        if not player or line is None: continue
                        props.append({
                            "player":    player,
                            "market":    market,
                            "direction": "over" if name == "over" else "under",
                            "line":      line,
                            "odds":      odds,
                            "implied_prob": round(1 / odds * 100, 2) if odds > 0 else 50.0,
                        })
            return props
        except Exception as e:
            return []

    def _parse_game(self, g: dict) -> dict:
        home = g.get("home_team", "")
        away = g.get("away_team", "")
        mkts = {}
        for bm in g.get("bookmakers", []):
            if bm.get("key") != "draftkings": continue
            for mkt in bm.get("markets", []):
                key = mkt.get("key", "")
                if key == "h2h":
                    mkts["moneyline"] = self._parse_h2h(mkt["outcomes"], home, away)
                elif key == "spreads":
                    mkts["spread"] = self._parse_spreads(mkt["outcomes"], home, away)
                elif key == "totals":
                    mkts["totals"] = self._parse_totals(mkt["outcomes"])
        return {
            "event_id":      g.get("id", ""),
            "home_team":     home,
            "away_team":     away,
            "commence_time": g.get("commence_time", ""),
            "markets":       mkts,
        }

    def _parse_h2h(self, outcomes, home, away):
        result = {}
        for o in outcomes:
            team = o.get("name", "")
            odds = o.get("price", 0)
            impl = round(1 / odds * 100, 2) if odds > 0 else 50.0
            side = "home" if team == home else "away"
            result[side] = {"team": team, "odds_decimal": odds, "implied_prob": impl}
        return result

    def _parse_spreads(self, outcomes, home, away):
        result = {}
        for o in outcomes:
            team   = o.get("name", "")
            odds   = o.get("price", 0)
            spread = o.get("point", 0)
            impl   = round(1 / odds * 100, 2) if odds > 0 else 50.0
            side   = "home" if team == home else "away"
            result[side] = {"team": team, "odds_decimal": odds,
                            "implied_prob": impl, "spread": spread}
        return result

    def _parse_totals(self, outcomes):
        result = {}
        for o in outcomes:
            direction = o.get("name", "").lower()
            odds = o.get("price", 0)
            line = o.get("point")
            impl = round(1 / odds * 100, 2) if odds > 0 else 50.0
            if direction in ("over", "under"):
                result[direction] = {"odds_decimal": odds, "implied_prob": impl, "line": line}
        return result
