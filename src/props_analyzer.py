"""
Props Analyzer - Signal joueurs +EV
Calcule l'edge reel vs les lignes DraftKings estimees
Retourne uniquement les bets avec edge >= MIN_EDGE
"""

import requests
import time
import math
from typing import Optional

NHL_API   = "https://api-web.nhle.com/v1"
SEASON    = "20252026"
GAME_TYPE = "2"

# Edge minimum pour inclure un bet joueur
MIN_EDGE = 8.0

# Vig standard DraftKings sur props joueurs (-115 = 52.38% implied)
DK_VIG_IMPLIED = 52.38 / 100  # 0.5238
DK_VIG_ODDS    = 1.869        # -115 en decimal

TEAM_ABBR = {
    "Anaheim Ducks":"ANA","Boston Bruins":"BOS","Buffalo Sabres":"BUF",
    "Calgary Flames":"CGY","Carolina Hurricanes":"CAR","Chicago Blackhawks":"CHI",
    "Colorado Avalanche":"COL","Columbus Blue Jackets":"CBJ","Dallas Stars":"DAL",
    "Detroit Red Wings":"DET","Edmonton Oilers":"EDM","Florida Panthers":"FLA",
    "Los Angeles Kings":"LAK","Minnesota Wild":"MIN",
    "Montreal Canadiens":"MTL","Montréal Canadiens":"MTL",
    "Nashville Predators":"NSH","New Jersey Devils":"NJD","New York Islanders":"NYI",
    "New York Rangers":"NYR","Ottawa Senators":"OTT","Philadelphia Flyers":"PHI",
    "Pittsburgh Penguins":"PIT","San Jose Sharks":"SJS","Seattle Kraken":"SEA",
    "St. Louis Blues":"STL","St Louis Blues":"STL",
    "Tampa Bay Lightning":"TBL","Toronto Maple Leafs":"TOR",
    "Utah Mammoth":"UTA","Vancouver Canucks":"VAN","Vegas Golden Knights":"VGK",
    "Washington Capitals":"WSH","Winnipeg Jets":"WPG",
}

DEF_SHOTS_ALLOWED = {
    "Carolina Hurricanes":26.1,"Boston Bruins":27.0,"Florida Panthers":27.3,
    "Dallas Stars":27.5,"Colorado Avalanche":28.2,"Vegas Golden Knights":28.4,
    "Winnipeg Jets":28.6,"Tampa Bay Lightning":28.8,"Minnesota Wild":29.0,
    "Los Angeles Kings":29.2,"Toronto Maple Leafs":29.8,"Edmonton Oilers":30.1,
    "New York Rangers":30.3,"New York Islanders":30.5,"Washington Capitals":30.8,
    "Seattle Kraken":31.0,"Ottawa Senators":31.2,"New Jersey Devils":31.4,
    "Pittsburgh Penguins":31.6,"Montreal Canadiens":31.8,"Vancouver Canucks":32.0,
    "Buffalo Sabres":32.5,"Philadelphia Flyers":32.8,"Nashville Predators":33.0,
    "Detroit Red Wings":33.2,"Calgary Flames":33.5,"St. Louis Blues":33.8,
    "Columbus Blue Jackets":34.0,"Chicago Blackhawks":34.5,"Anaheim Ducks":34.8,
    "San Jose Sharks":35.2,"Utah Mammoth":31.5,
}

