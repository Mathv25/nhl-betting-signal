"""
Props Analyzer - Analyse quotidienne des joueurs cles par match
Fetche les stats reelles NHL.com et calcule les props recommandes
"""

import requests
import time
import math
from typing import Optional

NHL_API = "https://api-web.nhle.com/v1"
SEASON  = "20252026"
GAME_TYPE = "2"

TEAM_ABBR = {
    "Anaheim Ducks":"ANA","Boston Bruins":"BOS","Buffalo Sabres":"BUF",
    "Calgary Flames":"CGY","Carolina Hurricanes":"CAR","Chicago Blackhawks":"CHI",
    "Colorado Avalanche":"COL","Columbus Blue Jackets":"CBJ","Dallas Stars":"DAL",
    "Detroit Red Wings":"DET","Edmonton Oilers":"EDM","Florida Panthers":"FLA",
    "Los Angeles Kings":"LAK","Minnesota Wild":"MIN","Montreal Canadiens":"MTL",
    "Nashville Predators":"NSH","New Jersey Devils":"NJD","New York Islanders":"NYI",
    "New York Rangers":"NYR","Ottawa Senators":"OTT","Philadelphia Flyers":"PHI",
    "Pittsburgh Penguins":"PIT","San Jose Sharks":"SJS","Seattle Kraken":"SEA",
    "St. Louis Blues":"STL","Tampa Bay Lightning":"TBL","Toronto Maple Leafs":"TOR",
    "Utah Mammoth":"UTA","Vancouver Canucks":"VAN","Vegas Golden Knights":"VGK",
    "Washington Capitals":"WSH","Winnipeg Jets":"WPG",
}

DEF_QUALITY = {
    "Carolina Hurricanes":"elite","Florida Panthers":"elite","Boston Bruins":"elite",
    "Dallas Stars":"elite","Colorado Avalanche":"good","Vegas Golden Knights":"good",
    "Winnipeg Jets":"good","Tampa Bay Lightning":"good","Minnesota Wild":"good",
    "Los Angeles Kings":"good","Toronto Maple Leafs":"avg","Edmonton Oilers":"avg",
    "New York Rangers":"avg","New York Islanders":"avg","Washington Capitals":"avg",
    "Seattle Kraken":"avg","Ottawa Senators":"avg","New Jersey Devils":"avg",
    "Pittsburgh Penguins":"avg","Montreal Canadiens":"avg","Vancouver Canucks":"avg",
    "Buffalo Sabres":"weak","Philadelphia Flyers":"weak","Nashville Predators":"weak",
    "Detroit Red Wings":"weak","Calgary Flames":"weak","St. Louis Blues":"weak",
    "Columbus Blue Jackets":"weak","Chicago Blackhawks":"weak","Anaheim Ducks":"weak",
    "San Jose Sharks":"weak","Utah Mammoth":"avg",
}

DEF_FACTORS = {"elite":0.82,"good":0.93,"avg":1.0,"weak":1.12}


def _get(url):
    time.sleep(0.4)
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  Props API: {e}")
        return None


def _pmf(lam, k):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    fact = 1
    for i in range(2, k + 1):
        fact *= i
    return math.exp(-lam) * (lam ** k) / fact


def _poisson_over(lam, line):
    p = sum(_pmf(lam, k) for k in range(int(line) + 1, int(line) + 20))
    return round(min(max(p, 0.05), 0.95), 4)


def _normal_cdf(z):
    t = 1 / (1 + 0.2316419 * abs(z))
    d = 0.3989423 * math.exp(-z * z / 2)
    p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.7814779 + t * (-1.8212560 + t * 1.3302744))))
    return 1 - p if z > 0 else p


