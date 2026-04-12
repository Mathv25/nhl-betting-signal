"""
Backtester NHL Signal - Resolution automatique complete
- value_bets : ML / puck line / totals via scores NHL
- props_analysis : shots / goals / points via game log joueur NHL API
Persiste dans docs/results.json
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta
from typing import Optional

NHL_API      = "https://api-web.nhle.com/v1"
RESULTS_PATH = os.path.join(os.path.dirname(__file__), "../docs/results.json")
SIGNAL_PATH  = os.path.join(os.path.dirname(__file__), "../docs/signal.json")
ARCHIVE_DIR  = os.path.join(os.path.dirname(__file__), "../docs/archive")

# ── Helpers ────────────────────────────────────────────────────────────────────

def _get(url: str, retries: int = 3) -> Optional[dict]:
    for i in range(retries):
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(15)
            elif r.status_code == 404:
                return None
        except Exception:
            time.sleep(3)
    return None

# ── Mapping noms complets -> abbrev scores API ────────────────────────────────
# Les abbrevs du scores API sont differentes des abbrevs standard NHL

TEAM_NAME_TO_SCORE_ABBR = {
    "Anaheim Ducks":          "ANA",
    "Boston Bruins":          "BOS",
    "Buffalo Sabres":         "BUF",
    "Calgary Flames":         "CGY",
    "Carolina Hurricanes":    "CAR",
    "Chicago Blackhawks":     "CHI",
    "Colorado Avalanche":     "COL",
    "Columbus Blue Jackets":  "CBJ",
    "Dallas Stars":           "DAL",
    "Detroit Red Wings":      "DET",
    "Edmonton Oilers":        "EDM",
    "Florida Panthers":       "FLA",
    "Los Angeles Kings":      "LA",   # Scores API utilise "LA" pas "LAK"
    "Minnesota Wild":         "MIN",
    "Montreal Canadiens":     "MTL",
    "Montréal Canadiens":     "MTL",
    "Nashville Predators":    "NSH",
    "New Jersey Devils":      "NJ",   # Scores API utilise "NJ" pas "NJD"
    "New York Islanders":     "NYI",
    "New York Rangers":       "NYR",
    "Ottawa Senators":        "OTT",
    "Philadelphia Flyers":    "PHI",
    "Pittsburgh Penguins":    "PIT",
    "San Jose Sharks":        "SJ",   # Scores API utilise "SJ" pas "SJS"
    "Seattle Kraken":         "SEA",
    "St Louis Blues":         "STL",
    "St. Louis Blues":        "STL",
    "Tampa Bay Lightning":    "TB",   # Scores API utilise "TB" pas "TBL"
    "Toronto Maple Leafs":    "TOR",
    "Utah Hockey Club":       "UTA",
    "Utah Mammoth":           "UTA",
    "Vancouver Canucks":      "VAN",
    "Vegas Golden Knights":   "VGK",
    "Washington Capitals":    "WSH",
    "Winnipeg Jets":          "WPG",
}

# Abbrevs roster NHL API (differentes du scores API)
TEAM_NAME_TO_ROSTER_ABBR = {
    "Anaheim Ducks":          "ANA",
    "Boston Bruins":          "BOS",
    "Buffalo Sabres":         "BUF",
    "Calgary Flames":         "CGY",
    "Carolina Hurricanes":    "CAR",
    "Chicago Blackhawks":     "CHI",
    "Colorado Avalanche":     "COL",
    "Columbus Blue Jackets":  "CBJ",
    "Dallas Stars":           "DAL",
    "Detroit Red Wings":      "DET",
    "Edmonton Oilers":        "EDM",
    "Florida Panthers":       "FLA",
    "Los Angeles Kings":      "LAK",
    "Minnesota Wild":         "MIN",
    "Montreal Canadiens":     "MTL",
    "Montréal Canadiens":     "MTL",
    "Nashville Predators":    "NSH",
    "New Jersey Devils":      "NJD",
    "New York Islanders":     "NYI",
    "New York Rangers":       "NYR",
    "Ottawa Senators":        "OTT",
    "Philadelphia Flyers":    "PHI",
    "Pittsburgh Penguins":    "PIT",
    "San Jose Sharks":        "SJS",
    "Seattle Kraken":         "SEA",
    "St Louis Blues":         "STL",
    "St. Louis Blues":        "STL",
    "Tampa Bay Lightning":    "TBL",
    "Toronto Maple Leafs":    "TOR",
    "Utah Hockey Club":       "UTA",
    "Utah Mammoth":           "UTA",
    "Vancouver Canucks":      "VAN",
    "Vegas Golden Knights":   "VGK",
    "Washington Capitals":    "WSH",
    "Winnipeg Jets":          "WPG",
}

# ── Scores finaux ──────────────────────────────────────────────────────────────

def get_final_scores(date: str) -> dict:
    """
    Retourne {(home_abbr, away_abbr): {"home_score": int, "away_score": int}}
    pour tous les matchs finaux d'une date donnee.
    """
    data = _get(f"{NHL_API}/score/{date}")
    if not data:
        return {}

    results = {}
    for game in data.get("games", []):
        state = game.get("gameState", "")
        if state not in ("OFF", "FINAL"):
            continue
        home      = game.get("homeTeam", {})
        away      = game.get("awayTeam", {})
        home_abbr = home.get("abbrev", "")
        away_abbr = away.get("abbrev", "")
        home_score = home.get("score", 0)
        away_score = away.get("score", 0)
        if home_abbr and away_abbr:
            results[(home_abbr, away_abbr)] = {
                "home_score": home_score,
                "away_score": away_score,
            }
    return results


def team_to_score_abbr(name: str) -> str:
    """Convertit un nom d'equipe en abbrev du scores API."""
    abbr = TEAM_NAME_TO_SCORE_ABBR.get(name, "")
    if abbr:
        return abbr
    # Fallback: cherche correspondance partielle
    name_lower = name.lower()
    for full, a in TEAM_NAME_TO_SCORE_ABBR.items():
        if name_lower in full.lower() or full.lower() in name_lower:
            return a
    return ""


