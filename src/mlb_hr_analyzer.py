"""
MLB Home Run Props Analyzer
Angles: forme récente (15j) + splits vs main lanceur + H2H carrière
Filtre: au moins 2 angles positifs sur 3 pour générer un bet
Edge min: 15% (marché plus difficile que K props)
"""

import math
import time
import requests

MLB_API = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
TIMEOUT = 10

MIN_EDGE_HR    = 15.0   # Plus strict que K props (12%)
MIN_AB_SPLIT   = 60     # AB minimum pour que le split L/R soit significatif
MIN_AB_H2H     = 10     # AB minimum H2H pour avoir de la valeur
HOT_HR_RATE    = 0.08   # > 1 HR tous les 12.5 AB = "hot"
N_RECENT       = 15     # Derniers matchs pour la forme

_pid_cache:    dict = {}
_split_cache:  dict = {}
_h2h_cache:    dict = {}
_hand_cache:   dict = {}
_recent_cache: dict = {}


def _get(url, params):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _get_player_id(name: str):
    key = name.lower().strip()
    if key in _pid_cache:
        return _pid_cache[key]
    data = _get(f"{MLB_API}/people/search", {"names": name, "sportId": 1})
    pid = data["people"][0]["id"] if data and data.get("people") else None
    _pid_cache[key] = pid
    return pid


def _get_pitcher_hand(pitcher_name: str) -> str:
    """Retourne 'L' ou 'R' pour la main du lanceur."""
    key = pitcher_name.lower().strip()
    if key in _hand_cache:
        return _hand_cache[key]
    pid = _get_player_id(pitcher_name)
    if pid is None:
        _hand_cache[key] = "R"  # défaut droitier
        return "R"
    data = _get(f"{MLB_API}/people/{pid}", {})
    hand = "R"
    if data and data.get("people"):
        hand = data["people"][0].get("pitchHand", {}).get("code", "R")
    _hand_cache[key] = hand
    return hand


def _get_recent_hr_rate(batter_id: int) -> dict | None:
    """HR/match sur les N derniers matchs."""
    if batter_id in _recent_cache:
        return _recent_cache[batter_id]
    data = _get(f"{MLB_API}/people/{batter_id}/stats", {
        "stats": "gameLog", "group": "hitting", "season": "2026"
    })
    if not data:
        _recent_cache[batter_id] = None
        return None
    splits = data.get("stats", [{}])[0].get("splits", [])
    recent = splits[-N_RECENT:] if len(splits) >= N_RECENT else splits
    if len(recent) < 5:
        _recent_cache[batter_id] = None
        return None
    hr    = sum(g["stat"].get("homeRuns", 0) for g in recent)
    ab    = sum(g["stat"].get("atBats", 0) for g in recent)
    games = len(recent)
    result = {
        "hr_per_game": round(hr / games, 3),
        "hr_per_ab":   round(hr / ab, 3) if ab else 0,
        "hr_total":    hr,
        "games":       games,
        "ab":          ab,
    }
    _recent_cache[batter_id] = result
    return result


def _get_split_vs_hand(batter_id: int, hand: str) -> dict | None:
    """Stats vs LHP ou RHP cette saison."""
    key = f"{batter_id}_{hand}"
    if key in _split_cache:
        return _split_cache[key]
    sit = "vl" if hand == "L" else "vr"
    data = _get(f"{MLB_API}/people/{batter_id}/stats", {
        "stats": "statSplits", "group": "hitting",
        "season": "2026", "sitCodes": sit,
    })
    result = None
    if data:
        for s in data.get("stats", []):
            for sp in s.get("splits", []):
                stat = sp.get("stat", {})
                ab   = stat.get("atBats", 0)
                hr   = stat.get("homeRuns", 0)
                if ab >= MIN_AB_SPLIT:
                    result = {
                        "hr": hr,
                        "ab": ab,
                        "hr_per_ab": round(hr / ab, 3),
                        "slg":       float(stat.get("slg", "0").lstrip(".").__class__(stat.get("slg", "0")) if stat.get("slg") else 0),
                        "hand":      hand,
                    }
    _split_cache[key] = result
    return result


def _get_h2h(batter_id: int, pitcher_id: int) -> dict | None:
    """H2H carrière frappeur vs lanceur."""
    key = f"{batter_id}_{pitcher_id}"
    if key in _h2h_cache:
        return _h2h_cache[key]
    data = _get(f"{MLB_API}/people/{batter_id}/stats", {
        "stats": "vsPlayerTotal", "group": "hitting",
        "opposingPlayerId": pitcher_id,
    })
    result = None
    if data:
        for s in data.get("stats", []):
            for sp in s.get("splits", []):
                stat = sp.get("stat", {})
                ab   = stat.get("atBats", 0)
                hr   = stat.get("homeRuns", 0)
                if ab >= MIN_AB_H2H:
                    result = {
                        "hr": hr,
                        "ab": ab,
                        "hr_per_ab": round(hr / ab, 3),
                        "avg":       stat.get("avg", ".000"),
                    }
    _h2h_cache[key] = result
    return result


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _prob_over(proj: float, line: float, std_factor: float = 0.85) -> float:
    """P(HR >= line+1) via distribution de Poisson approximée par normale."""
    if proj <= 0:
        return 0.0
    std = max(std_factor * math.sqrt(proj), 0.30)
    return 1 - _normal_cdf((line + 0.5 - proj) / std)


