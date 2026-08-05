"""
MLB Batter Power Analyzer
Identifie les frappeurs susceptibles d'atteindre 4-8 bases totales.
Courbe de probabilité P(TB >= N) pour N=4..8 + calculateur edge.

v2 — modèle enrichi (contexte matchup, plus seulement la forme du frappeur):
  1. Qualité du lanceur adverse   → facteur via SLG-contre du partant
  2. Historique frappeur-vs-lanceur (H2H) → blend TB/AB avec shrinkage PA/(PA+K)
  3. Platoon G/D                  → split du frappeur vs la main du lanceur
  4. Facteur de terrain           → parc du match (Coors ↑, parcs de lanceurs ↓)
Chaque ajustement dégrade proprement vers 1.0 si la donnée manque.
"""
from __future__ import annotations

import math
import time
import requests

MLB_API = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
TIMEOUT = 10

N_GAMES     = 15   # fenêtre rolling
MIN_P4      = 20.0 # P(TB>=4) minimum pour apparaître (%)
MIN_AB_GAME = 2    # AB minimum pour compter un match

# ── Paramètres du modèle matchup ─────────────────────────────────────────────
LEAGUE_AVG_SLG = 0.410   # SLG moyen MLB (référence pour les facteurs)
AB_PER_GAME    = 3.8     # AB attendus par match (conversion /AB → /match)
H2H_SHRINK_K   = 30      # constante de régression H2H : poids = PA/(PA+K)
MIN_PA_H2H     = 6       # PA minimum pour considérer le H2H
MIN_AB_SPLIT   = 40      # AB minimum pour un split platoon significatif
ENRICH_P4_FLOOR = 12.0   # on n'enrichit (appels API) que les frappeurs >= ce P4 de base

# Facteurs de terrain (offense/TB, 1.0 = neutre). Clé = nom complet équipe domicile.
PARK_TB_FACTOR = {
    "Colorado Rockies": 1.15, "Cincinnati Reds": 1.06, "Boston Red Sox": 1.05,
    "Baltimore Orioles": 1.03, "Philadelphia Phillies": 1.03, "New York Yankees": 1.02,
    "Arizona Diamondbacks": 1.02, "Texas Rangers": 1.02, "Kansas City Royals": 1.02,
    "Chicago Cubs": 1.01, "Toronto Blue Jays": 1.01, "Houston Astros": 1.01,
    "Atlanta Braves": 1.00, "Los Angeles Dodgers": 1.00, "Minnesota Twins": 1.00,
    "Washington Nationals": 1.00, "Milwaukee Brewers": 1.00, "Chicago White Sox": 1.00,
    "St. Louis Cardinals": 0.99, "Los Angeles Angels": 0.99, "New York Mets": 0.98,
    "Cleveland Guardians": 0.98, "Pittsburgh Pirates": 0.97, "Detroit Tigers": 0.97,
    "Tampa Bay Rays": 0.97, "Athletics": 0.95, "Oakland Athletics": 0.95,
    "Miami Marlins": 0.95, "San Diego Padres": 0.94, "Seattle Mariners": 0.93,
    "San Francisco Giants": 0.93,
}

_pid_cache:   dict = {}
_tb_cache:    dict = {}
_hand_cache:  dict = {}   # main lanceur ET côté frappeur
_pfac_cache:  dict = {}   # facteur qualité lanceur
_h2h_cache:   dict = {}   # H2H TB
_split_cache: dict = {}   # split platoon TB


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