DEF_GA_ALLOWED = {
    "Carolina Hurricanes":2.45,"Boston Bruins":2.60,"Florida Panthers":2.65,
    "Dallas Stars":2.70,"Colorado Avalanche":2.80,"Vegas Golden Knights":2.85,
    "Winnipeg Jets":2.88,"Tampa Bay Lightning":2.92,"Minnesota Wild":2.95,
    "Los Angeles Kings":3.00,"Toronto Maple Leafs":3.05,"Edmonton Oilers":3.10,
    "New York Rangers":3.12,"New York Islanders":3.15,"Washington Capitals":3.18,
    "Seattle Kraken":3.20,"Ottawa Senators":3.22,"New Jersey Devils":3.25,
    "Pittsburgh Penguins":3.28,"Montreal Canadiens":3.30,"Vancouver Canucks":3.32,
    "Buffalo Sabres":3.40,"Philadelphia Flyers":3.42,"Nashville Predators":3.45,
    "Detroit Red Wings":3.48,"Calgary Flames":3.50,"St. Louis Blues":3.55,
    "Columbus Blue Jackets":3.60,"Chicago Blackhawks":3.68,"Anaheim Ducks":3.72,
    "San Jose Sharks":3.80,"Utah Mammoth":3.25,
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

LEAGUE_AVG_SHOTS = 31.0
LEAGUE_AVG_GA    = 3.10


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
    p = sum(_pmf(lam, k) for k in range(int(line) + 1, int(line) + 25))
    return round(min(max(p, 0.01), 0.99) * 100, 1)


def _kelly(our_prob, implied_prob, odds):
    """Quart-Kelly."""
    b = odds - 1
    if b <= 0:
        return 0.0
    k = ((b * our_prob) - (1 - our_prob)) / b / 4 * 100
    return round(max(k, 0), 1)


def _edge_pct(our_prob_pct, implied_pct):
    """Edge en % relatif."""
    if implied_pct <= 0:
        return 0.0
    return round((our_prob_pct - implied_pct) / implied_pct * 100, 1)


class PropsAnalyzer:

    def __init__(self):
        self._roster_cache = {}
        self._stats_cache  = {}

    def analyze_game(self, home_team: str, away_team: str) -> dict:
        print(f"  Analyse props: {away_team} @ {home_team}...")

        home_players = self._get_top_players(home_team)
        away_players = self._get_top_players(away_team)
        home_goalie  = self._get_goalie_stats(home_team)
        away_goalie  = self._get_goalie_stats(away_team)

        home_def = DEF_QUALITY.get(home_team, "avg")
        away_def = DEF_QUALITY.get(away_team, "avg")

        # Genere les bets +EV par equipe (max 3 par equipe)
        home_bets = self._best_bets(home_players, opponent=away_team, team=home_team, n=3)
        away_bets = self._best_bets(away_players, opponent=home_team, team=away_team, n=3)

        # Fusionne et trie par edge, garde max 5
        all_bets = home_bets + away_bets
        all_bets.sort(key=lambda x: x["edge_pct"], reverse=True)
        all_bets = all_bets[:5]

        print(f"    -> {len(all_bets)} bets +EV trouves pour ce match")

        return {
            "home_team":      home_team,
            "away_team":      away_team,
            "home_goalie":    home_goalie,
            "away_goalie":    away_goalie,
            "home_def":       home_def,
            "away_def":       away_def,
            "home_def_shots": DEF_SHOTS_ALLOWED.get(home_team, LEAGUE_AVG_SHOTS),
            "away_def_shots": DEF_SHOTS_ALLOWED.get(away_team, LEAGUE_AVG_SHOTS),
            "home_def_ga":    DEF_GA_ALLOWED.get(home_team, LEAGUE_AVG_GA),
            "away_def_ga":    DEF_GA_ALLOWED.get(away_team, LEAGUE_AVG_GA),
            "bets":           all_bets,
        }

    def _best_bets(self, players, opponent, team, n=3):
        """
        Pour chaque joueur, calcule l'edge sur 3 marches:
          - Shots Over ligne estimee
          - Points Over 0.5
          - Buts Over 0.5
        Garde le meilleur edge par joueur, filtre >= MIN_EDGE.
        """
        opp_shots = DEF_SHOTS_ALLOWED.get(opponent, LEAGUE_AVG_SHOTS)
        opp_ga    = DEF_GA_ALLOWED.get(opponent, LEAGUE_AVG_GA)
        shots_factor = opp_shots / LEAGUE_AVG_SHOTS
        goals_factor = opp_ga    / LEAGUE_AVG_GA

        candidates = []
        for p in players:
            shots_adj  = p["shots_pg"]  * shots_factor
            goals_adj  = p["goals_pg"]  * goals_factor
            points_adj = p["points_pg"] * ((shots_factor + goals_factor) / 2)

            # DK fixe la ligne shots a ~85% de la moy ajustee, arrondi a 0.5 pres
            shots_line = max(round(shots_adj * 0.85 * 2) / 2, 0.5)

            shots_prob  = _poisson_over(shots_adj,  shots_line)
            goals_prob  = _poisson_over(goals_adj,  0.5)
            points_prob = _poisson_over(points_adj, 0.5)

            # DK implied = vig standard -115 (52.38%)
            dk_implied = DK_VIG_IMPLIED * 100

            shots_edge  = _edge_pct(shots_prob,  dk_implied)
            goals_edge  = _edge_pct(goals_prob,  dk_implied)
            points_edge = _edge_pct(points_prob, dk_implied)

            # Meilleur bet pour ce joueur
            options = [
                {
                    "market":    "Shots Over " + str(shots_line),
                    "our_prob":  shots_prob,
                    "edge_pct":  shots_edge,
                    "kelly":     _kelly(shots_prob/100, DK_VIG_IMPLIED, DK_VIG_ODDS),
                    "context":   str(round(shots_adj, 1)) + " shots projetes vs " + DEF_QUALITY.get(opponent,"avg") + " DEF",
                    "last5":     str(p.get("last5_shots", 0)) + " shots last 5",
                    "avg":       str(p["shots_pg"]) + " shots/m",
                },
                {
                    "market":    "Points Over 0.5",
                    "our_prob":  points_prob,
                    "edge_pct":  points_edge,
                    "kelly":     _kelly(points_prob/100, DK_VIG_IMPLIED, DK_VIG_ODDS),
                    "context":   str(round(points_adj, 2)) + " pts projetes",
                    "last5":     str(p.get("last5_points", 0)) + " pts last 5",
                    "avg":       str(round(p["points_pg"], 2)) + " pts/m",
                },
                {
                    "market":    "Buts Over 0.5",
                    "our_prob":  goals_prob,
                    "edge_pct":  goals_edge,
                    "kelly":     _kelly(goals_prob/100, DK_VIG_IMPLIED, DK_VIG_ODDS),
                    "context":   str(round(goals_adj, 2)) + " buts projetes vs " + DEF_QUALITY.get(opponent,"avg") + " DEF",
                    "last5":     str(p.get("last5_goals", 0)) + " buts last 5",
                    "avg":       str(round(p["goals_pg"], 2)) + " buts/m",
                },
            ]

            best = max(options, key=lambda x: x["edge_pct"])
            if best["edge_pct"] >= MIN_EDGE:
                candidates.append({
                    "name":      p["name"],
                    "position":  p.get("position", ""),
                    "team":      team,
                    "opponent":  opponent,
                    "toi":       p.get("toi_str", "--"),
                    "n_games":   p.get("n_games", 0),
                    "market":    best["market"],
                    "our_prob":  best["our_prob"],
                    "dk_implied": round(dk_implied, 1),
                    "dk_odds":   "-115",
                    "edge_pct":  best["edge_pct"],
                    "kelly":     best["kelly"],
                    "context":   best["context"],
                    "last5":     best["last5"],
                    "avg":       best["avg"],
                    # Stats completes pour affichage secondaire
                    "shots_pg":    round(p["shots_pg"], 1),
                    "shots_adj":   round(shots_adj, 1),
                    "shots_line":  shots_line,
                    "shots_prob":  shots_prob,
                    "points_pg":   round(p["points_pg"], 2),
                    "points_adj":  round(points_adj, 2),
                    "points_prob": points_prob,
                    "goals_pg":    round(p["goals_pg"], 2),
                    "goals_adj":   round(goals_adj, 2),
                    "goals_prob":  goals_prob,
                    "last5_shots":  p.get("last5_shots", 0),
                    "last5_points": p.get("last5_points", 0),
                    "last5_goals":  p.get("last5_goals", 0),
                })

        candidates.sort(key=lambda x: x["edge_pct"], reverse=True)
        return candidates[:n]

    def _get_top_players(self, team_name: str, top_n: int = 8) -> list:
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

        print(f"    -> {team_name}: {len(players)} joueurs avec stats")
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

        def parse_toi(val):
            if isinstance(val, str) and ":" in val:
                parts = val.split(":")
                return int(parts[0]) * 60 + int(parts[1])
            return float(val) if val else 0.0

        def wavg(field):
            return sum(
                parse_toi(logs[i].get(field, 0)) * weights[i] if field == "toi"
                else logs[i].get(field, 0) * weights[i]
                for i in range(len(logs))
            ) / total_w

        last5 = logs[:5]
        toi_sec = wavg("toi")

        result = {
            "shots_pg":     round(wavg("shots"),   2),
            "goals_pg":     round(wavg("goals"),   3),
            "assists_pg":   round(wavg("assists"),  3),
            "points_pg":    round(wavg("points"),   3),
            "toi_str":      f"{int(toi_sec//60)}:{int(toi_sec%60):02d}",
            "n_games":      len(logs),
            "last5_shots":  sum(g.get("shots",  0) for g in last5),
            "last5_goals":  sum(g.get("goals",  0) for g in last5),
            "last5_points": sum(g.get("points", 0) for g in last5),
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
            return sum(
                parse_toi_g(logs[i].get(field, 0)) * weights[i] if field == "toi"
                else logs[i].get(field, 0) * weights[i]
                for i in range(len(logs))
            ) / total_w

        sa    = wavg("shotsAgainst")
        ga    = wavg("goalsAgainst")
        saves = sa - ga
        sv_pct = saves / max(sa, 1)
        toi_h  = wavg("toi") / 3600
        gaa    = ga / max(toi_h, 0.01)

        return {
            "name":     fn + " " + ln,
            "sv_pct":   round(sv_pct, 3),
            "saves_pg": round(saves, 1),
            "gaa":      round(gaa, 2),
        }
