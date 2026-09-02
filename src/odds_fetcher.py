"""
Odds Fetcher - The Odds API -> DraftKings
Marches: h2h (moneyline), spreads (puck line), totals + player props NHL
"""

import time
from typing import Optional

import odds_api

# BASE_URL vit dans odds_api (client partage).
SPORT     = "icehockey_nhl"
BOOKMAKER = "draftkings"
FMT_ODDS  = "decimal"
FMT_DATE  = "iso"
MAIN_MARKETS = "h2h,spreads,totals"

# Ordre de priorite: bet365 (UK) en premier car c'est la que l'utilisateur bet,
# puis DraftKings (US) en fallback si bet365 n'a pas encore poste les cotes.
BOOKMAKER_PRIORITY = [
    {"key": "draftkings",   "region": "us"},
    {"key": "fanduel",      "region": "us"},
    {"key": "betmgm",       "region": "us"},
    {"key": "williamhill_us", "region": "us"},
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
        self.client    = odds_api.get_client(api_key)
        self.prop_events_done = 0

    def _get(self, endpoint: str, params: dict, cost: int = 1) -> Optional[dict]:
        """Passe par le client partage: cache + comptage et garde-fou de quota."""
        data = self.client.get(endpoint, params, cost=cost)
        if self.client.remaining is not None:
            self.remaining = self.client.remaining
        if self.client.used is not None:
            self.used = self.client.used
        return data

    @staticmethod
    def _n_regions() -> int:
        return max(len([r for r in odds_api.regions().split(",") if r.strip()]), 1)

    def get_nhl_games_b365(self) -> list:
        """
        Fetch les cotes NHL, puis parse en respectant l'ordre de priorite des
        books (bet365 d'abord la ou il est offert, sinon DK/FD).

        Un SEUL appel reseau pour tous les books. L'ancienne version relancait
        une requete par book de la cascade: 3 marches x 1 region = 3 credits par
        tentative, jusqu'a 12 credits pour un slate, et ce a chaque execution
        horaire. Le meme appel sans filtre `bookmakers` coute le meme prix pour
        un seul book et ramene les quatre.
        """
        cost = len(MAIN_MARKETS.split(",")) * self._n_regions()
        raw = self._get(f"sports/{SPORT}/odds", {
            "regions":    odds_api.regions(),
            "markets":    MAIN_MARKETS,
            "oddsFormat": FMT_ODDS,
            "dateFormat": FMT_DATE,
        }, cost=cost)
        print(f"  -> Requetes API restantes: {self.remaining} | utilisees: {self.used}")
        if not raw:
            print("  Aucun match NHL disponible.")
            return []

        for entry in BOOKMAKER_PRIORITY:
            book   = entry["key"]
            region = entry["region"]
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

    def get_nhl_player_props(self, event_id: str, bookmaker: str = "draftkings") -> dict:
        """Fetche les props joueurs NHL pour un match (tous les marches et tous
        les books en un seul appel), puis retient le premier book de la
        priorite qui cote reellement le match.
        Retourne dict {market_key: [{player, line, over_odds, over_implied, under_odds, under_implied}]}
        """
        if not odds_api.props_enabled() or not odds_api.props_window_open() or not self.client.healthy:
            return {}

        # 10 credits par (marche x region) sur l'endpoint event: 3 marches en
        # us+eu = 60 credits POUR UN MATCH, sur un quota mensuel de 500. La
        # cascade par book multipliait encore ce montant par le nombre de books
        # essayes. Un seul appel, tous les books, et un plafond d'evenements.
        params = {
            "regions":    odds_api.regions(),
            "markets":    ",".join(NHL_PROP_MARKETS),
            "oddsFormat": FMT_ODDS,
        }
        cost = (odds_api.COST_PER_MARKET_REGION_PROP
                * len(NHL_PROP_MARKETS) * self._n_regions())
        endpoint  = f"sports/{SPORT}/events/{event_id}/odds"
        cache_hit = self.client._cache_read(self.client._key(endpoint, params)) is not None
        if not cache_hit:
            if self.prop_events_done >= odds_api.max_prop_events():
                print(f"    [Props NHL] plafond ODDS_MAX_PROP_EVENTS="
                      f"{odds_api.max_prop_events()} atteint — {event_id[:8]} ignore")
                return {}
            if not self.client.can_spend_props(cost):
                print(f"    [Props NHL] budget du jour atteint "
                      f"({self.client.spent_today() + self.client.prop_credits}/"
                      f"{self.client.day_budget()} credits) — {event_id[:8]} ignore")
                return {}
            self.client.note_props(cost)
            self.prop_events_done += 1
            time.sleep(0.5)

        data = self._get(endpoint, params, cost=cost)
        if not data:
            return {}

        # Le book retenu est le premier de la priorite qui cote reellement.
        offered = {bm.get("key") for bm in data.get("bookmakers", []) if bm.get("markets")}
        books_to_try = [bookmaker] + [e["key"] for e in BOOKMAKER_PRIORITY if e["key"] != bookmaker]
        used_bookmaker = next((b for b in books_to_try if b in offered), bookmaker)
        if used_bookmaker != bookmaker and used_bookmaker in offered:
            print(f"    [Props NHL] {bookmaker} sans props — utilise {used_bookmaker}")

        result = {}
        for bm in data.get("bookmakers", []):
            if bm.get("key") != used_bookmaker:
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