def _to_float(v) -> float:
    """Parse un SLG/AVG MLB ('.412' ou '0.412') en float, robuste."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _prob_tb_gte(mean_tb: float, std_tb: float, n: int) -> float:
    """P(TB >= n) via distribution normale."""
    if std_tb <= 0 or mean_tb <= 0:
        return 0.0
    z = (n - 0.5 - mean_tb) / std_tb
    return round(max(min((1 - _normal_cdf(z)) * 100, 99.0), 0.5), 1)


# ── Contexte matchup ─────────────────────────────────────────────────────────

def _pitcher_hand(pitcher_name: str) -> str:
    """Main du lanceur ('L'/'R'), défaut 'R'."""
    key = f"P_{pitcher_name.lower().strip()}"
    if key in _hand_cache:
        return _hand_cache[key]
    pid = _search_player_id(pitcher_name)
    hand = "R"
    if pid is not None:
        data = _get(f"{MLB_API}/people/{pid}", {})
        if data and data.get("people"):
            hand = data["people"][0].get("pitchHand", {}).get("code", "R")
    _hand_cache[key] = hand
    return hand


def _batter_hand(batter_id: int) -> str:
    """Côté du frappeur ('L'/'R'/'S'), défaut 'R'."""
    key = f"B_{batter_id}"
    if key in _hand_cache:
        return _hand_cache[key]
    hand = "R"
    data = _get(f"{MLB_API}/people/{batter_id}", {})
    if data and data.get("people"):
        hand = data["people"][0].get("batSide", {}).get("code", "R")
    _hand_cache[key] = hand
    return hand


def _pitcher_tb_factor(pitcher_name: str) -> tuple:
    """
    Facteur de suppression TB du lanceur adverse, via son SLG-contre (saison).
    < 1.0 = lanceur qui étouffe la puissance (ex: Skubal), > 1.0 = généreux.
    Retourne (facteur, description).
    """
    key = pitcher_name.lower().strip()
    if key in _pfac_cache:
        return _pfac_cache[key]
    pid = _search_player_id(pitcher_name)
    result = (1.0, "")
    if pid is not None:
        data = _get(f"{MLB_API}/people/{pid}/stats", {
            "stats": "season", "group": "pitching", "season": "2026",
        })
        if data:
            for s in data.get("stats", []):
                for sp in s.get("splits", []):
                    slg_against = _to_float(sp.get("stat", {}).get("slg"))
                    if slg_against > 0:
                        factor = slg_against / LEAGUE_AVG_SLG
                        factor = round(max(min(factor, 1.25), 0.75), 3)
                        result = (factor, f"lanceur SLG-contre {slg_against:.3f} (x{factor})")
    _pfac_cache[key] = result
    return result


def _h2h_tb(batter_id: int, pitcher_id: int) -> dict | None:
    """H2H carrière frappeur vs lanceur, orienté bases totales."""
    key = f"{batter_id}_{pitcher_id}"
    if key in _h2h_cache:
        return _h2h_cache[key]
    result = None
    data = _get(f"{MLB_API}/people/{batter_id}/stats", {
        "stats": "vsPlayerTotal", "group": "hitting", "opposingPlayerId": pitcher_id,
    })
    if data:
        for s in data.get("stats", []):
            for sp in s.get("splits", []):
                stat = sp.get("stat", {})
                ab = stat.get("atBats", 0)
                pa = stat.get("plateAppearances", ab)
                tb = stat.get("totalBases", 0)
                if pa >= MIN_PA_H2H and ab > 0:
                    result = {
                        "pa": pa, "ab": ab, "tb": tb,
                        "tb_per_ab": round(tb / ab, 3),
                        "avg": stat.get("avg", ".000"),
                    }
    _h2h_cache[key] = result
    return result


def _platoon_factor(batter_id: int, batter_hand: str, pitcher_hand: str) -> tuple:
    """
    Facteur platoon G/D via le split SLG du frappeur vs la main du lanceur.
    Fallback générique si l'échantillon est trop petit.
    Retourne (facteur, description).
    """
    key = f"{batter_id}_{pitcher_hand}"
    if key in _split_cache:
        return _split_cache[key]
    sit = "vl" if pitcher_hand == "L" else "vr"
    data = _get(f"{MLB_API}/people/{batter_id}/stats", {
        "stats": "statSplits", "group": "hitting", "season": "2026", "sitCodes": sit,
    })
    result = None
    if data:
        for s in data.get("stats", []):
            for sp in s.get("splits", []):
                stat = sp.get("stat", {})
                ab  = stat.get("atBats", 0)
                slg = _to_float(stat.get("slg"))
                if ab >= MIN_AB_SPLIT and slg > 0:
                    factor = round(max(min(slg / LEAGUE_AVG_SLG, 1.20), 0.85), 3)
                    hand_lbl = "LHP" if pitcher_hand == "L" else "RHP"
                    result = (factor, f"vs {hand_lbl}: SLG {slg:.3f} ({ab} AB, x{factor})")
    if result is None:
        # Fallback générique sur les mains (avantage platoon ~ +4%, désavantage -4%)
        if batter_hand == "S":
            result = (1.02, "switch (léger avantage platoon)")
        elif batter_hand != pitcher_hand:
            result = (1.04, f"avantage platoon ({batter_hand} vs {pitcher_hand})")
        else:
            result = (0.96, f"désavantage platoon ({batter_hand} vs {pitcher_hand})")
    _split_cache[key] = result
    return result


def get_batter_tb_rolling(name: str, n_games: int = N_GAMES) -> dict | None:
    """
    Retourne les stats TB rolling du frappeur (forme brute, sans matchup).
    {mean_tb, std_tb, hr_rate, games, hot_streak, season_avg, rolling_avg, tb_dist}
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
    games  = [g for g in splits if g["stat"].get("atBats", 0) >= MIN_AB_GAME]
    if len(games) < 5:
        _tb_cache[key] = None
        return None

    all_tb   = [g["stat"].get("totalBases", 0) for g in games]
    season_avg = sum(all_tb) / len(all_tb)

    recent = games[-n_games:]
    tb_vals = [g["stat"].get("totalBases", 0) for g in recent]
    hr_vals = [g["stat"].get("homeRuns", 0) for g in recent]

    n = len(tb_vals)
    weights  = [1.0 + 0.5 * i for i in range(n)]
    w_sum    = sum(w * t for w, t in zip(weights, tb_vals))
    w_total  = sum(weights)
    rolling_avg = w_sum / w_total

    mean_tb = round(0.65 * rolling_avg + 0.35 * season_avg, 3)

    variance = sum((t - mean_tb) ** 2 for t in tb_vals) / len(tb_vals)
    std_tb   = round(max(math.sqrt(variance), 0.8), 3)

    hr_rate  = round(sum(hr_vals) / len(hr_vals), 3)
    tb_dist = {str(i): sum(1 for t in all_tb if t == i) for i in range(0, 9)}

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
        "pid":        pid,
    }
    _tb_cache[key] = result
    return result


