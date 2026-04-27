"""
Backtester NHL + NBA + MLB Signal - Resolution automatique complete
- value_bets     : ML / puck line / totals via scores NHL API
- props_analysis : shots / goals / points via game log joueur NHL API
- nba_analysis   : points / rebonds / passes / 3pts via ESPN API (gratuit)
- mlb_analysis   : strikeouts / hits / total bases via MLB Stats API
Persiste dans docs/results.json
"""

import json
import os
import sys
import time
import math
import unicodedata
import requests
from datetime import datetime, timedelta
from typing import Optional

NHL_API      = "https://api-web.nhle.com/v1"
ESPN_NBA     = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
MLB_API      = "https://statsapi.mlb.com/api/v1"
RESULTS_PATH = os.path.join(os.path.dirname(__file__), "../docs/results.json")
SIGNAL_PATH  = os.path.join(os.path.dirname(__file__), "../docs/signal.json")
ARCHIVE_DIR  = os.path.join(os.path.dirname(__file__), "../docs/archive")

# ── Helpers generiques ─────────────────────────────────────────────────────────

def _get(url: str, params: dict = None, retries: int = 3) -> Optional[dict]:
    for i in range(retries):
        try:
            r = requests.get(url, params=params or {}, timeout=15,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(15)
            elif r.status_code == 404:
                return None
        except Exception:
            time.sleep(3)
    return None

# ── Mapping equipes ────────────────────────────────────────────────────────────

# Abbrevs du scores API NHL (different du roster API)
TEAM_NAME_TO_SCORE_ABBR = {
    "Anaheim Ducks": "ANA", "Boston Bruins": "BOS", "Buffalo Sabres": "BUF",
    "Calgary Flames": "CGY", "Carolina Hurricanes": "CAR", "Chicago Blackhawks": "CHI",
    "Colorado Avalanche": "COL", "Columbus Blue Jackets": "CBJ", "Dallas Stars": "DAL",
    "Detroit Red Wings": "DET", "Edmonton Oilers": "EDM", "Florida Panthers": "FLA",
    "Los Angeles Kings": "LAK",
    "Minnesota Wild": "MIN", "Montreal Canadiens": "MTL", "Montréal Canadiens": "MTL",
    "Nashville Predators": "NSH", "New Jersey Devils": "NJD",
    "New York Islanders": "NYI", "New York Rangers": "NYR", "Ottawa Senators": "OTT",
    "Philadelphia Flyers": "PHI", "Pittsburgh Penguins": "PIT",
    "San Jose Sharks": "SJS",
    "Seattle Kraken": "SEA", "St Louis Blues": "STL", "St. Louis Blues": "STL",
    "Tampa Bay Lightning": "TBL",
    "Toronto Maple Leafs": "TOR", "Utah Hockey Club": "UTA", "Utah Mammoth": "UTA",
    "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK",
    "Washington Capitals": "WSH", "Winnipeg Jets": "WPG",
}

# Abbrevs du roster API NHL
TEAM_NAME_TO_ROSTER_ABBR = {
    "Anaheim Ducks": "ANA", "Boston Bruins": "BOS", "Buffalo Sabres": "BUF",
    "Calgary Flames": "CGY", "Carolina Hurricanes": "CAR", "Chicago Blackhawks": "CHI",
    "Colorado Avalanche": "COL", "Columbus Blue Jackets": "CBJ", "Dallas Stars": "DAL",
    "Detroit Red Wings": "DET", "Edmonton Oilers": "EDM", "Florida Panthers": "FLA",
    "Los Angeles Kings": "LAK", "Minnesota Wild": "MIN",
    "Montreal Canadiens": "MTL", "Montréal Canadiens": "MTL",
    "Nashville Predators": "NSH", "New Jersey Devils": "NJD",
    "New York Islanders": "NYI", "New York Rangers": "NYR", "Ottawa Senators": "OTT",
    "Philadelphia Flyers": "PHI", "Pittsburgh Penguins": "PIT", "San Jose Sharks": "SJS",
    "Seattle Kraken": "SEA", "St Louis Blues": "STL", "St. Louis Blues": "STL",
    "Tampa Bay Lightning": "TBL", "Toronto Maple Leafs": "TOR",
    "Utah Hockey Club": "UTA", "Utah Mammoth": "UTA",
    "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK",
    "Washington Capitals": "WSH", "Winnipeg Jets": "WPG",
}

# Mapping stat BallDontLie
NBA_STAT_MAP = {
    "player_points":                  "pts",
    "player_rebounds":                "reb",
    "player_assists":                 "ast",
    "player_threes":                  "fg3m",
    "player_points_rebounds_assists": "pra",
}

# ── Scores NHL ─────────────────────────────────────────────────────────────────

def get_nhl_scores(date: str) -> dict:
    """Retourne {(home_abbr, away_abbr): {home_score, away_score}} pour matchs finaux."""
    data = _get(f"{NHL_API}/score/{date}")
    if not data:
        return {}

    results = {}
    for game in data.get("games", []):
        if game.get("gameState") not in ("OFF", "FINAL"):
            continue
        home      = game.get("homeTeam", {})
        away      = game.get("awayTeam", {})
        home_abbr = home.get("abbrev", "")
        away_abbr = away.get("abbrev", "")
        if home_abbr and away_abbr:
            results[(home_abbr, away_abbr)] = {
                "home_score": home.get("score", 0),
                "away_score": away.get("score", 0),
            }
    return results


def name_to_score_abbr(name: str) -> str:
    abbr = TEAM_NAME_TO_SCORE_ABBR.get(name, "")
    if abbr:
        return abbr
    name_l = name.lower()
    for full, a in TEAM_NAME_TO_SCORE_ABBR.items():
        if name_l in full.lower() or full.lower() in name_l:
            return a
    return ""


def parse_game_str(game_str: str):
    """'Away @ Home' -> (away_abbr, home_abbr) pour scores API."""
    if " @ " in game_str:
        away_name, home_name = game_str.split(" @ ", 1)
        return name_to_score_abbr(away_name.strip()), name_to_score_abbr(home_name.strip())
    return "", ""


def find_nhl_score(game_str: str, scores: dict) -> Optional[dict]:
    away_abbr, home_abbr = parse_game_str(game_str)
    if not away_abbr or not home_abbr:
        return None
    # Correspondance exacte
    if (home_abbr, away_abbr) in scores:
        return scores[(home_abbr, away_abbr)]
    # Orientation inversee dans l'archive (home/away swap) — retourne score corrige
    if (away_abbr, home_abbr) in scores:
        s = scores[(away_abbr, home_abbr)]
        return {"home_score": s["away_score"], "away_score": s["home_score"]}
    # Fallback partiel
    for (h, a), s in scores.items():
        if home_abbr in h and away_abbr in a:
            return s
        if away_abbr in h and home_abbr in a:
            return {"home_score": s["away_score"], "away_score": s["home_score"]}
    return None

# ── Resolution bets equipe NHL ─────────────────────────────────────────────────

def resolve_team_bet(bet: dict, scores: dict) -> Optional[str]:
    game_str = bet.get("game", "")
    bet_str  = bet.get("bet", "")
    score    = find_nhl_score(game_str, scores)
    if score is None:
        return None

    hs   = score["home_score"]
    as_  = score["away_score"]
    diff = hs - as_

    away_name, home_name = ("", "")
    if " @ " in game_str:
        away_name, home_name = game_str.split(" @ ", 1)
        away_name = away_name.strip()
        home_name = home_name.strip()

    home_abbr = name_to_score_abbr(home_name)
    away_abbr = name_to_score_abbr(away_name)
    bet_upper = bet_str.upper()

    def is_home():
        return (home_abbr and home_abbr in bet_upper) or \
               any(w.upper() in bet_upper for w in home_name.split()[-2:] if len(w) > 2)

    def is_away():
        return (away_abbr and away_abbr in bet_upper) or \
               any(w.upper() in bet_upper for w in away_name.split()[-2:] if len(w) > 2)

    if "ML" in bet_upper:
        if is_home(): return "W" if hs > as_ else "L"
        if is_away(): return "W" if as_ > hs else "L"

    if "-1.5" in bet_str:
        if is_home(): return "W" if diff >= 2 else "L"
        if is_away(): return "W" if diff <= -2 else "L"

    if "+1.5" in bet_str:
        if is_home(): return "W" if diff >= -1 else "L"
        if is_away(): return "W" if diff <= 1 else "L"

    if "OVER" in bet_upper:
        try:
            line = float(bet_str.upper().split("OVER")[1].strip().split()[0])
            return "W" if (hs + as_) > line else "L"
        except Exception:
            pass

    if "UNDER" in bet_upper:
        try:
            line = float(bet_str.upper().split("UNDER")[1].strip().split()[0])
            return "W" if (hs + as_) < line else "L"
        except Exception:
            pass

    return None

# ── Resolution props NHL joueurs ───────────────────────────────────────────────

_nhl_roster_cache = {}

def get_nhl_player_id(player_name: str, team_name: str) -> Optional[int]:
    roster_abbr = TEAM_NAME_TO_ROSTER_ABBR.get(team_name, "")
    if not roster_abbr:
        for full, a in TEAM_NAME_TO_ROSTER_ABBR.items():
            if team_name.lower() in full.lower() or full.lower() in team_name.lower():
                roster_abbr = a
                break
    if not roster_abbr:
        return None

    if roster_abbr not in _nhl_roster_cache:
        data = _get(f"{NHL_API}/roster/{roster_abbr}/current")
        time.sleep(0.5)
        if not data:
            return None
        cache = {}
        for pos_group in ["forwards", "defensemen", "goalies"]:
            for p in data.get(pos_group, []):
                fn   = p.get("firstName", {}).get("default", "")
                ln   = p.get("lastName",  {}).get("default", "")
                full = f"{fn} {ln}".strip().lower()
                pid  = p.get("id")
                if full and pid:
                    cache[full] = pid
        _nhl_roster_cache[roster_abbr] = cache

    cache      = _nhl_roster_cache[roster_abbr]
    name_lower = player_name.strip().lower()
    if name_lower in cache:
        return cache[name_lower]
    # Match partiel sur nom de famille
    last = name_lower.split()[-1] if name_lower else ""
    for full_name, pid in cache.items():
        if last and last in full_name:
            return pid
    return None


def get_nhl_player_game_stats(player_id: int, target_date: str,
                               expected_home: str = "", expected_away: str = "") -> Optional[dict]:
    """Retourne les stats du joueur sur target_date.
    Si expected_home/away fournis, valide que le match correspond aux bonnes equipes
    (evite de resoudre un prop avec les stats d'un match different)."""
    data = _get(f"{NHL_API}/player/{player_id}/game-log/20252026/2")
    time.sleep(0.3)
    if not data:
        return None

    def _abbrevs_match(game_str: str, home_abbr: str, away_abbr: str) -> bool:
        """Verifie que home_abbr et away_abbr sont dans la chaine de jeu NHL API."""
        gs = game_str.upper()
        return home_abbr.upper() in gs and away_abbr.upper() in gs

    for game in data.get("gameLog", []):
        if game.get("gameDate", "")[:10] != target_date:
            continue

        # Validation des equipes si fournie
        if expected_home and expected_away:
            h_abbr = TEAM_NAME_TO_ROSTER_ABBR.get(expected_home, "")
            a_abbr = TEAM_NAME_TO_ROSTER_ABBR.get(expected_away, "")
            opp    = game.get("opponentAbbrev", "")
            team_a = game.get("teamAbbrev", "")
            if h_abbr and a_abbr:
                game_abbrevs = {opp.upper(), team_a.upper()}
                expected_abbrevs = {h_abbr.upper(), a_abbr.upper()}
                if not game_abbrevs.issubset(expected_abbrevs | {""}):
                    print(f"    ⚠ Match differe: {team_a} vs {opp} (attendu: {h_abbr} vs {a_abbr}) — skip")
                    return None

        shots   = game.get("shots",  0) or 0
        goals   = game.get("goals",  0) or 0
        assists = game.get("assists", 0) or 0
        sa      = game.get("shotsAgainst", 0) or 0
        ga      = game.get("goalsAgainst", 0) or 0
        return {
            "shots":  shots,
            "goals":  goals,
            "points": goals + assists,
            "saves":  max(0, sa - ga),
        }
    return None


def resolve_nhl_prop(prop: dict, target_date: str) -> Optional[str]:
    name        = prop.get("name", "")
    team        = prop.get("team", "")
    market      = prop.get("market", "")
    market_type = prop.get("market_type", "")
    game_home   = prop.get("_game_home", "")
    game_away   = prop.get("_game_away", "")
    if not name or not team or not market:
        return None

    player_id = get_nhl_player_id(name, team)
    if not player_id:
        print(f"    ⚠ ID NHL introuvable: {name} ({team})")
        return None

    stats = get_nhl_player_game_stats(player_id, target_date, game_home, game_away)
    if not stats:
        print(f"    ⚠ Stats NHL introuvables: {name} pour {target_date}")
        return None

    # Parser "Shots Over 2.5" -> direction=over, line=2.5
    m_upper   = market.upper()
    direction = "over" if "OVER" in m_upper else "under"
    try:
        clean = market.replace("Over","").replace("over","").replace("Under","").replace("under","")
        for word in ["Shots","Buts","Goals","Points","Saves","Shot","Goal","Point","Save"]:
            clean = clean.replace(word, "").replace(word.upper(), "")
        line = float(clean.strip())
    except Exception:
        return None

    if market_type == "shots" or "SHOT" in m_upper:
        actual = stats["shots"]
    elif market_type == "goals" or "BUT" in m_upper or "GOAL" in m_upper:
        actual = stats["goals"]
    elif market_type == "points" or "POINT" in m_upper:
        actual = stats["points"]
    elif market_type == "saves" or "SAVE" in m_upper:
        actual = stats["saves"]
    else:
        actual = stats["points"]

    print(f"    {name}: {market_type}={actual} vs {line} ({direction}) -> ", end="")
    result = "W" if (actual > line if direction == "over" else actual < line) else "L"
    print(result)
    return result

# ── Resolution props NBA joueurs via ESPN API ──────────────────────────────────

_espn_nba_cache: dict = {}  # {date_str: {player_name_lower: {pts,reb,ast,fg3m}}}


def _espn_date_fmt(date_str: str) -> str:
    return date_str.replace("-", "")


def _load_espn_nba_date(target_date: str) -> dict:
    """Charge toutes les stats NBA pour une date via ESPN boxscore API.
    Retourne {player_name_lower: {pts, reb, ast, fg3m}}."""
    if target_date in _espn_nba_cache:
        return _espn_nba_cache[target_date]

    all_player_stats: dict = {}

    # 1. Scoreboard → liste des event IDs
    scoreboard = _get(f"{ESPN_NBA}/scoreboard", {"dates": _espn_date_fmt(target_date)})
    if not scoreboard:
        _espn_nba_cache[target_date] = all_player_stats
        return all_player_stats

    events = scoreboard.get("events", [])
    print(f"    ESPN NBA: {len(events)} match(s) le {target_date}")

    for event in events:
        game_id = event.get("id")
        if not game_id:
            continue
        time.sleep(0.4)
        summary = _get(f"{ESPN_NBA}/summary", {"event": game_id})
        if not summary:
            continue

        # 2. Parser le boxscore
        for team_data in summary.get("boxscore", {}).get("players", []):
            for stats_block in team_data.get("statistics", []):
                names = stats_block.get("names", [])
                if not names:
                    continue
                idx = {n: i for i, n in enumerate(names)}

                for athlete in stats_block.get("athletes", []):
                    player_name = athlete.get("athlete", {}).get("displayName", "")
                    raw_stats   = athlete.get("stats", [])
                    if not player_name or not raw_stats:
                        continue

                    def _parse(key: str) -> int:
                        i = idx.get(key)
                        if i is None or i >= len(raw_stats):
                            return 0
                        val = str(raw_stats[i])
                        if "-" in val:          # "3-9" format (3PT, FG, FT)
                            try:
                                return int(val.split("-")[0])
                            except Exception:
                                return 0
                        try:
                            return int(val)
                        except Exception:
                            return 0

                    all_player_stats[player_name.lower()] = {
                        "pts":  _parse("PTS"),
                        "reb":  _parse("REB"),
                        "ast":  _parse("AST"),
                        "fg3m": _parse("3PT"),
                    }

    _espn_nba_cache[target_date] = all_player_stats
    return all_player_stats


def _infer_nba_stat_key(market: str) -> str:
    """Infere le stat_key NBA depuis le libelle du marche (robuste aux erreurs de stockage)."""
    m = market.lower()
    if "rebond" in m or " reb" in m:
        return "reb"
    if "passe" in m or "assist" in m:
        return "ast"
    if "3pt" in m or "trois" in m or "thre" in m:
        return "fg3m"
    if "pra" in m or "pts+reb" in m:
        return "pra"
    return "pts"  # defaut: points


def resolve_nba_prop(bet: dict, target_date: str) -> Optional[str]:
    """Resout un bet NBA prop via ESPN boxscore."""
    bet_str  = bet.get("bet", "")
    market   = bet.get("market", "")
    name     = bet.get("name", "")
    stat_key = bet.get("stat_key", "pts")

    if not name and " — " in bet_str:
        name = bet_str.split(" — ")[0].strip()
    if not name:
        return None

    # Parser direction et ligne
    m_upper   = market.upper() if market else bet_str.upper()
    direction = "over" if "OVER" in m_upper else "under"
    line = bet.get("line", 0) or 0
    if not line:
        try:
            clean = m_upper
            for word in ["POINTS", "REBONDS", "PASSES", "3PTS", "PRA", "OVER", "UNDER"]:
                clean = clean.replace(word, "")
            line = float(clean.strip())
        except Exception:
            return None

    # Charger toutes les stats ESPN pour la date
    all_stats = _load_espn_nba_date(target_date)

    # Chercher le joueur (exact puis par nom de famille)
    player_stats = all_stats.get(name.lower())
    if not player_stats:
        last = name.lower().split()[-1] if name else ""
        for pname, pstats in all_stats.items():
            if last and len(last) > 3 and pname.split()[-1] == last:
                player_stats = pstats
                break

    if not player_stats:
        print(f"    ⚠ Stats NBA ESPN introuvables: {name} pour {target_date}")
        return None

    if stat_key == "pra":
        actual = player_stats.get("pts", 0) + player_stats.get("reb", 0) + player_stats.get("ast", 0)
    else:
        actual = player_stats.get(stat_key, 0)
    print(f"    {name}: {stat_key}={actual} vs {line} ({direction}) -> ", end="")
    result = "W" if (actual > line if direction == "over" else actual < line) else "L"
    print(result)
    return result

# ── Resolution props MLB ───────────────────────────────────────────────────────

_mlb_game_pk_cache = {}


def _team_name_match(api_name: str, our_name: str) -> bool:
    """Compare noms d'equipes MLB (tolerant aux variantes mineures)."""
    a = api_name.lower().strip()
    b = our_name.lower().strip()
    if a == b:
        return True
    # Dernier mot (ex: "Yankees" dans "New York Yankees")
    last_a = a.split()[-1]
    last_b = b.split()[-1]
    return last_a == last_b


def _normalize(s: str) -> str:
    """Supprime les accents et met en minuscules."""
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii").lower().strip()


def _player_name_match(api_name: str, our_name: str) -> bool:
    """Match joueur MLB: exact ou par nom de famille (tolerant aux accents et suffixes Jr./Sr.)."""
    a = _normalize(api_name)
    b = _normalize(our_name)
    if a == b:
        return True
    # Supprimer suffixes Jr./Sr./II/III
    for suffix in (" jr.", " sr.", " ii", " iii", " iv"):
        a = a.replace(suffix, "")
        b = b.replace(suffix, "")
    a = a.strip()
    b = b.strip()
    if a == b:
        return True
    last_a = a.split()[-1] if a else ""
    last_b = b.split()[-1] if b else ""
    first_a = a.split()[0] if a else ""
    first_b = b.split()[0] if b else ""
    # Meme nom de famille + meme initiale prenom
    if last_a == last_b and len(last_a) > 3 and first_a and first_b and first_a[0] == first_b[0]:
        return True
    return False


def get_mlb_game_pk(home_team: str, away_team: str, target_date: str) -> Optional[int]:
    """Trouve le gamePk MLB pour un matchup et une date."""
    cache_key = f"{target_date}|{home_team}|{away_team}"
    if cache_key in _mlb_game_pk_cache:
        return _mlb_game_pk_cache[cache_key]

    data = _get(f"{MLB_API}/schedule", {
        "sportId": 1,
        "date":    target_date,
        "hydrate": "team",
    })
    if not data:
        _mlb_game_pk_cache[cache_key] = None
        return None

    for d in data.get("dates", []):
        for game in d.get("games", []):
            h_name = game.get("teams", {}).get("home", {}).get("team", {}).get("name", "")
            a_name = game.get("teams", {}).get("away", {}).get("team", {}).get("name", "")
            if _team_name_match(h_name, home_team) and _team_name_match(a_name, away_team):
                pk = game.get("gamePk")
                _mlb_game_pk_cache[cache_key] = pk
                return pk

    _mlb_game_pk_cache[cache_key] = None
    return None


def resolve_mlb_prop(prop: dict, target_date: str) -> Optional[str]:
    """Resout un prop MLB via le boxscore MLB Stats API."""
    player    = prop.get("player", "")
    stat_key  = prop.get("stat_key", "")
    line      = prop.get("line", 0)
    game_home = prop.get("_game_home", "")
    game_away = prop.get("_game_away", "")

    if not player or not stat_key or not game_home:
        return None

    game_pk = get_mlb_game_pk(game_home, game_away, target_date)
    if not game_pk:
        print(f"    ⚠ Game MLB introuvable: {game_away} @ {game_home} ({target_date})")
        return None

    time.sleep(0.5)
    boxscore = _get(f"{MLB_API}/game/{game_pk}/boxscore")
    if not boxscore:
        print(f"    ⚠ Boxscore MLB introuvable: gamePk={game_pk}")
        return None

    # Chercher le joueur dans home et away
    for side in ("home", "away"):
        players = boxscore.get("teams", {}).get(side, {}).get("players", {})
        for pid, pdata in players.items():
            api_name = pdata.get("person", {}).get("fullName", "")
            if not _player_name_match(api_name, player):
                continue

            stats    = pdata.get("stats", {})
            batting  = stats.get("batting",  {})
            pitching = stats.get("pitching", {})

            if stat_key == "hits":
                actual = batting.get("hits", None)
            elif stat_key == "total_bases":
                actual = batting.get("totalBases", None)
            elif stat_key == "strikeouts":
                actual = pitching.get("strikeOuts", None)
            elif stat_key == "home_runs":
                actual = batting.get("homeRuns", None)
            else:
                return None

            if actual is None:
                print(f"    ⚠ Stat {stat_key} absente pour {player}")
                return None

            result = "W" if actual > line else "L"
            print(f"    {player}: {stat_key}={actual} vs {line} -> {result}")
            return result

    print(f"    ⚠ Joueur MLB introuvable dans boxscore: {player}")
    return None


# ── Persistance ────────────────────────────────────────────────────────────────

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

# ── Sommaire ───────────────────────────────────────────────────────────────────

def compute_summary(bets: list) -> dict:
    resolved = [b for b in bets if b.get("result") in ("W", "L")]
    if not resolved:
        return {
            "total": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "profit": 0.0, "roi": 0.0, "by_edge": {}, "by_type": {},
            "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    wins   = sum(1 for b in resolved if b["result"] == "W")
    profit = 0.0
    staked = 0.0

    for b in resolved:
        stake = min(b.get("kelly_fraction", 1.0), 3.0)
        odds  = b.get("b365_odds", 2.0)
        staked += stake
        profit += stake * (odds - 1) if b["result"] == "W" else -stake

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
             if b["result"] == "W" else -min(b.get("kelly_fraction", 1), 3))
            for b in subset
        )
        by_edge[label] = {"n": len(subset), "wins": sw, "profit": round(sp, 2)}

    # Par type de bet
    by_type = {}
    for b in resolved:
        sport = b.get("sport", "nhl")
        btype = b.get("market_type", b.get("bet_type", "team"))
        key   = f"{sport}_{btype}"
        if key not in by_type:
            by_type[key] = {"n": 0, "wins": 0, "profit": 0.0}
        stake = min(b.get("kelly_fraction", 1.0), 3.0)
        odds  = b.get("b365_odds", 2.0)
        by_type[key]["n"] += 1
        if b["result"] == "W":
            by_type[key]["wins"]   += 1
            by_type[key]["profit"] = round(by_type[key]["profit"] + stake * (odds - 1), 2)
        else:
            by_type[key]["profit"] = round(by_type[key]["profit"] - stake, 2)

    # Par sport (agrege)
    by_sport: dict = {}
    for b in resolved:
        sport = b.get("sport", "nhl")
        if sport not in by_sport:
            by_sport[sport] = {"n": 0, "wins": 0, "losses": 0, "profit": 0.0}
        stake = min(b.get("kelly_fraction", 1.0), 3.0)
        odds  = b.get("b365_odds", 2.0)
        by_sport[sport]["n"] += 1
        if b["result"] == "W":
            by_sport[sport]["wins"]   += 1
            by_sport[sport]["profit"]  = round(by_sport[sport]["profit"] + stake * (odds - 1), 2)
        else:
            by_sport[sport]["losses"] += 1
            by_sport[sport]["profit"]  = round(by_sport[sport]["profit"] - stake, 2)

    return {
        "total":    len(resolved),
        "wins":     wins,
        "losses":   len(resolved) - wins,
        "win_rate": round(wins / len(resolved) * 100, 1),
        "profit":   round(profit, 2),
        "roi":      round(roi, 1),
        "by_edge":  by_edge,
        "by_type":  by_type,
        "by_sport": by_sport,
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

# ── Re-resolution des bets en attente ─────────────────────────────────────────

def _parse_game_str(game_str: str):
    """'Away @ Home' -> (home, away)"""
    if " @ " in game_str:
        away, home = game_str.split(" @ ", 1)
        return home.strip(), away.strip()
    return "", ""


def _parse_line_from_str(s: str) -> float:
    """Extrait la ligne numerique depuis 'Over 5.5' ou 'Points Over 25.5'."""
    import re
    m = re.search(r"(\d+\.?\d*)\s*$", s.strip())
    if m:
        return float(m.group(1))
    # Chercher apres Over/Under
    m2 = re.search(r"(?:over|under)\s+(\d+\.?\d*)", s, re.IGNORECASE)
    if m2:
        return float(m2.group(1))
    return 0.0


def retry_unresolved(results_data: dict, max_days: int = 14) -> int:
    """
    Retente la resolution de tous les bets '?' des derniers max_days jours.
    Groupe par date et sport pour minimiser les appels API.
    Retourne le nombre de bets nouvellement resolus.
    """
    from datetime import date as date_cls, timedelta

    cutoff    = (datetime.utcnow().date() - timedelta(days=max_days)).isoformat()
    pending   = [
        b for b in results_data["bets"]
        if b.get("result") == "?" and b.get("date", "") >= cutoff
    ]

    if not pending:
        print("  Aucun bet en attente dans les 14 derniers jours.")
        return 0

    # Grouper par date
    by_date = {}
    for b in pending:
        by_date.setdefault(b["date"], []).append(b)

    total_resolved = 0

    for target_date in sorted(by_date.keys()):
        bets_for_date = by_date[target_date]
        print(f"\n  Retry {target_date}: {len(bets_for_date)} bets en attente")

        # Scores NHL (une seule fois par date)
        nhl_scores = get_nhl_scores(target_date)

        for bet in bets_for_date:
            sport    = bet.get("sport", "nhl")
            bet_type = bet.get("bet_type", "team")
            result   = None

            try:
                if sport == "nhl" and bet_type == "team":
                    result = resolve_team_bet(bet, nhl_scores)

                elif sport == "nhl" and bet_type == "prop":
                    home, away = _parse_game_str(bet.get("game", ""))
                    # Extraire market depuis le champ bet "Name — Market"
                    bet_str = bet.get("bet", "")
                    market  = bet_str.split(" — ", 1)[1].strip() if " — " in bet_str else ""
                    prop = {
                        "name":        bet.get("name", ""),
                        "team":        bet.get("team", ""),
                        "market":      market,
                        "market_type": bet.get("market_type", ""),
                        "_game_home":  home,
                        "_game_away":  away,
                    }
                    result = resolve_nhl_prop(prop, target_date)

                elif sport == "nba":
                    bet_str  = bet.get("bet", "")
                    market   = bet_str.split(" — ", 1)[1].strip() if " — " in bet_str else ""
                    # Inferer le stat_key depuis le libelle (market_type stocke peut etre "pts" par erreur)
                    stat_key = _infer_nba_stat_key(market)
                    line     = bet.get("line", 0) or _parse_line_from_str(market)
                    prop = {
                        "name":     bet.get("name", ""),
                        "market":   market,
                        "stat_key": stat_key,
                        "line":     line,
                    }
                    result = resolve_nba_prop(prop, target_date)

                elif sport == "mlb":
                    home, away = _parse_game_str(bet.get("game", ""))
                    bet_str  = bet.get("bet", "")
                    market   = bet_str.split(" — ", 1)[1].strip() if " — " in bet_str else ""
                    line     = bet.get("line", 0) or _parse_line_from_str(market)
                    stat_key = bet.get("market_type", "")
                    prop = {
                        "player":     bet.get("name", ""),
                        "stat_key":   stat_key,
                        "line":       line,
                        "market":     market,
                        "_game_home": home,
                        "_game_away": away,
                    }
                    result = resolve_mlb_prop(prop, target_date)

            except Exception as e:
                print(f"    ⚠ Erreur retry {bet.get('id','?')}: {e}")
                continue

            if result in ("W", "L"):
                bet["result"] = result
                total_resolved += 1
                print(f"    ✓ Resolu: {bet.get('name', bet.get('bet',''))[:40]} → {result}")

    return total_resolved


# ── Main ───────────────────────────────────────────────────────────────────────

def run_for_date(target_date: str):
    print(f"\n{'='*60}")
    print(f"BACKTEST {target_date}")
    print(f"{'='*60}")

    # Charger le signal (archive en priorite)
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
    nba_by_game   = signal.get("nba_analysis", [])
    mlb_by_game   = signal.get("mlb_analysis", [])

    # Collecter tous les NHL props
    all_nhl_props = []
    for game_analysis in props_by_game:
        home = game_analysis.get("home_team", "")
        away = game_analysis.get("away_team", "")
        for b in game_analysis.get("bets", []):
            b = dict(b)
            b["_game_home"] = home
            b["_game_away"] = away
            all_nhl_props.append(b)

    # Collecter tous les NBA props
    all_nba_props = []
    for game_analysis in nba_by_game:
        home = game_analysis.get("home_team", "")
        away = game_analysis.get("away_team", "")
        for b in game_analysis.get("bets", []):
            b = dict(b)
            b["_game_home"] = home
            b["_game_away"] = away
            all_nba_props.append(b)

    # Collecter tous les MLB props
    all_mlb_props = []
    for game_analysis in mlb_by_game:
        home = game_analysis.get("home_team", "")
        away = game_analysis.get("away_team", "")
        for b in game_analysis.get("bets", []):
            b = dict(b)
            b["_game_home"] = home
            b["_game_away"] = away
            all_mlb_props.append(b)

    print(f"NHL value bets:  {len(value_bets)}")
    print(f"NHL props:       {len(all_nhl_props)}")
    print(f"NBA props:       {len(all_nba_props)}")
    print(f"MLB props:       {len(all_mlb_props)}")
    print(f"TOTAL:           {len(value_bets) + len(all_nhl_props) + len(all_nba_props) + len(all_mlb_props)}")

    # Scores NHL
    print(f"\nFetch scores NHL {target_date}...")
    nhl_scores = get_nhl_scores(target_date)
    print(f"{len(nhl_scores)} match(s) final(aux) NHL")
    for (h, a), s in nhl_scores.items():
        print(f"  {a} @ {h}: {s['away_score']}-{s['home_score']}")

    results_data = load_results()
    existing_ids = {b.get("id") for b in results_data["bets"]}
    new_count    = 0
    res_count    = 0

    def upsert(bet_id, entry):
        nonlocal new_count, res_count
        # Cherche si deja present
        for existing in results_data["bets"]:
            if existing.get("id") == bet_id:
                if existing.get("result") not in ("W", "L") and entry.get("result") in ("W", "L"):
                    existing["result"] = entry["result"]
                    res_count += 1
                return
        results_data["bets"].append(entry)
        existing_ids.add(bet_id)
        new_count += 1
        if entry.get("result") in ("W", "L"):
            res_count += 1

    # ── 1. NHL value bets ──────────────────────────────────────────────────────
    print(f"\n--- NHL VALUE BETS ({len(value_bets)}) ---")
    for bet in value_bets:
        bet_id = f"{target_date}|{bet.get('game','')}|{bet.get('bet','')}"
        result = resolve_team_bet(bet, nhl_scores) if nhl_scores else None
        status = result or "?"
        print(f"  {bet.get('bet')} → {status}")
        upsert(bet_id, {
            "id":             bet_id,
            "date":           target_date,
            "sport":          "nhl",
            "bet_type":       "team",
            "market_type":    bet.get("type", "").lower(),
            "game":           bet.get("game", ""),
            "bet":            bet.get("bet", ""),
            "edge_pct":       bet.get("edge_pct", 0),
            "our_prob":       bet.get("our_prob", 0),
            "b365_odds":      bet.get("b365_odds", 0),
            "b365_implied":   bet.get("b365_implied", 0),
            "kelly_fraction": bet.get("kelly_fraction", 0),
            "result":         result or "?",
        })

    # ── 2. NHL props ───────────────────────────────────────────────────────────
    print(f"\n--- NHL PROPS ({len(all_nhl_props)}) ---")
    for prop in all_nhl_props:
        name   = prop.get("name", "")
        market = prop.get("market", "")
        bet_id = f"{target_date}|prop_nhl|{name}|{market}"
        game_str = f"{prop.get('_game_away','')} @ {prop.get('_game_home','')}"
        print(f"  {name} | {market}")
        result = resolve_nhl_prop(prop, target_date)
        upsert(bet_id, {
            "id":             bet_id,
            "date":           target_date,
            "sport":          "nhl",
            "bet_type":       "prop",
            "market_type":    prop.get("market_type", ""),
            "game":           game_str,
            "name":           name,
            "team":           prop.get("team", ""),
            "bet":            f"{name} — {market}",
            "edge_pct":       prop.get("edge_pct", 0),
            "our_prob":       prop.get("our_prob", 0),
            "b365_odds":      prop.get("est_odds", 0),
            "b365_implied":   prop.get("b365_implied", 0),
            "kelly_fraction": prop.get("kelly", 0),
            "result":         result or "?",
        })

    # ── 3. NBA props ───────────────────────────────────────────────────────────
    if all_nba_props:
        print(f"\n--- NBA PROPS ({len(all_nba_props)}) ---")
        for prop in all_nba_props:
            player = prop.get("player", "")
            market = prop.get("market", "")
            bet_id = f"{target_date}|prop_nba|{player}|{market}"
            game_str = f"{prop.get('_game_away','')} @ {prop.get('_game_home','')}"

            # stat_key directement depuis le prop (set par NBAPropsAnalyzer)
            # Ne pas utiliser NBA_STAT_MAP avec market_raw=None (tombe toujours sur "pts")
            prop["name"] = player
            if not prop.get("stat_key"):
                prop["stat_key"] = _infer_nba_stat_key(market)

            print(f"  {player} | {market}")
            result = resolve_nba_prop(prop, target_date)
            upsert(bet_id, {
                "id":             bet_id,
                "date":           target_date,
                "sport":          "nba",
                "bet_type":       "prop",
                "market_type":    prop.get("stat_key", "pts"),
                "game":           game_str,
                "name":           player,
                "team":           prop.get("team", ""),
                "bet":            f"{player} — {market}",
                "line":           prop.get("line", 0),
                "edge_pct":       prop.get("edge_pct", 0),
                "our_prob":       prop.get("our_prob", 0),
                "b365_odds":      prop.get("est_odds", prop.get("b365_odds", 0)),
                "b365_implied":   prop.get("dk_implied", prop.get("b365_implied", 0)),
                "kelly_fraction": prop.get("kelly", prop.get("kelly_fraction", 0)),
                "result":         result or "?",
            })

    # ── 4. MLB props ───────────────────────────────────────────────────────────
    if all_mlb_props:
        print(f"\n--- MLB PROPS ({len(all_mlb_props)}) ---")
        for prop in all_mlb_props:
            player   = prop.get("player", "")
            market   = prop.get("market", "")
            stat_key = prop.get("stat_key", "")
            bet_id   = f"{target_date}|prop_mlb|{player}|{market}"
            game_str = f"{prop.get('_game_away','')} @ {prop.get('_game_home','')}"

            print(f"  {player} | {market}")
            result = resolve_mlb_prop(prop, target_date)
            upsert(bet_id, {
                "id":             bet_id,
                "date":           target_date,
                "sport":          "mlb",
                "bet_type":       "prop",
                "market_type":    stat_key,
                "game":           game_str,
                "name":           player,
                "team":           prop.get("team", ""),
                "line":           prop.get("line", 0),
                "bet":            f"{player} — {market}",
                "edge_pct":       prop.get("edge_pct", 0),
                "our_prob":       prop.get("our_prob", 0),
                "b365_odds":      prop.get("est_odds", prop.get("b365_odds", 0)),
                "b365_implied":   prop.get("dk_implied", prop.get("b365_implied", 0)),
                "kelly_fraction": prop.get("kelly", prop.get("kelly_fraction", 0)),
                "result":         result or "?",
            })

    # Sommaire partiel + save intermediaire
    results_data["summary"] = compute_summary(results_data["bets"])
    save_results(results_data)

    s = results_data["summary"]
    print(f"\n{'='*60}")
    print(f"Nouveaux: {new_count} | Resolus ce run: {res_count}")
    print(f"Cumul: {s['total']} bets | WR {s['win_rate']}% | Profit {s['profit']:+.2f}u | ROI {s['roi']:+.1f}%")
    if s.get("by_type"):
        print("Par type:")
        for t, info in sorted(s["by_type"].items()):
            wr = round(info["wins"] / info["n"] * 100) if info["n"] else 0
            print(f"  {t}: {info['n']} bets | {wr}% WR | {info['profit']:+.2f}u")

    # Re-resolution des bets en attente (14 derniers jours)
    print(f"\n{'='*60}")
    print("RETRY — bets non-resolus (14 derniers jours)")
    print(f"{'='*60}")
    newly_resolved = retry_unresolved(results_data)
    print(f"\n  {newly_resolved} bet(s) supplementaire(s) resolus")

    # Sommaire final + save
    results_data["summary"] = compute_summary(results_data["bets"])
    save_results(results_data)
    s2 = results_data["summary"]
    print(f"  Cumul final: {s2['total']} bets | WR {s2['win_rate']}% | ROI {s2['roi']:+.1f}%")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        target = sys.argv[1]
    else:
        target = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    run_for_date(target)
