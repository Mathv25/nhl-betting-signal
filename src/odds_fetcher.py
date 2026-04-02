"""
Récupère les cotes bet365 via The Odds API
Marchés: h2h (moneyline), spreads (puck line), totals, props joueurs
"""

import requests
from typing import Optional


BASE_URL = "https://api.the-odds-api.com/v4"
SPORT_KEY = "icehockey_nhl"
BOOKMAKER = "bet365"
REGIONS = "eu"  # bet365 est disponible via région EU


class OddsFetcher:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.remaining_requests = None

    def _get(self, endpoint: str, params: dict) -> Optional[dict]:
        params["apiKey"] = self.api_key
        try:
            resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
            self.remaining_requests = resp.headers.get("x-requests-remaining", "?")
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            print(f"  ⚠️  Erreur API: {e}")
            return None

    def get_nhl_games_b365(self) -> list:
        """Récupère tous les marchés principaux bet365 pour les matchs NHL du jour."""
        print(f"  → Moneyline + Puck Line + Totals...")
        data = self._get(
            f"sports/{SPORT_KEY}/odds",
            {
                "regions": REGIONS,
                "markets": "h2h,spreads,totals",
                "bookmakers": BOOKMAKER,
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            }
        )
        if not data:
            return []

        print(f"  → Requêtes API restantes ce mois: {self.remaining_requests}")

        games = []
        for event in data:
            game = self._parse_event(event)
            if game:
                games.append(game)

        # Enrichit avec props joueurs pour chaque match
        for game in games:
            self._add_player_props(game)

        return games

    def _parse_event(self, event: dict) -> Optional[dict]:
        """Parse un événement API en structure interne."""
        b365 = next(
            (b for b in event.get("bookmakers", []) if b["key"] == BOOKMAKER),
            None
        )
        if not b365:
            return None

        game = {
            "id": event["id"],
            "home_team": event["home_team"],
            "away_team": event["away_team"],
            "commence_time": event["commence_time"],
            "bookmaker": BOOKMAKER,
            "markets": {}
        }

        for market in b365.get("markets", []):
            key = market["key"]
            if key == "h2h":
                game["markets"]["moneyline"] = self._parse_h2h(market, game)
            elif key == "spreads":
                game["markets"]["puck_line"] = self._parse_spreads(market, game)
            elif key == "totals":
                game["markets"]["totals"] = self._parse_totals(market)

        return game

    def _parse_h2h(self, market: dict, game: dict) -> dict:
        result = {}
        for outcome in market.get("outcomes", []):
            team_key = "home" if outcome["name"] == game["home_team"] else "away"
            result[team_key] = {
                "team": outcome["name"],
                "odds_decimal": outcome["price"],
                "implied_prob": round(1 / outcome["price"] * 100, 2)
            }
        return result

    def _parse_spreads(self, market: dict, game: dict) -> dict:
        result = {}
        for outcome in market.get("outcomes", []):
            team_key = "home" if outcome["name"] == game["home_team"] else "away"
            result[team_key] = {
                "team": outcome["name"],
                "spread": outcome.get("point", -1.5),
                "odds_decimal": outcome["price"],
                "implied_prob": round(1 / outcome["price"] * 100, 2)
            }
        return result

    def _parse_totals(self, market: dict) -> dict:
        result = {}
        for outcome in market.get("outcomes", []):
            direction = outcome["name"].lower()  # "over" ou "under"
            result[direction] = {
                "line": outcome.get("point"),
                "odds_decimal": outcome["price"],
                "implied_prob": round(1 / outcome["price"] * 100, 2)
            }
        return result

    def _add_player_props(self, game: dict):
        """Récupère les props joueurs disponibles sur bet365 pour ce match."""
        prop_markets = [
            "player_points",
            "player_goals",
            "player_assists",
            "player_shots_on_goal",
            "player_saves",
        ]
        print(f"  → Props joueurs: {game['home_team']} vs {game['away_team']}...")
        data = self._get(
            f"sports/{SPORT_KEY}/events/{game['id']}/odds",
            {
                "regions": REGIONS,
                "markets": ",".join(prop_markets),
                "bookmakers": BOOKMAKER,
                "oddsFormat": "decimal",
            }
        )
        if not data:
            game["markets"]["player_props"] = []
            return

        props = []
        b365 = next(
            (b for b in data.get("bookmakers", []) if b["key"] == BOOKMAKER),
            None
        )
        if not b365:
            game["markets"]["player_props"] = []
            return

        for market in b365.get("markets", []):
            for outcome in market.get("outcomes", []):
                props.append({
                    "market": market["key"],
                    "player": outcome["description"],
                    "direction": outcome["name"],
                    "line": outcome.get("point"),
                    "odds_decimal": outcome["price"],
                    "implied_prob": round(1 / outcome["price"] * 100, 2)
                })

        game["markets"]["player_props"] = props
        print(f"     ✅ {len(props)} props trouvées")
