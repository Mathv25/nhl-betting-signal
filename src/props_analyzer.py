"""
Props Analyzer - Analyse approfondie des joueurs cles par match
Stats reelles NHL.com: shots, buts, points avec contexte defensif
"""

import requests
import time
import math
from typing import Optional

NHL_API   = "https://api-web.nhle.com/v1"
SEASON    = "20252026"
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

# Rang defensif par equipe - shots accordes/match (saison courante)
DEF_SHOTS_ALLOWED = {
    "Carolina Hurricanes":   26.1, "Boston Bruins":         27.0,
    "Florida Panthers":      27.3, "Dallas Stars":          27.5,
    "Colorado Avalanche":    28.2, "Vegas Golden Knights":  28.4,
    "Winnipeg Jets":         28.6, "Tampa Bay Lightning":   28.8,
    "Minnesota Wild":        29.0, "Los Angeles Kings":     29.2,
    "Toronto Maple Leafs":   29.8, "Edmonton Oilers":       30.1,
    "New York Rangers":      30.3, "New York Islanders":    30.5,
    "Washington Capitals":   30.8, "Seattle Kraken":        31.0,
    "Ottawa Senators":       31.2, "New Jersey Devils":     31.4,
    "Pittsburgh Penguins":   31.6, "Montreal Canadiens":    31.8,
    "Vancouver Canucks":     32.0, "Buffalo Sabres":        32.5,
    "Philadelphia Flyers":   32.8, "Nashville Predators":   33.0,
    "Detroit Red Wings":     33.2, "Calgary Flames":        33.5,
    "St. Louis Blues":       33.8, "Columbus Blue Jackets": 34.0,
    "Chicago Blackhawks":    34.5, "Anaheim Ducks":         34.8,
    "San Jose Sharks":       35.2, "Utah Mammoth":          31.5,
}

# Rang offensif par equipe - buts accordes/match
DEF_GA_ALLOWED = {
    "Carolina Hurricanes":   2.45, "Boston Bruins":         2.60,
    "Florida Panthers":      2.65, "Dallas Stars":          2.70,
    "Colorado Avalanche":    2.80, "Vegas Golden Knights":  2.85,
    "Winnipeg Jets":         2.88, "Tampa Bay Lightning":   2.92,
    "Minnesota Wild":        2.95, "Los Angeles Kings":     3.00,
    "Toronto Maple Leafs":   3.05, "Edmonton Oilers":       3.10,
    "New York Rangers":      3.12, "New York Islanders":    3.15,
    "Washington Capitals":   3.18, "Seattle Kraken":        3.20,
    "Ottawa Senators":       3.22, "New Jersey Devils":     3.25,
    "Pittsburgh Penguins":   3.28, "Montreal Canadiens":    3.30,
    "Vancouver Canucks":     3.32, "Buffalo Sabres":        3.40,
    "Philadelphia Flyers":   3.42, "Nashville Predators":   3.45,
    "Detroit Red Wings":     3.48, "Calgary Flames":        3.50,
    "St. Louis Blues":       3.55, "Columbus Blue Jackets": 3.60,
    "Chicago Blackhawks":    3.68, "Anaheim Ducks":         3.72,
    "San Jose Sharks":       3.80, "Utah Mammoth":          3.25,
}

LEAGUE_AVG_SHOTS = 31.0
LEAGUE_AVG_GA    = 3.10

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

DEF_LABELS = {
    "elite": ("Elite (top 4)", "#0F6E56"),
    "good":  ("Bonne (top 10)", "#2563EB"),
    "avg":   ("Moyenne", "#6B7280"),
    "weak":  ("Faible (bot 10)", "#B45309"),
}


def _get(url):
    time.sleep(0.5)
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
    return round(min(max(p, 0.02), 0.98) * 100, 1)