def analyze_power_batters(game: dict, roster_batters: list,
                          opp_pitchers: dict = None, park_factor: float = 1.0) -> list:
    """
    Analyse les frappeurs d'un match pour identifier les candidats 4+ TB.
    roster_batters: [{"name": str, "team": str}]
    opp_pitchers:   {team_name: nom_du_lanceur_adverse}  (le partant que ce frappeur affronte)
    park_factor:    facteur TB du terrain (domicile)
    Retourne une liste triée par P(TB>=4) ajustée décroissant.
    """
    opp_pitchers = opp_pitchers or {}
    results = []

    # Résout le contexte lanceur une fois par lanceur (mis en cache de toute façon)
    for batter in roster_batters:
        name = batter.get("name", "")
        if not name:
            continue

        stats = get_batter_tb_rolling(name)
        time.sleep(0.2)
        if stats is None:
            continue

        base_mean = stats["mean_tb"]
        std_tb    = stats["std_tb"]

        # P(TB>=4) de base — sert de garde pour limiter les appels API d'enrichissement
        base_p4 = _prob_tb_gte(base_mean, std_tb, 4)
        if base_p4 < ENRICH_P4_FLOOR:
            continue

        mean_tb = base_mean
        reasons = []

        pitcher_name = opp_pitchers.get(batter.get("team", ""))
        pitcher_id   = None
        p_hand       = "R"
        if pitcher_name:
            # 1) Qualité du lanceur adverse
            pf, pf_desc = _pitcher_tb_factor(pitcher_name)
            mean_tb *= pf
            if pf_desc:
                reasons.append(pf_desc)
            p_hand = _pitcher_hand(pitcher_name)
            time.sleep(0.15)
            pitcher_id = _search_player_id(pitcher_name)

            # 3) Platoon G/D
            b_hand = _batter_hand(stats["pid"])
            time.sleep(0.15)
            plat_f, plat_desc = _platoon_factor(stats["pid"], b_hand, p_hand)
            mean_tb *= plat_f
            reasons.append(plat_desc)
            time.sleep(0.15)

        # 4) Facteur de terrain
        if park_factor and abs(park_factor - 1.0) > 0.001:
            mean_tb *= park_factor
            reasons.append(f"parc x{round(park_factor, 3)}")

        # 2) H2H frappeur-vs-lanceur (blend avec shrinkage)
        h2h = _h2h_tb(stats["pid"], pitcher_id) if pitcher_id else None
        if h2h:
            w = h2h["pa"] / (h2h["pa"] + H2H_SHRINK_K)
            h2h_mean = h2h["tb_per_ab"] * AB_PER_GAME
            mean_tb = (1 - w) * mean_tb + w * h2h_mean
            reasons.append(
                f"H2H {h2h['tb']} TB/{h2h['ab']} AB ({h2h['avg']} AVG, poids {w:.0%})"
            )
            time.sleep(0.15)

        mean_tb = round(mean_tb, 3)

        # Courbe P(TB >= N) ajustée
        curve = [{"n": n, "prob": _prob_tb_gte(mean_tb, std_tb, n)} for n in range(4, 9)]
        p4 = curve[0]["prob"]

        if p4 < MIN_P4:
            continue

        results.append({
            "player":       name,
            "team":         batter.get("team", ""),
            "opponent":     pitcher_name or "",
            "mean_tb":      mean_tb,
            "base_mean_tb": base_mean,
            "rolling_avg":  stats["rolling_avg"],
            "season_avg":   stats["season_avg"],
            "hr_rate":      stats["hr_rate"],
            "hot_streak":   stats["hot_streak"],
            "games":        stats["games"],
            "curve":        curve,
            "p4":           p4,
            "base_p4":      base_p4,
            "context":      reasons,
        })

    return sorted(results, key=lambda x: -x["p4"])
