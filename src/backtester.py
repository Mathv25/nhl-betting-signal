"""
Backtester NHL Signal - Resolution automatique via NHL.com API
Tourne chaque nuit apres les matchs pour resoudre les bets du jour.
Persiste les resultats dans docs/results.json
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta
from typing import Optional

NHL_API  = "https://api-web.nhle.com/v1"
RESULTS_PATH = os.path.join(os.path.dirname(__file__), "../docs/results.json")
SIGNAL_PATH  = os.path.join(os.path.dirname(__file__), "../docs/signal.json")

# ── Helpers NHL API ────────────────────────────────────────────────────────────

def _get(url: str, retries: int = 3) -> Optional[dict]:
    for i in range(retries):
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(10)
        except Exception:
            time.sleep(3)
    return None


def get_final_scores(date: str) -> dict:
    """
    Retourne {(home_abbr, away_abbr): {"home_score": int, "away_score": int}}
    pour tous les matchs finaux d'une date donnee (YYYY-MM-DD).
    """
    data = _get(f"{NHL_API}/score/{date}")
    if not data:
        return {}

    results = {}
    for game in data.get("games", []):
        state = game.get("gameState", "")
        # OFF = final, FINAL aussi accepte
        if state not in ("OFF", "FINAL"):
            continue
        home = game.get("homeTeam", {})
        away = game.get("awayTeam", {})
        home_abbr  = home.get("abbrev", "")
        away_abbr  = away.get("abbrev", "")
        home_score = home.get("score", 0)
        away_score = away.get("score", 0)
        if home_abbr and away_abbr:
            results[(home_abbr, away_abbr)] = {
                "home_score": home_score,
                "away_score": away_score,
                "home_abbr":  home_abbr,
                "away_abbr":  away_abbr,
            }
    return results


# ── Mapping noms longs -> abbrev ───────────────────────────────────────────────

TEAM_TO_ABBR = {
    "Anaheim Ducks": "ANA", "Boston Bruins": "BOS", "Buffalo Sabres": "BUF",
    "Calgary Flames": "CGY", "Carolina Hurricanes": "CAR", "Chicago Blackhawks": "CHI",
    "Colorado Avalanche": "COL", "Columbus Blue Jackets": "CBJ", "Dallas Stars": "DAL",
    "Detroit Red Wings": "DET", "Edmonton Oilers": "EDM", "Florida Panthers": "FLA",
    "Los Angeles Kings": "LAK", "Minnesota Wild": "MIN", "Montreal Canadiens": "MTL",
    "Nashville Predators": "NSH", "New Jersey Devils": "NJD", "New York Islanders": "NYI",
    "New York Rangers": "NYR", "Ottawa Senators": "OTT", "Philadelphia Flyers": "PHI",
    "Pittsburgh Penguins": "PIT", "San Jose Sharks": "SJS", "Seattle Kraken": "SEA",
    "St. Louis Blues": "STL", "Tampa Bay Lightning": "TBL", "Toronto Maple Leafs": "TOR",
    "Utah Hockey Club": "UTA", "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK",
    "Washington Capitals": "WSH", "Winnipeg Jets": "WPG",
}


def abbrev_from_game_str(game_str: str) -> tuple[str, str]:
    """
    Extrait (away_abbr, home_abbr) depuis une string du style 'MTL @ TOR'
    ou 'Montreal Canadiens @ Toronto Maple Leafs'.
    """
    if " @ " in game_str:
        parts = game_str.split(" @ ")
        away_part = parts[0].strip()
        home_part = parts[1].strip()
    elif " vs " in game_str.lower():
        parts = game_str.lower().split(" vs ")
        away_part = parts[0].strip()
        home_part = parts[1].strip()
    else:
        return ("", "")

    def resolve(s):
        s_upper = s.upper()
        if len(s_upper) <= 3 and s_upper.isalpha():
            return s_upper
        # Essaie correspondance partielle nom
        for name, abbr in TEAM_TO_ABBR.items():
            if s.lower() in name.lower() or name.lower() in s.lower():
                return abbr
        return s_upper[:3]

    return (resolve(away_part), resolve(home_part))


# ── Resolution d'un bet ────────────────────────────────────────────────────────

def resolve_bet(bet: dict, scores: dict) -> Optional[str]:
    """
    Retourne 'W', 'L', ou None si non resolvable.

    Champs attendus dans bet:
      - game:      "MTL @ TOR" ou "Montreal Canadiens @ Toronto Maple Leafs"
      - bet:       ex. "MTL ML", "TOR -1.5", "Over 6.0", "Under 5.5"
      - b365_odds: float
    """
    game_str = bet.get("game", "")
    bet_str  = bet.get("bet", "")

    away_abbr, home_abbr = abbrev_from_game_str(game_str)
    if not away_abbr or not home_abbr:
        return None

    # Cherche le score dans les resultats
    score = None
    for (h, a), s in scores.items():
        if h == home_abbr and a == away_abbr:
            score = s
            break
        # Fallback partiel
        if home_abbr in h and away_abbr in a:
            score = s
            break

    if score is None:
        return None

    hs = score["home_score"]
    as_ = score["away_score"]
    diff = hs - as_  # positif = home wins

    bet_upper = bet_str.upper()

    # Moneyline home
    if home_abbr in bet_upper and "ML" in bet_upper:
        return "W" if hs > as_ else "L"

    # Moneyline away
    if away_abbr in bet_upper and "ML" in bet_upper:
        return "W" if as_ > hs else "L"

    # Puck line home -1.5
    if home_abbr in bet_upper and "-1.5" in bet_str:
        return "W" if diff >= 2 else "L"

    # Puck line away -1.5
    if away_abbr in bet_upper and "-1.5" in bet_str:
        return "W" if diff <= -2 else "L"

    # Puck line home +1.5
    if home_abbr in bet_upper and "+1.5" in bet_str:
        return "W" if diff >= -1 else "L"

    # Puck line away +1.5
    if away_abbr in bet_upper and "+1.5" in bet_str:
        return "W" if diff <= 1 else "L"

    # Over
    if "OVER" in bet_upper:
        try:
            line = float(bet_str.upper().split("OVER")[1].strip().split()[0])
            return "W" if (hs + as_) > line else "L"
        except Exception:
            pass

    # Under
    if "UNDER" in bet_upper:
        try:
            line = float(bet_str.upper().split("UNDER")[1].strip().split()[0])
            return "W" if (hs + as_) < line else "L"
        except Exception:
            pass

    return None


# ── Chargement / sauvegarde results.json ──────────────────────────────────────

def load_results() -> dict:
    if os.path.exists(RESULTS_PATH):
        try:
            with open(RESULTS_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {"bets": [], "summary": {}}


def save_results(data: dict):
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Calcul du sommaire ─────────────────────────────────────────────────────────

def compute_summary(bets: list) -> dict:
    resolved = [b for b in bets if b.get("result") in ("W", "L")]
    if not resolved:
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "profit": 0.0, "roi": 0.0}

    wins   = sum(1 for b in resolved if b["result"] == "W")
    losses = len(resolved) - wins
    profit = 0.0
    staked = 0.0

    for b in resolved:
        stake_pct = min(b.get("kelly_fraction", 1.0), 3.0)
        odds      = b.get("b365_odds", 2.0)
        stake     = stake_pct  # en unites (% de BR)
        staked   += stake
        if b["result"] == "W":
            profit += stake * (odds - 1)
        else:
            profit -= stake

    roi = (profit / staked * 100) if staked > 0 else 0.0

    # Par categorie d'edge
    by_edge = {}
    for label, lo, hi in [("15+", 15, 999), ("8-15", 8, 15), ("5-8", 5, 8)]:
        subset = [b for b in resolved if lo <= b.get("edge_pct", 0) < hi]
        if not subset:
            continue
        sw = sum(1 for b in subset if b["result"] == "W")
        sp = sum(
            (min(b.get("kelly_fraction", 1), 3) * (b.get("b365_odds", 2) - 1)
             if b["result"] == "W"
             else -min(b.get("kelly_fraction", 1), 3))
            for b in subset
        )
        by_edge[label] = {"n": len(subset), "wins": sw, "profit": round(sp, 2)}

    return {
        "total":    len(resolved),
        "wins":     wins,
        "losses":   losses,
        "win_rate": round(wins / len(resolved) * 100, 1),
        "profit":   round(profit, 2),
        "roi":      round(roi, 1),
        "by_edge":  by_edge,
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def run_for_date(target_date: str):
    """
    Charge le signal.json, fetch les scores NHL pour target_date,
    resout les bets non-resolus, et sauvegarde dans results.json.
    """
    print(f"Backtest live pour {target_date}")

    # Charge le signal
    if not os.path.exists(SIGNAL_PATH):
        print(f"signal.json introuvable: {SIGNAL_PATH}")
        return

    with open(SIGNAL_PATH) as f:
        signal = json.load(f)

    signal_date = signal.get("date", "")[:10]
    value_bets  = signal.get("value_bets", [])

    print(f"  Signal date: {signal_date} | {len(value_bets)} bets")

    # Fetch les scores
    scores = get_final_scores(target_date)
    if not scores:
        print(f"  Aucun score final disponible pour {target_date}")
        return

    print(f"  {len(scores)} match(s) final(aux) trouves")

    # Charge les resultats existants
    results_data = load_results()
    existing_ids = {b.get("id") for b in results_data["bets"]}

    new_bets  = 0
    resolved  = 0

    for bet in value_bets:
        # ID unique = date + bet + game
        bet_id = f"{signal_date}|{bet.get('game','')}|{bet.get('bet','')}"

        if bet_id in existing_ids:
            # Deja enregistre — essaie de resoudre si encore en attente
            for b in results_data["bets"]:
                if b.get("id") == bet_id and b.get("result") == "?":
                    result = resolve_bet(bet, scores)
                    if result:
                        b["result"] = result
                        print(f"    Resolu: {bet.get('game')} | {bet.get('bet')} → {result}")
                        resolved += 1
        else:
            # Nouveau bet
            result = resolve_bet(bet, scores)
            entry = {
                "id":              bet_id,
                "date":            signal_date,
                "game":            bet.get("game", ""),
                "bet":             bet.get("bet", ""),
                "edge_pct":        bet.get("edge_pct", 0),
                "our_prob":        bet.get("our_prob", 0),
                "b365_odds":       bet.get("b365_odds", 0),
                "b365_implied":    bet.get("b365_implied", 0),
                "kelly_fraction":  bet.get("kelly_fraction", 0),
                "result":          result if result else "?",
            }
            results_data["bets"].append(entry)
            new_bets += 1
            if result:
                print(f"    {bet.get('game')} | {bet.get('bet')} → {result}")
                resolved += 1
            else:
                print(f"    {bet.get('game')} | {bet.get('bet')} → en attente")

    # Recalcule le sommaire
    results_data["summary"] = compute_summary(results_data["bets"])

    save_results(results_data)

    print(f"\n  {new_bets} nouveau(x) bet(s) enregistre(s)")
    print(f"  {resolved} bet(s) resolu(s)")
    s = results_data["summary"]
    print(f"  Cumul: {s['total']} bets | WR {s['win_rate']}% | Profit {s['profit']:+.2f}u | ROI {s['roi']:+.1f}%")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        target = sys.argv[1]
    else:
        # Par defaut: hier (les matchs d'hier sont finis ce matin)
        target = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    run_for_date(target)