def _build_reason(player_name, shots_pg, shots_adj, goals_pg, goals_adj,
                  points_pg, points_adj, def_quality, opponent,
                  last5_shots, last5_goals, last5_points, n_games):
    reasons = []

    # Tendance shots (last 5 vs prev 5)
    if n_games >= 8:
        if last5_shots > shots_pg * 1.15:
            reasons.append("en feu aux shots (last 5 au-dessus de sa moyenne)")
        elif last5_shots < shots_pg * 0.80:
            reasons.append("froid aux shots recemment (last 5 sous sa moyenne)")

    # Defense adverse pour shots
    opp_shots = DEF_SHOTS_ALLOWED.get(opponent, LEAGUE_AVG_SHOTS)
    if opp_shots > LEAGUE_AVG_SHOTS + 2.5:
        reasons.append(f"{opponent[:15]} accorde {opp_shots:.1f} shots/match (bot-5 ligue)")
    elif opp_shots < LEAGUE_AVG_SHOTS - 2.5:
        reasons.append(f"{opponent[:15]} n'accorde que {opp_shots:.1f} shots/match (top-5 ligue)")

    # Defense adverse pour buts
    opp_ga = DEF_GA_ALLOWED.get(opponent, LEAGUE_AVG_GA)
    if opp_ga > LEAGUE_AVG_GA + 0.4:
        reasons.append(f"defense poreuse ({opp_ga:.2f} buts accordes/match)")

    # Tendance buts last 5
    if n_games >= 5:
        goals_per_last5 = last5_goals
        if goals_per_last5 >= 3:
            reasons.append(f"{goals_per_last5} buts dans ses 5 derniers matchs")
        elif goals_per_last5 == 0 and goals_pg > 0.3:
            reasons.append("en manque de buts recemment (regression possible)")

    # Tendance points last 5
    if n_games >= 5:
        pts_per_last5 = last5_points
        if pts_per_last5 >= 5:
            reasons.append(f"{pts_per_last5} pts dans ses 5 derniers matchs")

    # Boost/reduction shots selon defense
    boost = round((shots_adj / shots_pg - 1) * 100) if shots_pg > 0 else 0
    if boost >= 10:
        reasons.append(f"shots projetes +{boost}% vs defense adverse")
    elif boost <= -10:
        reasons.append(f"shots projetes {boost}% vs defense adverse")

    if not reasons:
        reasons.append(f"stats stables ({shots_pg:.1f} shots/match, {points_pg:.2f} pts/match)")

    return " · ".join(reasons[:3])