class PropsAnalyzer:

    def __init__(self):
        self._roster_cache = {}
        self._stats_cache  = {}

    def analyze_game(self, home_team: str, away_team: str) -> dict:
        """
        Pour un match donne, retourne:
        - Top joueurs a surveiller avec leurs stats
        - Props recommandees (shots, points)
        - Analyse des gardiens
        """
        print(f"  Analyse props: {away_team} @ {home_team}...")

        home_players = self._get_top_players(home_team)
        away_players = self._get_top_players(away_team)
        home_goalie  = self._get_goalie_stats(home_team)
        away_goalie  = self._get_goalie_stats(away_team)

        home_def = DEF_QUALITY.get(home_team, "avg")
        away_def = DEF_QUALITY.get(away_team, "avg")

        props = []

        for p in home_players:
            adj_shots  = p["shots_pg"]  * DEF_FACTORS[away_def]
            adj_points = p["points_pg"] * DEF_FACTORS[away_def]
            props.append(self._build_prop(p, adj_shots, adj_points, home_team, away_team))

        for p in away_players:
            adj_shots  = p["shots_pg"]  * DEF_FACTORS[home_def]
            adj_points = p["points_pg"] * DEF_FACTORS[home_def]
            props.append(self._build_prop(p, adj_shots, adj_points, away_team, home_team))

        props = [p for p in props if p is not None]
        props.sort(key=lambda x: x["shots_pg_adj"], reverse=True)

        # Seulement les joueurs avec vraie opportunite
        props = [p for p in props if p["shots_over_pct"] >= 58 or p["pts_over_pct"] >= 62]
        props = props[:6]

        return {
            "home_team":   home_team,
            "away_team":   away_team,
            "home_goalie": home_goalie,
            "away_goalie": away_goalie,
            "home_def":    home_def,
            "away_def":    away_def,
            "props":       props[:8],
        }

    def _build_prop(self, player, adj_shots, adj_points, team, opponent):
        name = player.get("name","")
        if not name:
            return None

        shots_line  = round(adj_shots * 0.85 * 2) / 2
        shots_line  = max(shots_line, 0.5)
        shots_over  = round(_poisson_over(adj_shots, shots_line) * 100, 1)

        points_line = 0.5
        pts_over    = round(_poisson_over(adj_points, points_line) * 100, 1)

        return {
            "name":          name,
            "team":          team,
            "opponent":      opponent,
            "position":      player.get("position",""),
            "shots_pg":      round(player["shots_pg"], 2),
            "shots_pg_adj":  round(adj_shots, 2),
            "shots_line":    shots_line,
            "shots_over_pct": shots_over,
            "points_pg":     round(player["points_pg"], 2),
            "points_pg_adj": round(adj_points, 2),
            "pts_over_pct":  pts_over,
            "toi":           player.get("toi_str","--"),
            "n_games":       player.get("n_games", 0),
        }

    def _get_top_players(self, team_name: str, top_n: int = 4) -> list:
        abbr = TEAM_ABBR.get(team_name, "")
        if not abbr:
            return []

        if abbr in self._roster_cache:
            roster = self._roster_cache[abbr]
        else:
            data = _get(f"{NHL_API}/roster/{abbr}/current")
            if not data:
                return []
            self._roster_cache[abbr] = data
            roster = data

        players = []
        for group in ["forwards", "defensemen"]:
            for p in roster.get(group, []):
                if p.get("injuryStatus") in ("IR","LTIR","Day-to-Day","Injured"):
                    continue
                pid  = p.get("id")
                fn   = p.get("firstName",{}).get("default","")
                ln   = p.get("lastName",{}).get("default","")
                pos  = p.get("positionCode","")
                stats = self._get_player_stats(pid, fn + " " + ln)
                if stats:
                    stats["name"]     = fn + " " + ln
                    stats["position"] = pos
                    players.append(stats)

        players.sort(key=lambda x: x.get("points_pg", 0), reverse=True)
        return players[:top_n]

    def _get_player_stats(self, player_id: int, name: str) -> Optional[dict]:
        if not player_id:
            return None
        key = str(player_id)
        if key in self._stats_cache:
            return self._stats_cache[key]

        data = _get(f"{NHL_API}/player/{player_id}/game-log/{SEASON}/{GAME_TYPE}")
        if not data:
            return None

        logs = data.get("gameLog", [])[:10]
        if not logs:
            return None

        weights = [math.exp(-0.1 * i) for i in range(len(logs))]
        total_w = sum(weights)

        def wavg(field):
            return sum(logs[i].get(field, 0) * weights[i] for i in range(len(logs))) / total_w

        toi_sec = wavg("toi")
        toi_min = int(toi_sec // 60)
        toi_sec2 = int(toi_sec % 60)

        result = {
            "shots_pg":  round(wavg("shots"), 2),
            "goals_pg":  round(wavg("goals"), 3),
            "assists_pg": round(wavg("assists"), 3),
            "points_pg": round(wavg("points"), 3),
            "toi_str":   f"{toi_min}:{toi_sec2:02d}",
            "n_games":   len(logs),
        }
        self._stats_cache[key] = result
        return result

    def _get_goalie_stats(self, team_name: str) -> dict:
        abbr = TEAM_ABBR.get(team_name, "")
        if not abbr:
            return {}

        if abbr in self._roster_cache:
            roster = self._roster_cache[abbr]
        else:
            data = _get(f"{NHL_API}/roster/{abbr}/current")
            if not data:
                return {}
            self._roster_cache[abbr] = data
            roster = data

        goalies = roster.get("goalies", [])
        if not goalies:
            return {}

        starter = max(goalies, key=lambda g: g.get("gamesPlayed", 0) if isinstance(g.get("gamesPlayed"), int) else 0)
        pid = starter.get("id")
        fn  = starter.get("firstName",{}).get("default","")
        ln  = starter.get("lastName",{}).get("default","")

        stats = self._get_goalie_log(pid)
        stats["name"] = fn + " " + ln
        stats["team"] = team_name
        return stats

    def _get_goalie_log(self, player_id: int) -> dict:
        if not player_id:
            return {"saves_pg":26.0,"sv_pct":0.910,"gaa":2.85}

        data = _get(f"{NHL_API}/player/{player_id}/game-log/{SEASON}/{GAME_TYPE}")
        if not data:
            return {"saves_pg":26.0,"sv_pct":0.910,"gaa":2.85}

        logs = data.get("gameLog", [])[:10]
        if not logs:
            return {"saves_pg":26.0,"sv_pct":0.910,"gaa":2.85}

        weights = [math.exp(-0.1 * i) for i in range(len(logs))]
        total_w = sum(weights)
        def wavg(f):
            return sum(logs[i].get(f, 0) * weights[i] for i in range(len(logs))) / total_w

        return {
            "saves_pg":  round(wavg("saves"), 1),
            "sv_pct":    round(wavg("savePct"), 4) if wavg("savePct") > 0 else 0.910,
            "gaa":       round(wavg("goalsAgainst"), 2),
            "n_games":   len(logs),
        }
