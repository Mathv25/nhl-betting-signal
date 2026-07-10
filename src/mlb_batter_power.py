"""
MLB Batter Power Analyzer
Identifie les frappeurs susceptibles d'atteindre 4-8 bases totales.
Courbe de probabilité P(TB >= N) pour N=4..8 + calculateur edge.
"""
import math
import time
import requests

MLB_API = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
TIMEOUT = 10

N_GAMES     = 15   # fenêtre rolling
MIN_P4      = 20.0 # P(TB>=4) minimum pour apparaître (%)
MIN_AB_GAME = 2    # AB minimum pour compter un match

_pid_cache:  dict = {}
_tb_cache:   dict = {}


def _get(url, params=None):
    try:
        r = requests.get(url, params=params or {}, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _search_player_id(name: str):
    key = name.lower().strip()
    if key in _pid_cache:
        return _pid_cache[key]
    data = _get(f"{MLB_API}/people/search", {"names": name, "sportId": 1})
    pid = data["people"][0]["id"] if data and data.get("people") else None
    _pid_cache[key] = pid
    return pid


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _prob_tb_gte(mean_tb: float, std_tb: float, n: int) -> float:
    """P(TB >= n) via distribution normale."""
    if std_tb <= 0 or mean_tb <= 0:
        return 0.0
    z = (n - 0.5 - mean_tb) / std_tb
    return round(max(min((1 - _normal_cdf(z)) * 100, 99.0), 0.5), 1)


def get_batter_tb_rolling(name: str, n_games: int = N_GAMES) -> dict | None:
    """
    Retourne les stats TB rolling du frappeur.
    {mean_tb, std_tb, hr_rate, games, hot_streak, tb_dist}
    """
    key = f"{name}_{n_games}"
    if key in _tb_cache:
        return _tb_cache[key]

    pid = _search_player_id(name)
    if pid is None:
        _tb_cache[key] = None
        return None

    data = _get(f"{MLB_API}/people/{pid}/stats", {
        "stats": "gameLog", "group": "hitting", "season": "2026"
    })
    if not data:
        _tb_cache[key] = None
        return None

    splits = data.get("stats", [{}])[0].get("splits", [])
    # Garder seulement les matchs avec au moins MIN_AB_GAME AB
    games  = [g for g in splits if g["stat"].get("atBats", 0) >= MIN_AB_GAME]
    if len(games) < 5:
        _tb_cache[key] = None
        return None

    # Saison complète pour stabilité
    all_tb   = [g["stat"].get("totalBases", 0) for g in games]
    season_avg = sum(all_tb) / len(all_tb)

    # Rolling n derniers matchs (pondéré — récents comptent plus)
    recent = games[-n_games:]
    tb_vals = [g["stat"].get("totalBases", 0) for g in recent]
    hr_vals = [g["stat"].get("homeRuns", 0) for g in recent]

    n = len(tb_vals)
    weights  = [1.0 + 0.5 * i for i in range(n)]
    w_sum    = sum(w * t for w, t in zip(weights, tb_vals))
    w_total  = sum(weights)
    rolling_avg = w_sum / w_total

    # Blend 65% rolling / 35% saison
    mean_tb = round(0.65 * rolling_avg + 0.35 * season_avg, 3)

    # Écart-type (variance TB est haute)
    variance = sum((t - mean_tb) ** 2 for t in tb_vals) / len(tb_vals)
    std_tb   = round(max(math.sqrt(variance), 0.8), 3)

    hr_rate  = round(sum(hr_vals) / len(hr_vals), 3)

    # Distribution TB observée
    tb_dist = {str(i): sum(1 for t in all_tb if t == i) for i in range(0, 9)}

    # Hot streak: tendance des 5 derniers vs 10 précédents
    if len(tb_vals) >= 5:
        last5  = sum(tb_vals[-5:]) / 5
        prev10 = sum(tb_vals[:-5]) / max(len(tb_vals) - 5, 1)
        hot_streak = round(last5 - prev10, 2)
    else:
        hot_streak = 0.0

    result = {
        "mean_tb":    mean_tb,
        "std_tb":     std_tb,
        "hr_rate":    hr_rate,
        "games":      len(tb_vals),
        "season_avg": round(season_avg, 2),
        "rolling_avg": round(rolling_avg, 2),
        "hot_streak": hot_streak,
        "tb_dist":    tb_dist,
    }
    _tb_cache[key] = result
    return result


def analyze_power_batters(game: dict, roster_batters: list) -> list:
    """
    Analyse les frappeurs d'un match pour identifier les candidats 4+ TB.
    roster_batters: [{"name": str, "team": str, "bats": str}]
    Retourne une liste triée par P(TB>=4) décroissant.
    """
    results = []

    for batter in roster_batters:
        name = batter.get("name", "")
        if not name:
            continue

        stats = get_batter_tb_rolling(name)
        time.sleep(0.2)
        if stats is None:
            continue

        mean_tb = stats["mean_tb"]
        std_tb  = stats["std_tb"]

        # Courbe P(TB >= N) pour N = 4..8
        curve = []
        for n in range(4, 9):
            prob = _prob_tb_gte(mean_tb, std_tb, n)
            curve.append({"n": n, "prob": prob})

        p4 = curve[0]["prob"]  # P(TB >= 4)

        if p4 < MIN_P4:
            continue

        results.append({
            "player":      name,
            "team":        batter.get("team", ""),
            "mean_tb":     mean_tb,
            "rolling_avg": stats["rolling_avg"],
            "season_avg":  stats["season_avg"],
            "hr_rate":     stats["hr_rate"],
            "hot_streak":  stats["hot_streak"],
            "games":       stats["games"],
            "curve":       curve,
            "p4":          p4,
        })

    return sorted(results, key=lambda x: -x["p4"])