class PropsAnalyzer:

    def __init__(self):
        self._roster_cache = {}
        self._stats_cache  = {}

    def analyze_game(self, home_team: str, away_team: str) -> dict:
        print(f"  Analyse props: {away_team} @ {home_team}...")

        home_players = self._get_top_players(home_team, away_team)
        away_players = self._get_top_players(away_team, home_team)
        home_goalie  = self._get_goalie_stats(home_team)
        away_goalie  = self._get_goalie_stats(away_team)

        home_def = DEF_QUALITY.get(home_team, "avg")
        away_def = DEF_QUALITY.get(away_team, "avg")

        props = []
        for p in home_players:
            prop = self._build_prop(p, away_team, home_team)
            if prop:
                props.append(prop)
        for p in away_players:
            prop = self._build_prop(p, home_team, away_team)
            if prop:
                props.append(prop)

        props.sort(key=lambda x: x["shots_over_pct"], reverse=True)

        return {
            "home_team":   home_team,
            "away_team":   away_team,
            "home_goalie": home_goalie,
            "away_goalie": away_goalie,
            "home_def":    home_def,
            "away_def":    away_def,
            "home_def_shots": DEF_SHOTS_ALLOWED.get(home_team, LEAGUE_AVG_SHOTS),
            "away_def_shots": DEF_SHOTS_ALLOWED.get(away_team, LEAGUE_AVG_SHOTS),
            "home_def_ga":    DEF_GA_ALLOWED.get(home_team, LEAGUE_AVG_GA),
            "away_def_ga":    DEF_GA_ALLOWED.get(away_team, LEAGUE_AVG_GA),
            "props":       props[:10],
        }

    def _build_prop(self, player: dict, opponent: str, playing_for: str) -> Optional[dict]:
        name = player.get("name", "")
        if not name:
            return None

        shots_pg  = player["shots_pg"]
        goals_pg  = player["goals_pg"]
        points_pg = player["points_pg"]

        # Facteur defensif base sur shots accordes vs moyenne ligue
        opp_shots_allowed = DEF_SHOTS_ALLOWED.get(opponent, LEAGUE_AVG_SHOTS)
        opp_ga_allowed    = DEF_GA_ALLOWED.get(opponent, LEAGUE_AVG_GA)

        shots_factor  = opp_shots_allowed / LEAGUE_AVG_SHOTS
        goals_factor  = opp_ga_allowed    / LEAGUE_AVG_GA

        shots_adj  = round(shots_pg  * shots_factor, 2)
        goals_adj  = round(goals_pg  * goals_factor, 2)
        points_adj = round(points_pg * ((shots_factor + goals_factor) / 2), 2)

        # Lignes standard DK
        shots_line  = max(round(shots_adj * 0.85 * 2) / 2, 0.5)
        goals_line  = 0.5
        points_line = 0.5

        shots_over_pct  = _poisson_over(shots_adj, shots_line)
        goals_over_pct  = _poisson_over(goals_adj, goals_line)
        points_over_pct = _poisson_over(points_adj, points_line)

        reason = _build_reason(
            name, shots_pg, shots_adj, goals_pg, goals_adj,
            points_pg, points_adj,
            DEF_QUALITY.get(opponent, "avg"), opponent,
            player.get("last5_shots", 0),
            player.get("last5_goals", 0),
            player.get("last5_points", 0),
            player.get("n_games", 0),
        )

        return {
            "name":             name,
            "position":         player.get("position", ""),
            "team":             playing_for,
            "opponent":         opponent,
            "toi":              player.get("toi_str", "--"),
            "n_games":          player.get("n_games", 0),
            # Shots
            "shots_pg":         round(shots_pg, 2),
            "shots_pg_adj":     shots_adj,
            "shots_line":       shots_line,
            "shots_over_pct":   shots_over_pct,
            # Buts
            "goals_pg":         round(goals_pg, 3),
            "goals_pg_adj":     goals_adj,
            "goals_line":       goals_line,
            "goals_over_pct":   goals_over_pct,
            # Points
            "points_pg":        round(points_pg, 3),
            "points_pg_adj":    points_adj,
            "points_line":      points_line,
            "points_over_pct":  points_over_pct,
            # Tendance last 5
            "last5_shots":      player.get("last5_shots", 0),
            "last5_goals":      player.get("last5_goals", 0),
            "last5_points":     player.get("last5_points", 0),
            # Raison narrative
            "reason":           reason,
        }

    def _get_top_players(self, team_name: str, opponent: str, top_n: int = 5) -> list:
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
                if p.get("injuryStatus") in ("IR", "LTIR", "Day-to-Day", "Injured"):
                    continue
                pid  = p.get("id")
                fn   = p.get("firstName", {}).get("default", "")
                ln   = p.get("lastName",  {}).get("default", "")
                pos  = p.get("positionCode", "")
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

        # Ponderation exponentielle (match recent = plus de poids)
        weights = [math.exp(-0.1 * i) for i in range(len(logs))]
        total_w = sum(weights)

        def parse_toi(val):
            if isinstance(val, str) and ":" in val:
                parts = val.split(":")
                return int(parts[0]) * 60 + int(parts[1])
            return float(val) if val else 0.0

        def wavg(field):
            return sum(parse_toi(logs[i].get(field, 0)) * weights[i]
                       if field == "toi"
                       else logs[i].get(field, 0) * weights[i]
                       for i in range(len(logs))) / total_w

        # Stats last 5 (non ponderees - pour tendance)
        last5 = logs[:5]
        last5_shots  = sum(g.get("shots",   0) for g in last5)
        last5_goals  = sum(g.get("goals",   0) for g in last5)
        last5_points = sum(g.get("points",  0) for g in last5)

        toi_sec = wavg("toi")
        toi_min = int(toi_sec // 60)
        toi_s   = int(toi_sec % 60)

        result = {
            "shots_pg":      round(wavg("shots"),   2),
            "goals_pg":      round(wavg("goals"),   3),
            "assists_pg":    round(wavg("assists"),  3),
            "points_pg":     round(wavg("points"),   3),
            "toi_str":       f"{toi_min}:{toi_s:02d}",
            "n_games":       len(logs),
            "last5_shots":   last5_shots,
            "last5_goals":   last5_goals,
            "last5_points":  last5_points,
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

        starter = max(goalies, key=lambda g: g.get("gamesPlayed", 0)
                      if isinstance(g.get("gamesPlayed"), int) else 0)
        pid = starter.get("id")
        fn  = starter.get("firstName", {}).get("default", "")
        ln  = starter.get("lastName",  {}).get("default", "")

        data = _get(f"{NHL_API}/player/{pid}/game-log/{SEASON}/{GAME_TYPE}")
        if not data:
            return {"name": fn + " " + ln}

        logs = data.get("gameLog", [])[:10]
        if not logs:
            return {"name": fn + " " + ln}

        weights = [math.exp(-0.1 * i) for i in range(len(logs))]
        total_w = sum(weights)

        def parse_toi_g(val):
            if isinstance(val, str) and ":" in val:
                p = val.split(":")
                return int(p[0]) * 60 + int(p[1])
            return float(val) if val else 0.0

        def wavg(field):
            return sum(parse_toi_g(logs[i].get(field, 0)) * weights[i]
                       if field == "toi"
                       else logs[i].get(field, 0) * weights[i]
                       for i in range(len(logs))) / total_w

        sv_pct = wavg("savePctg")
        saves  = wavg("saves")
        sa     = wavg("shotsAgainst")
        gaa    = (sa - saves) / max((wavg("toi") / 3600), 0.01)

        return {
            "name":     fn + " " + ln,
            "sv_pct":   round(sv_pct, 3),
            "saves_pg": round(saves, 1),
            "gaa":      round(gaa, 2),
        }