def parse_game_string(game_str: str):
    """
    Parse 'Away Team @ Home Team' -> (away_abbr, home_abbr) pour scores API.
    """
    if " @ " in game_str:
        parts     = game_str.split(" @ ")
        away_name = parts[0].strip()
        home_name = parts[1].strip()
        return team_to_score_abbr(away_name), team_to_score_abbr(home_name)
    return "", ""


def find_score(game_str: str, scores: dict) -> Optional[dict]:
    """Cherche le score d'un match dans les scores disponibles."""
    away_abbr, home_abbr = parse_game_string(game_str)
    if not away_abbr or not home_abbr:
        return None

    # Match exact
    if (home_abbr, away_abbr) in scores:
        return scores[(home_abbr, away_abbr)]

    # Match partiel (fallback)
    for (h, a), s in scores.items():
        if home_abbr in h and away_abbr in a:
            return s
        if h in home_abbr and a in away_abbr:
            return s

    return None


# ── Resolution bets ML / puck line / totals ────────────────────────────────────

def resolve_team_bet(bet: dict, scores: dict) -> Optional[str]:
    """Retourne 'W', 'L', ou None."""
    game_str = bet.get("game", "")
    bet_str  = bet.get("bet", "")
    score    = find_score(game_str, scores)

    if score is None:
        return None

    hs  = score["home_score"]
    as_ = score["away_score"]
    diff = hs - as_  # positif = home wins

    # Extraire l'equipe du bet
    away_name, home_name = ("", "")
    if " @ " in game_str:
        parts     = game_str.split(" @ ")
        away_name = parts[0].strip()
        home_name = parts[1].strip()

    away_abbr = team_to_score_abbr(away_name)
    home_abbr = team_to_score_abbr(home_name)

    bet_upper = bet_str.upper()

    # Determine si le bet cible l'equipe home ou away
    # On cherche l'abbrev ou une partie du nom dans le bet
    bet_is_home = (home_abbr and home_abbr in bet_upper) or \
                  (home_name and any(w.upper() in bet_upper for w in home_name.split()[-2:]))
    bet_is_away = (away_abbr and away_abbr in bet_upper) or \
                  (away_name and any(w.upper() in bet_upper for w in away_name.split()[-2:]))

    # Moneyline
    if "ML" in bet_upper:
        if bet_is_home:
            return "W" if hs > as_ else "L"
        if bet_is_away:
            return "W" if as_ > hs else "L"

    # Puck line -1.5
    if "-1.5" in bet_str:
        if bet_is_home:
            return "W" if diff >= 2 else "L"
        if bet_is_away:
            return "W" if diff <= -2 else "L"

    # Puck line +1.5
    if "+1.5" in bet_str:
        if bet_is_home:
            return "W" if diff >= -1 else "L"
        if bet_is_away:
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