def analyze_hr_props(game: dict, batter_props: list, pitcher_name: str) -> list:
    """
    Analyse les props HR pour un match.
    batter_props: liste de {'player': str, 'line': float, 'dk_odds': float}
    pitcher_name: lanceur adverse
    Retourne une liste de bets qualifiés.
    """
    bets = []

    pitcher_id   = _get_player_id(pitcher_name)
    pitcher_hand = _get_pitcher_hand(pitcher_name)
    time.sleep(0.3)

    for bp in batter_props:
        player = bp.get("player", "")
        line   = bp.get("line", 0.5)
        dk_odds = bp.get("dk_odds", 0)

        if line > 0.5:
            continue  # On joue seulement HR over 0.5 (seuil standard)

        batter_id = _get_player_id(player)
        if batter_id is None:
            continue
        time.sleep(0.2)

        # ── Angle 1: forme récente ──────────────────────────────────────────
        recent   = _get_recent_hr_rate(batter_id)
        angle1_ok = False
        recent_desc = ""
        if recent and recent["games"] >= 5:
            rate = recent["hr_per_ab"]
            angle1_ok = rate >= HOT_HR_RATE
            recent_desc = f"{recent['hr_total']} HR/{recent['games']}j ({rate:.3f}/AB)"

        # ── Angle 2: split vs main lanceur ──────────────────────────────────
        time.sleep(0.2)
        split    = _get_split_vs_hand(batter_id, pitcher_hand)
        angle2_ok = False
        split_desc = ""
        if split:
            # Comparer au taux global (~0.035 HR/AB en MLB)
            MLB_AVG_HR_AB = 0.035
            angle2_ok = split["hr_per_ab"] >= MLB_AVG_HR_AB * 1.3  # 30% au-dessus de la moyenne
            hand_label = "LHP" if pitcher_hand == "L" else "RHP"
            split_desc = f"vs {hand_label}: {split['hr']}/{split['ab']} AB ({split['hr_per_ab']:.3f}/AB)"

        # ── Angle 3: H2H carrière ───────────────────────────────────────────
        time.sleep(0.2)
        h2h      = _get_h2h(batter_id, pitcher_id) if pitcher_id else None
        angle3_ok = False
        h2h_desc  = ""
        if h2h:
            angle3_ok = h2h["hr_per_ab"] >= 0.04  # Mieux que la moyenne vs ce lanceur
            h2h_desc = f"H2H: {h2h['hr']}/{h2h['ab']} AB ({h2h['hr_per_ab']:.3f}/AB) {h2h['avg']} AVG"

        # ── Filtre: min 2 angles positifs sur 3 ────────────────────────────
        angles_ok = sum([angle1_ok, angle2_ok, angle3_ok])
        if angles_ok < 2:
            print(f"    [HR Skip] {player}: {angles_ok}/3 angles ({recent_desc} | {split_desc} | {h2h_desc})")
            continue

        # ── Projection ─────────────────────────────────────────────────────
        proj_rates = []
        if recent and recent["games"] >= 5:
            proj_rates.append(recent["hr_per_game"])
        if split:
            # Convertir HR/AB en HR/match (environ 3.7 AB/match en moyenne)
            proj_rates.append(split["hr_per_ab"] * 3.7)
        if h2h and h2h["ab"] >= MIN_AB_H2H:
            proj_rates.append(h2h["hr_per_ab"] * 3.7)

        proj = sum(proj_rates) / len(proj_rates) if proj_rates else 0.10

        our_prob  = _prob_over(proj, line)
        if dk_odds > 0:
            dk_implied = 1 / dk_odds * 100
        else:
            dk_implied = 28.0  # ~3.57 cotes standard HR over 0.5

        edge = our_prob * 100 - dk_implied
        if edge < MIN_EDGE_HR:
            print(f"    [HR Skip] {player}: edge {edge:.1f}% < {MIN_EDGE_HR}% (proj={proj:.3f})")
            continue

        # ── Kelly fractionné ───────────────────────────────────────────────
        b    = (dk_odds - 1) if dk_odds > 0 else 2.57
        p    = our_prob
        q    = 1 - p
        kelly = max(0, (b * p - q) / b) * 25  # 1/4 Kelly

        context = []
        if angle1_ok and recent_desc:
            context.append(f"Forme: {recent_desc}")
        if angle2_ok and split_desc:
            context.append(split_desc)
        if angle3_ok and h2h_desc:
            context.append(h2h_desc)

        bet = {
            "player":      player,
            "team":        bp.get("team", ""),
            "opponent":    pitcher_name,
            "player_type": "batter",
            "market":      f"Home Run Over {line}",
            "stat_key":    "home_runs",
            "line":        line,
            "proj":        round(proj, 3),
            "our_prob":    round(our_prob * 100, 1),
            "dk_implied":  round(dk_implied, 1),
            "edge_pct":    round(edge, 1),
            "kelly":       round(kelly, 1),
            "est_odds":    dk_odds or 3.57,
            "angles_ok":   angles_ok,
            "context":     context,
        }
        bets.append(bet)
        print(f"    [HR BET] {player}: edge {edge:.1f}%, {angles_ok}/3 angles, proj={proj:.3f}")

    return sorted(bets, key=lambda x: -x["edge_pct"])
