"""
NBA Props Analyzer - Stats via BallDontLie API (gratuit, pas de cle requise)
Distribution normale pour points/rebonds/passes/3pts
"""
import requests
import time
import math
from typing import Optional

BDLIE_URL = "https://www.balldontlie.io/api/v1"

# Mapping marche -> (cle stat dans la reponse BallDontLie, label affichage)
MARKET_TO_STAT = {
    "player_points":                  ("pts",  "Points"),
    "player_rebounds":                ("reb",  "Rebonds"),
    "player_assists":                 ("ast",  "Passes"),
    "player_threes":                  ("fg3m", "3pts"),
    "player_points_rebounds_assists": ("pra",  "PRA"),
}

MIN_EDGE       = 6.0
MIN_GAMES      = 5
MIN_ODDS       = 1.65
MAX_BETS_GAME  = 6
# Props DK standard: -115/-115 => implied 53.49% par cote
DK_PROP_IMPLIED = 53.49


def _get(url: str, params: dict = None) -> Optional[dict]:
    time.sleep(0.4)
    try:
        r = requests.get(url, params=params or {}, timeout=12,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def _search_player_id(name: str) -> Optional[int]:
    """Cherche l'ID BallDontLie d'un joueur par son nom."""
    data = _get(f"{BDLIE_URL}/players", {"search": name, "per_page": 5})
    if not data or not data.get("data"):
        return None
    players = data["data"]
    if not players:
        return None
    # Prend le premier resultat (generalement le plus proche)
    return players[0]["id"]


def _get_recent_stats(player_id: int, stat_key: str, n: int = 15) -> list:
    """
    Retourne les n derniers matchs du joueur pour la saison 2024-25.
    Exclut les matchs < 10 minutes de temps de jeu.
    """
    data = _get(f"{BDLIE_URL}/stats", {
        "player_ids[]": player_id,
        "seasons[]":    2024,
        "per_page":     n,
    })
    if not data or not data.get("data"):
        return []

    logs = sorted(
        data["data"],
        key=lambda x: x.get("game", {}).get("date", ""),
        reverse=True
    )

    values = []
    for log in logs:
        # Filtre: minimum 10 minutes
        min_str = str(log.get("min", "0") or "0")
        try:
            mins = int(min_str.split(":")[0]) if ":" in min_str else int(min_str)
        except Exception:
            mins = 0
        if mins < 10:
            continue

        if stat_key == "pra":
            v = (log.get("pts") or 0) + (log.get("reb") or 0) + (log.get("ast") or 0)
        else:
            v = log.get(stat_key) or 0
        values.append(float(v))

    return values[:10]


def _weighted_avg(values: list) -> float:
    """Moyenne ponderee exponentiellement (plus recent = plus important)."""
    if not values:
        return 0.0
    weights = [math.exp(-0.1 * i) for i in range(len(values))]
    total_w = sum(weights)
    return sum(v * w for v, w in zip(values, weights)) / total_w


def _std_dev(values: list, mean: float) -> float:
    if len(values) < 2:
        return mean * 0.35
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return max(math.sqrt(variance), mean * 0.25)


def _normal_over_prob(mean: float, std: float, line: float) -> float:
    """
    Probabilite Over(line) avec distribution normale + correction de continuite.
    Utilise une approximation de la fonction erf.
    """
    if std <= 0:
        return 99.0 if mean > line else 1.0

    # Correction de continuite: on ajoute 0.5 car la stat est discrete
    z = (line + 0.5 - mean) / std

    def erf_approx(x):
        sign = 1 if x >= 0 else -1
        x = abs(x)
        t = 1.0 / (1.0 + 0.3275911 * x)
        poly = t * (0.254829592 + t * (-0.284496736 + t * (
               1.421413741 + t * (-1.453152027 + t * 1.061405429))))
        return sign * (1.0 - poly * math.exp(-x * x))

    prob_over = (1.0 - erf_approx(z / math.sqrt(2))) / 2.0
    return round(min(max(prob_over * 100, 1.0), 99.0), 1)


def _edge(our_pct: float, implied_pct: float) -> float:
    if implied_pct <= 0:
        return 0.0
    return round((our_pct - implied_pct) / implied_pct * 100, 1)


def _kelly(our_pct: float, odds: float) -> float:
    b = odds - 1
    if b <= 0:
        return 0.0
    k = ((b * our_pct / 100) - (1 - our_pct / 100)) / b / 4 * 100
    return round(max(k, 0.0), 1)


class NBAPropsAnalyzer:

    def __init__(self):
        self._id_cache    = {}   # name -> player_id
        self._stats_cache = {}   # "{player_id}_{stat_key}" -> [values]

    def analyze_game(self, game: dict, props_by_market: dict) -> dict:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        print(f"  NBA props: {away} @ {home}")

        ev_bets      = []
        seen_players = set()

        for market, props in props_by_market.items():
            stat_key, stat_label = MARKET_TO_STAT.get(market, ("pts", market))

            for prop in props:
                player_name  = prop.get("player", "")
                line         = prop.get("line", 0)
                over_odds    = prop.get("over_odds", 2.0)
                over_implied = prop.get("over_implied", DK_PROP_IMPLIED)

                if not player_name or player_name in seen_players:
                    continue
                if over_odds < MIN_ODDS:
                    continue

                # Stats joueur
                values = self._fetch_player_stats(player_name, stat_key)
                if not values or len(values) < MIN_GAMES:
                    continue

                mean = _weighted_avg(values)
                std  = _std_dev(values, mean)

                our_prob = _normal_over_prob(mean, std, line)
                edge     = _edge(our_prob, over_implied)

                if edge < MIN_EDGE:
                    continue

                avg5  = round(sum(values[:5]) / min(5, len(values)), 1)
                avg10 = round(mean, 1)

                context = []
                if avg5 > avg10 * 1.20:
                    context.append(f"🔥 En hausse — {avg5} last 5 vs {avg10} last 10")
                elif avg5 < avg10 * 0.80:
                    context.append(f"❄️ En baisse — {avg5} last 5 vs {avg10} last 10")
                if our_prob >= 70:
                    context.append(f"✅ Forte conviction — {our_prob}% prob")

                ev_bets.append({
                    "player":    player_name,
                    "team":      home,   # approximation, affinee si besoin
                    "opponent":  away,
                    "market":    f"{stat_label} Over {line}",
                    "stat_key":  stat_key,
                    "line":      line,
                    "avg10":     avg10,
                    "avg5":      avg5,
                    "adj_proj":  round(mean, 1),
                    "our_prob":  our_prob,
                    "edge_pct":  edge,
                    "kelly":     _kelly(our_prob, over_odds),
                    "est_odds":  over_odds,
                    "dk_implied": over_implied,
                    "def_rank":  15,
                    "context":   context,
                })

                seen_players.add(player_name)

        ev_bets.sort(key=lambda x: x["edge_pct"], reverse=True)
        ev_bets = ev_bets[:MAX_BETS_GAME]

        print(f"    -> {len(ev_bets)} bets NBA +EV")
        return {
            "home_team": home,
            "away_team": away,
            "bets":      ev_bets,
        }

    def _fetch_player_stats(self, name: str, stat_key: str) -> Optional[list]:
        cache_key = f"{name}_{stat_key}"
        if cache_key in self._stats_cache:
            return self._stats_cache[cache_key]

        # ID joueur
        if name in self._id_cache:
            player_id = self._id_cache[name]
        else:
            player_id = _search_player_id(name)
            self._id_cache[name] = player_id

        if not player_id:
            return None

        values = _get_recent_stats(player_id, stat_key)
        self._stats_cache[cache_key] = values
        return values