# ── Resolution props joueurs ───────────────────────────────────────────────────

# Cache roster: {team_abbr: {player_name_lower: player_id}}
_roster_cache = {}

def get_player_id(player_name: str, team_name: str) -> Optional[int]:
    """Trouve l'ID NHL d'un joueur via le roster de son equipe."""
    roster_abbr = TEAM_NAME_TO_ROSTER_ABBR.get(team_name, "")
    if not roster_abbr:
        # Fallback: cherche partiel
        for full, a in TEAM_NAME_TO_ROSTER_ABBR.items():
            if team_name.lower() in full.lower() or full.lower() in team_name.lower():
                roster_abbr = a
                break
    if not roster_abbr:
        return None

    if roster_abbr not in _roster_cache:
        data = _get(f"{NHL_API}/roster/{roster_abbr}/current")
        time.sleep(0.5)
        if not data:
            return None
        cache = {}
        for pos_group in ["forwards", "defensemen", "goalies"]:
            for p in data.get(pos_group, []):
                fn   = p.get("firstName", {}).get("default", "")
                ln   = p.get("lastName", {}).get("default", "")
                full = f"{fn} {ln}".strip().lower()
                pid  = p.get("id")
                if full and pid:
                    cache[full] = pid
        _roster_cache[roster_abbr] = cache

    cache      = _roster_cache[roster_abbr]
    name_lower = player_name.strip().lower()

    # Match exact
    if name_lower in cache:
        return cache[name_lower]

    # Match partiel (nom de famille)
    last = name_lower.split()[-1] if name_lower else ""
    for full_name, pid in cache.items():
        if last and last in full_name:
            return pid

    return None


def get_player_game_stats(player_id: int, target_date: str) -> Optional[dict]:
    """
    Retourne les stats du joueur pour le match joue a target_date.
    Stats: shots, goals, points, saves.
    """
    data = _get(f"{NHL_API}/player/{player_id}/game-log/20252026/2")
    time.sleep(0.3)
    if not data:
        return None

    for game in data.get("gameLog", []):
        game_date = game.get("gameDate", "")[:10]
        if game_date == target_date:
            shots  = game.get("shots", 0) or 0
            goals  = game.get("goals", 0) or 0
            assists = game.get("assists", 0) or 0
            points = goals + assists
            saves  = game.get("saves", None)
            if saves is None:
                shots_against = game.get("shotsAgainst", 0) or 0
                goals_against = game.get("goalsAgainst", 0) or 0
                saves = max(0, shots_against - goals_against)
            return {
                "shots":  shots,
                "goals":  goals,
                "points": points,
                "saves":  saves,
                "date":   game_date,
            }

    return None


