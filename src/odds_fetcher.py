"""
Odds Fetcher — The Odds API → bet365 uniquement
Marchés récupérés:
  - h2h (moneyline)
  - spreads (puck line ±1.5)
  - totals (O/U buts)
  - h2h_1st_period (ML 1re période)
  - totals_1st_period (O/U 1re période)
  - player_shots_on_goal
  - player_goals
  - player_assists
  - player_points
  - player_saves
"""

import requests
from typing import Optional

BASE_URL  = "https://api.the-odds-api.com/v4"
SPORT     = "icehockey_nhl"
BOOKMAKER = "bet365"
REGIONS   = "us"
FMT_ODDS  = "decimal"
FMT_DATE  = "iso"

# Marchés principaux (1 requête par match)
MAIN_MARKETS = "h2h,spreads,totals"

# Marchés de période (1 requête par match)
PERIOD_MARKETS = "h2h_1st_period,totals_1st_period"

# Marchés props joueurs (1 requête par match)
PROP_MARKETS = (
    "player_shots_on_goal,"
    "player_goals,"
    "player_assists,"
    "player_points,"
    "player_saves"
)


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
            print(f"  ⚠️  HTTP {e.response.status_code}: {endpoint}")
            return None
        except Exception as e:
            print(f"  ⚠️  Erreur réseau: {e}")
            return None

    # ── Récupération principale ────────────────────────────────────────────

    def get_nhl_games_b365(self) -> list:
        """
        Récupère tous les matchs NHL du jour avec leurs marchés bet365.
        Retourne une liste de dicts structurés prêts pour l'EdgeCalculator.
        """
        print("  → Récupération matchs + cotes principales (ML/PL/Total)...")
        raw = self._get(f"sports/{SPORT}/odds", {
            "regions": REGIONS,
            "markets": MAIN_MARKETS,
            "bookmakers": BOOKMAKER,
            "oddsFormat": FMT_ODDS,
            "dateFormat": FMT_DATE,
        })

        if not raw:
            return []

        print(f"  → Requêtes API restantes: {self.remaining} | utilisées: {self.used}")

        games = []
        for event in raw:
            game = self._parse_event(event)
            if game:
                games.append(game)

        print(f"  ✅ {len(games)} match(s) avec cotes bet365")

        # Enrichissement: marchés de période + props joueurs
        for game in games:
            self._add_period_markets(game)
            self._add_player_props(game)

        return games

    # ── Parsing événement ──────────────────────────────────────────────────

    def _parse_event(self, event: dict) -> Optional[dict]:
        b365 = next(
            (b for b in event.get("bookmakers", []) if b["key"] == BOOKMAKER),
            None
        )
        if not b365:
            return None

        game = {
            "id":             event["id"],
            "home_team":      event["home_team"],
            "away_team":      event["away_team"],
            "commence_time":  event["commence_time"],
            "bookmaker":      BOOKMAKER,
            "markets":        {},
            "removed_props":  [],
        }

        for market in b365.get("markets", []):
            k = market["key"]
            if k == "h2h":
                game["markets"]["moneyline"] = self._parse_h2h(market, game)
            elif k == "spreads":
                game["markets"]["puck_line"] = self._parse_spreads(market, game)
            elif k == "totals":
                game["markets"]["totals"] = self._parse_totals(market)

        return game

    def _parse_h2h(self, market: dict, game: dict) -> dict:
        out = {}
        for o in market.get("outcomes", []):
            side = "home" if o["name"] == game["home_team"] else "away"
            out[side] = {
                "team":         o["name"],
                "odds_decimal": round(o["price"], 3),
                "implied_prob": round(1 / o["price"] * 100, 2),
            }
        return out

    def _parse_spreads(self, market: dict, game: dict) -> dict:
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

    def _parse_totals(self, market: dict) -> dict:
        out = {}
        for o in market.get("outcomes", []):
            direction = o["name"].lower()
            out[direction] = {
                "line":         o.get("point"),
                "odds_decimal": round(o["price"], 3),
                "implied_prob": round(1 / o["price"] * 100, 2),
            }
        return out

    # ── Marchés de période ─────────────────────────────────────────────────

    def _add_period_markets(self, game: dict):
        """Ajoute les marchés 1re période si disponibles sur bet365."""
        data = self._get(f"sports/{SPORT}/events/{game['id']}/odds", {
            "regions": REGIONS,
            "markets": PERIOD_MARKETS,
            "bookmakers": BOOKMAKER,
            "oddsFormat": FMT_ODDS,
        })
        if not data:
            return

        b365 = next(
            (b for b in data.get("bookmakers", []) if b["key"] == BOOKMAKER),
            None
        )
        if not b365:
            return

        for market in b365.get("markets", []):
            k = market["key"]
            if k == "h2h_1st_period":
                game["markets"]["first_period_ml"] = self._parse_h2h(market, game)
            elif k == "totals_1st_period":
                game["markets"]["first_period_totals"] = self._parse_totals(market)

    # ── Props joueurs ──────────────────────────────────────────────────────

    def _add_player_props(self, game: dict):
        """Récupère toutes les props joueurs bet365 pour ce match."""
        data = self._get(f"sports/{SPORT}/events/{game['id']}/odds", {
            "regions": REGIONS,
            "markets": PROP_MARKETS,
            "bookmakers": BOOKMAKER,
            "oddsFormat": FMT_ODDS,
        })

        game["markets"]["player_props"] = []
        if not data:
            return

        b365 = next(
            (b for b in data.get("bookmakers", []) if b["key"] == BOOKMAKER),
            None
        )
        if not b365:
            return

        props = []
        for market in b365.get("markets", []):
            for o in market.get("outcomes", []):
                props.append({
                    "market":       market["key"],
                    "player":       o.get("description", ""),
                    "direction":    o["name"].lower(),
                    "line":         o.get("point"),
                    "odds_decimal": round(o["price"], 3),
                    "implied_prob": round(1 / o["price"] * 100, 2),
                })

        game["markets"]["player_props"] = props
        n = len(props)
        if n:
            print(f"     → {n} props: {game['home_team']} vs {game['away_team']}")