def resolve_prop_bet(bet: dict, target_date: str) -> Optional[str]:
    """
    Resout un prop bet joueur.
    bet doit avoir: name, team, market, market_type
    """
    name        = bet.get("name", "")
    team        = bet.get("team", "")
    market      = bet.get("market", "")  # ex: "Shots Over 2.5"
    market_type = bet.get("market_type", "")  # shots / goals / points / saves

    if not name or not team or not market:
        return None

    # Trouver l'ID du joueur
    player_id = get_player_id(name, team)
    if not player_id:
        print(f"    ⚠ ID introuvable: {name} ({team})")
        return None

    # Recuperer les stats
    stats = get_player_game_stats(player_id, target_date)
    if not stats:
        print(f"    ⚠ Stats introuvables: {name} pour {target_date}")
        return None

    # Parser le marche: "Shots Over 2.5" -> type=shots, direction=over, line=2.5
    market_upper = market.upper()
    direction    = "over" if "OVER" in market_upper else "under"

    # Extraire la ligne numerique
    try:
        parts = market.replace("Over", "").replace("over", "").replace("Under", "").replace("under", "")
        parts = parts.replace("Shots", "").replace("Buts", "").replace("Goals", "")
        parts = parts.replace("Points", "").replace("Saves", "").strip()
        line  = float(parts)
    except Exception:
        return None

    # Determiner la stat a comparer
    if market_type == "shots" or "SHOT" in market_upper:
        actual = stats["shots"]
    elif market_type == "goals" or "BUT" in market_upper or "GOAL" in market_upper:
        actual = stats["goals"]
    elif market_type == "points" or "POINT" in market_upper:
        actual = stats["points"]
    elif market_type == "saves" or "SAVE" in market_upper:
        actual = stats["saves"]
    else:
        return None

    print(f"    {name}: {market_type}={actual} vs ligne {line} → ", end="")

    if direction == "over":
        result = "W" if actual > line else "L"
    else:
        result = "W" if actual < line else "L"

    print(result)
    return result


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
        return {
            "total": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "profit": 0.0, "roi": 0.0,
            "by_edge": {}, "by_type": {},
            "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    wins   = sum(1 for b in resolved if b["result"] == "W")
    losses = len(resolved) - wins
    profit = 0.0
    staked = 0.0

    for b in resolved:
        stake_pct = min(b.get("kelly_fraction", 1.0), 3.0)
        odds      = b.get("b365_odds", 2.0)
        staked   += stake_pct
        if b["result"] == "W":
            profit += stake_pct * (odds - 1)
        else:
            profit -= stake_pct

    roi = (profit / staked * 100) if staked > 0 else 0.0

    # Par tranche d'edge
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

    # Par type de bet
    by_type = {}
    for b in resolved:
        t  = b.get("bet_type", "team")
        mt = b.get("market_type", "")
        key = mt if t == "prop" else t
        if key not in by_type:
            by_type[key] = {"n": 0, "wins": 0, "profit": 0.0}
        stake_pct = min(b.get("kelly_fraction", 1.0), 3.0)
        by_type[key]["n"] += 1
        if b["result"] == "W":
            by_type[key]["wins"]   += 1
            by_type[key]["profit"] += round(stake_pct * (b.get("b365_odds", 2) - 1), 2)
        else:
            by_type[key]["profit"] -= stake_pct
        by_type[key]["profit"] = round(by_type[key]["profit"], 2)

    return {
        "total":    len(resolved),
        "wins":     wins,
        "losses":   losses,
        "win_rate": round(wins / len(resolved) * 100, 1),
        "profit":   round(profit, 2),
        "roi":      round(roi, 1),
        "by_edge":  by_edge,
        "by_type":  by_type,
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def run_for_date(target_date: str):
    print(f"\n{'='*60}")
    print(f"BACKTEST {target_date}")
    print(f"{'='*60}")

    # Charger le signal - priorite archive
    archive_path = os.path.join(ARCHIVE_DIR, f"signal_{target_date}.json")
    if os.path.exists(archive_path):
        signal_file = archive_path
        print(f"Archive: signal_{target_date}.json")
    elif os.path.exists(SIGNAL_PATH):
        signal_file = SIGNAL_PATH
        print(f"Signal courant: signal.json")
    else:
        print(f"Aucun signal pour {target_date}")
        return

    with open(signal_file) as f:
        signal = json.load(f)

    value_bets    = signal.get("value_bets", [])
    props_by_game = signal.get("props_analysis", [])

    # Collecter TOUS les props de tous les matchs
    all_props = []
    for game_analysis in props_by_game:
        home = game_analysis.get("home_team", "")
        away = game_analysis.get("away_team", "")
        for b in game_analysis.get("bets", []):
            b["_game_home"] = home
            b["_game_away"] = away
            all_props.append(b)

    print(f"Value bets:  {len(value_bets)}")
    print(f"Props:       {len(all_props)}")
    print(f"TOTAL:       {len(value_bets) + len(all_props)}")

    # Fetch scores finaux
    print(f"\nFetch scores {target_date}...")
    scores = get_final_scores(target_date)
    print(f"{len(scores)} match(s) final(aux) trouves")
    for (h, a), s in scores.items():
        print(f"  {a} @ {h}: {s['away_score']}-{s['home_score']}")

    # Charger resultats existants
    results_data = load_results()
    existing_ids = {b.get("id") for b in results_data["bets"]}

    new_count      = 0
    resolved_count = 0

    # ── 1. Resoudre value_bets (team bets) ────────────────────────────────────
    print(f"\n--- VALUE BETS ({len(value_bets)}) ---")
    for bet in value_bets:
        bet_id = f"{target_date}|{bet.get('game','')}|{bet.get('bet','')}"

        # Deja resolu?
        already_resolved = False
        for existing in results_data["bets"]:
            if existing.get("id") == bet_id:
                if existing.get("result") in ("W", "L"):
                    already_resolved = True
                    break
                # Essayer de resoudre
                result = resolve_team_bet(bet, scores) if scores else None
                if result:
                    existing["result"] = result
                    print(f"  Resolu: {bet.get('bet')} → {result}")
                    resolved_count += 1
                break

        if already_resolved:
            continue

        if bet_id not in existing_ids:
            result = resolve_team_bet(bet, scores) if scores else None
            entry = {
                "id":             bet_id,
                "date":           target_date,
                "bet_type":       "team",
                "market_type":    bet.get("type", "").lower(),
                "game":           bet.get("game", ""),
                "bet":            bet.get("bet", ""),
                "edge_pct":       bet.get("edge_pct", 0),
                "our_prob":       bet.get("our_prob", 0),
                "b365_odds":      bet.get("b365_odds", 0),
                "b365_implied":   bet.get("b365_implied", 0),
                "kelly_fraction": bet.get("kelly_fraction", 0),
                "result":         result if result else "?",
            }
            results_data["bets"].append(entry)
            existing_ids.add(bet_id)
            new_count += 1
            status = result if result else "en attente"
            print(f"  {bet.get('bet')} → {status}")
            if result:
                resolved_count += 1

    # ── 2. Resoudre props joueurs ─────────────────────────────────────────────
    print(f"\n--- PROPS JOUEURS ({len(all_props)}) ---")
    for prop in all_props:
        name        = prop.get("name", "")
        team        = prop.get("team", "")
        market      = prop.get("market", "")
        market_type = prop.get("market_type", "")
        game_str    = f"{prop.get('_game_away','')} @ {prop.get('_game_home','')}"
        bet_id      = f"{target_date}|prop|{name}|{market}"

        already_resolved = False
        for existing in results_data["bets"]:
            if existing.get("id") == bet_id:
                if existing.get("result") in ("W", "L"):
                    already_resolved = True
                    break
                # Essayer de resoudre
                result = resolve_prop_bet(prop, target_date)
                if result:
                    existing["result"] = result
                    resolved_count += 1
                break

        if already_resolved:
            continue

        if bet_id not in existing_ids:
            print(f"  {name} | {market}")
            result = resolve_prop_bet(prop, target_date)
            entry = {
                "id":             bet_id,
                "date":           target_date,
                "bet_type":       "prop",
                "market_type":    market_type,
                "game":           game_str,
                "bet":            f"{name} — {market}",
                "edge_pct":       prop.get("edge_pct", 0),
                "our_prob":       prop.get("our_prob", 0),
                "b365_odds":      prop.get("est_odds", 0),
                "b365_implied":   prop.get("b365_implied", 0),
                "kelly_fraction": prop.get("kelly", 0),
                "result":         result if result else "?",
            }
            results_data["bets"].append(entry)
            existing_ids.add(bet_id)
            new_count += 1
            if result:
                resolved_count += 1

    # Sommaire
    results_data["summary"] = compute_summary(results_data["bets"])
    save_results(results_data)

    s = results_data["summary"]
    print(f"\n{'='*60}")
    print(f"Nouveaux: {new_count} | Resolus: {resolved_count}")
    print(f"Cumul: {s['total']} bets | WR {s['win_rate']}% | Profit {s['profit']:+.2f}u | ROI {s['roi']:+.1f}%")
    if s.get("by_type"):
        print("Par type:")
        for t, info in s["by_type"].items():
            wr = round(info["wins"]/info["n"]*100) if info["n"] else 0
            print(f"  {t}: {info['n']} bets | {wr}% WR | {info['profit']:+.2f}u")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        target = sys.argv[1]
    else:
        target = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

    run_for_date(target)
