"""
Props Analyzer - Signal joueurs +EV complet
- Shots, buts, points vs lignes bet365 estimees (-110)
- Multiplicateurs PP1/PP2/ligne depuis Daily Faceoff
- Tendance last 5 vs last 10 + milestones
- Edge reel vs vig bet365 standard
"""

import requests
import time
import math
from typing import Optional

NHL_API   = "https://api-web.nhle.com/v1"
SEASON    = "20252026"
GAME_TYPE = "2"

MIN_EDGE       = 8.0
B365_VIG_IMPL  = 52.36 / 100   # bet365 -110 standard
B365_VIG_ODDS  = 1.909          # -110 en decimal

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

# Rang defensif
DEF_SHOTS_RANK = {}
DEF_GA_RANK    = {}

def _build_ranks():
    for i, (t, _) in enumerate(sorted(DEF_SHOTS_ALLOWED.items(), key=lambda x: x[1])):
        DEF_SHOTS_RANK[t] = i + 1
    for i, (t, _) in enumerate(sorted(DEF_GA_ALLOWED.items(), key=lambda x: x[1])):
        DEF_GA_RANK[t] = i + 1

_build_ranks()


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


def _kelly(our_prob_pct, implied, odds):
    b = odds - 1
    if b <= 0: return 0.0
    k = ((b * our_prob_pct / 100) - (1 - our_prob_pct / 100)) / b / 4 * 100
    return round(max(k, 0), 1)


def _edge(our_pct, implied_pct):
    if implied_pct <= 0: return 0.0
    return round((our_pct - implied_pct) / implied_pct * 100, 1)


def _def_label(rank):
    if rank <= 4:  return "Elite (#" + str(rank) + ")"
    if rank <= 10: return "Bonne (#" + str(rank) + ")"
    if rank <= 22: return "Moyenne (#" + str(rank) + ")"
    return "Faible (#" + str(rank) + ")"


def _def_color(rank):
    if rank <= 4:  return "#0F6E56"
    if rank <= 10: return "#2563EB"
    if rank <= 22: return "#6B7280"
    return "#B45309"


def _build_context(name, shots_pg, shots_adj, goals_pg, goals_adj, points_pg,
                   last5_shots, last5_goals, last5_points,
                   last10_shots, last10_goals, last10_points,
                   season_goals, season_points, opponent,
                   shots_rank_opp, ga_rank_opp,
                   pp_unit, line_num, is_defense):
    notes = []

    # Milestones buts
    if season_goals > 0:
        for m in [20, 25, 30, 35, 40, 45, 50, 55, 60]:
            rem = m - season_goals
            if 0 < rem <= 5:
                notes.append("🎯 Chase du " + str(m) + "e but — " + str(rem) + " but" + ("s" if rem > 1 else "") + " restant" + ("s" if rem > 1 else ""))
                break

    # Milestones points
    if season_points > 0:
        for m in [30, 40, 50, 60, 70, 80, 90, 100]:
            rem = m - season_points
            if 0 < rem <= 6:
                notes.append("📈 Chase du " + str(m) + "e point — " + str(rem) + " pt" + ("s" if rem > 1 else "") + " restant" + ("s" if rem > 1 else ""))
                break

    # Role PP
    if pp_unit == 1:
        notes.append("⚡ PP1 — temps de jeu supplementaire en avantage numerique")
    elif pp_unit == 2:
        notes.append("PP2 — opportunites en avantage numerique")

    # Tendance shots last 5 vs last 10
    avg5  = round(last5_shots / 5,  1) if last5_shots  else 0
    avg10 = round(last10_shots / 10, 1) if last10_shots else shots_pg
    if avg5 > avg10 * 1.20:
        notes.append("🔥 Shots en hausse — " + str(avg5) + "/m last 5 vs " + str(avg10) + "/m last 10")
    elif avg5 < avg10 * 0.75:
        notes.append("❄️ Shots en baisse — " + str(avg5) + "/m last 5 vs " + str(avg10) + "/m last 10")

    # Streak buts
    if last5_goals >= 5:
        notes.append("🚨 " + str(last5_goals) + " buts dans ses 5 derniers matchs")
    elif last5_goals >= 3:
        notes.append(str(last5_goals) + " buts dans ses 5 derniers matchs")

    # Streak points
    if last5_points >= 8:
        notes.append("⭐ " + str(last5_points) + " pts dans ses 5 derniers matchs")
    elif last5_points >= 5:
        notes.append(str(last5_points) + " pts dans ses 5 derniers matchs")

    # Matchup shots
    opp_shots = DEF_SHOTS_ALLOWED.get(opponent, LEAGUE_AVG_SHOTS)
    if shots_rank_opp >= 28:
        notes.append("🎯 Matchup ideal — " + opponent[:12] + " accorde " + str(opp_shots) + " shots/m (" + _def_label(shots_rank_opp) + ")")
    elif shots_rank_opp <= 5:
        notes.append("⚠️ Defense solide — " + opponent[:12] + " n'accorde que " + str(opp_shots) + " shots/m (" + _def_label(shots_rank_opp) + ")")

    # Matchup buts
    opp_ga = DEF_GA_ALLOWED.get(opponent, LEAGUE_AVG_GA)
    if ga_rank_opp >= 28:
        notes.append("Defense poreuse — " + str(opp_ga) + " buts accordes/m (" + _def_label(ga_rank_opp) + ")")

    return notes[:4]


class PropsAnalyzer:

    def __init__(self):
        self._roster_cache  = {}
        self._stats_cache   = {}
        self._lineup_fetcher = None  # Injecte depuis signal.py

    def analyze_game(self, home_team: str, away_team: str) -> dict:
        print(f"  Analyse props: {away_team} @ {home_team}...")

        home_players = self._get_top_players(home_team)
        away_players = self._get_top_players(away_team)
        home_goalie  = self._get_goalie_stats(home_team)
        away_goalie  = self._get_goalie_stats(away_team)

        home_bets = self._best_bets(home_players, opponent=away_team, team=home_team, n=3)
        away_bets = self._best_bets(away_players, opponent=home_team, team=away_team, n=3)

        all_bets = (home_bets + away_bets)
        all_bets.sort(key=lambda x: x["edge_pct"], reverse=True)
        all_bets = all_bets[:6]

        print(f"    -> {len(all_bets)} bets +EV ({home_team} vs {away_team})")

        return {
            "home_team":      home_team,
            "away_team":      away_team,
            "home_goalie":    home_goalie,
            "away_goalie":    away_goalie,
            "home_def_shots": DEF_SHOTS_ALLOWED.get(home_team, LEAGUE_AVG_SHOTS),
            "away_def_shots": DEF_SHOTS_ALLOWED.get(away_team, LEAGUE_AVG_SHOTS),
            "home_def_ga":    DEF_GA_ALLOWED.get(home_team, LEAGUE_AVG_GA),
            "away_def_ga":    DEF_GA_ALLOWED.get(away_team, LEAGUE_AVG_GA),
            "home_shots_rank": DEF_SHOTS_RANK.get(home_team, 16),
            "away_shots_rank": DEF_SHOTS_RANK.get(away_team, 16),
            "home_ga_rank":    DEF_GA_RANK.get(home_team, 16),
            "away_ga_rank":    DEF_GA_RANK.get(away_team, 16),
            "bets":           all_bets,
        }

    def _get_role_multiplier(self, player_name: str, team: str) -> tuple:
        """Retourne (multiplicateur, pp_unit, line_num, is_defense)."""
        if self._lineup_fetcher is None:
            return (1.0, 0, 2, False)
        role = self._lineup_fetcher.get_player_role(player_name, team)
        return (
            role.get("multiplier", 1.0),
            role.get("pp", 0),
            role.get("line", 2),
            role.get("is_defense", False),
        )

    def _best_bets(self, players, opponent, team, n=3):
        opp_shots      = DEF_SHOTS_ALLOWED.get(opponent, LEAGUE_AVG_SHOTS)
        opp_ga         = DEF_GA_ALLOWED.get(opponent, LEAGUE_AVG_GA)
        shots_factor   = opp_shots / LEAGUE_AVG_SHOTS
        goals_factor   = opp_ga    / LEAGUE_AVG_GA
        shots_rank_opp = DEF_SHOTS_RANK.get(opponent, 16)
        ga_rank_opp    = DEF_GA_RANK.get(opponent, 16)
        b365_impl_pct  = B365_VIG_IMPL * 100

        candidates = []
        for p in players:
            # Multiplicateur de role (lineup Daily Faceoff)
            mult, pp_unit, line_num, is_defense = self._get_role_multiplier(p["name"], team)

            # Projections ajustees par role ET defense adverse
            shots_adj  = p["shots_pg"]  * shots_factor * mult
            goals_adj  = p["goals_pg"]  * goals_factor * mult
            points_adj = p["points_pg"] * ((shots_factor + goals_factor) / 2) * mult

            # Plafonds realistes pour eviter les projections folles
            shots_adj  = min(shots_adj,  8.0)
            goals_adj  = min(goals_adj,  1.5)
            points_adj = min(points_adj, 3.0)

            # ── Lignes bet365 avec filtres cote minimale ──────────────
            # Cote min 1.65 (-154) — en dessous le R/R est trop mauvais
            # meme avec un edge solide.
            # Logique: prob Over doit etre <= 61% pour que la cote estimee
            # soit >= 1.65. Si prob est 70%+, la cote serait ~1.43 -> skip.
            # Regle: on choisit la ligne shots qui donne une cote >= 1.65.
            # Pour y arriver: prob Over doit etre entre 45% et 62%.

            MIN_PROB = 0.38   # Prob min pour que le bet soit credible
            MAX_PROB = 0.62   # Prob max => cote min ~1.61, acceptable
            # Note: prob 62% => cote implicite 1.61, avec vig -110 => ~1.65

            # Shots: cherche la ligne optimale entre 0.5 et 5.5
            shots_line  = None
            shots_prob  = 0.0
            shots_edge  = 0.0
            for candidate_line in [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]:
                p_val = _poisson_over(shots_adj, candidate_line) / 100
                if MIN_PROB <= p_val <= MAX_PROB:
                    shots_line = candidate_line
                    shots_prob = round(p_val * 100, 1)
                    shots_edge = _edge(shots_prob, b365_impl_pct)
                    break

            # Buts Over 0.5 — prob souvent trop haute pour stars
            # On utilise Over 1.5 si prob Over 0.5 > 62%
            goals_raw = _poisson_over(goals_adj, 0.5) / 100
            if goals_raw > MAX_PROB:
                goals_prob = round(_poisson_over(goals_adj, 1.5), 1)
                goals_label = "Buts Over 1.5"
            else:
                goals_prob = round(goals_raw * 100, 1)
                goals_label = "Buts Over 0.5"
            goals_edge = _edge(goals_prob, b365_impl_pct)

            # Points — meme logique
            pts_raw = _poisson_over(points_adj, 0.5) / 100
            if pts_raw > MAX_PROB:
                points_prob = round(_poisson_over(points_adj, 1.5), 1)
                points_label = "Points Over 1.5"
            else:
                points_prob = round(pts_raw * 100, 1)
                points_label = "Points Over 0.5"
            points_edge = _edge(points_prob, b365_impl_pct)

            # EV = edge * (cote_implicite / 100) — filtre bets a faible EV
            # Cote implicite estimee bet365 = 1 / (notre_prob/100) * (1 - vig)
            def est_odds(prob_pct):
                if prob_pct <= 0: return 99.0
                return round((1 / (prob_pct / 100)) * 0.9524, 2)  # vig ~5%

            shots_odds  = est_odds(shots_prob)  if shots_line else 99.0
            goals_odds  = est_odds(goals_prob)
            points_odds = est_odds(points_prob)

            # Contexte narratif
            context_notes = _build_context(
                p["name"], p["shots_pg"], shots_adj,
                p["goals_pg"], goals_adj, p["points_pg"],
                p.get("last5_shots", 0), p.get("last5_goals", 0), p.get("last5_points", 0),
                p.get("last10_shots", 0), p.get("last10_goals", 0), p.get("last10_points", 0),
                p.get("season_goals", 0), p.get("season_points", 0),
                opponent, shots_rank_opp, ga_rank_opp,
                pp_unit, line_num, is_defense,
            )

            # ── Marches avec edge ET cote acceptable (>= 1.65) ──────
            MIN_ODDS_FILTER = 1.65
            markets = []

            if shots_line and shots_edge >= MIN_EDGE and shots_odds >= MIN_ODDS_FILTER:
                markets.append({
                    "type":      "shots",
                    "label":     "Shots Over " + str(shots_line),
                    "prob":      shots_prob,
                    "edge":      shots_edge,
                    "kelly":     _kelly(shots_prob, B365_VIG_IMPL, B365_VIG_ODDS),
                    "est_odds":  shots_odds,
                    "detail":    str(round(shots_adj, 1)) + " shots proj. · moy " + str(p["shots_pg"]) + "/m" + (" · PP" + str(pp_unit) if pp_unit else ""),
                })

            if goals_edge >= MIN_EDGE and goals_odds >= MIN_ODDS_FILTER:
                markets.append({
                    "type":      "goals",
                    "label":     goals_label,
                    "prob":      goals_prob,
                    "edge":      goals_edge,
                    "kelly":     _kelly(goals_prob, B365_VIG_IMPL, B365_VIG_ODDS),
                    "est_odds":  goals_odds,
                    "detail":    str(round(goals_adj, 2)) + " buts proj. · moy " + str(round(p["goals_pg"], 2)) + "/m",
                })

            if points_edge >= MIN_EDGE and points_odds >= MIN_ODDS_FILTER:
                markets.append({
                    "type":      "points",
                    "label":     points_label,
                    "prob":      points_prob,
                    "edge":      points_edge,
                    "kelly":     _kelly(points_prob, B365_VIG_IMPL, B365_VIG_ODDS),
                    "est_odds":  points_odds,
                    "detail":    str(round(points_adj, 2)) + " pts proj. · moy " + str(round(p["points_pg"], 2)) + "/m",
                })

            if not markets:
                continue

            markets.sort(key=lambda x: x["edge"], reverse=True)
            best = markets[0]

            candidates.append({
                "name":          p["name"],
                "position":      p.get("position", ""),
                "team":          team,
                "opponent":      opponent,
                "toi":           p.get("toi_str", "--"),
                "n_games":       p.get("n_games", 0),
                # Role
                "line_num":      line_num,
                "pp_unit":       pp_unit,
                "is_defense":    is_defense,
                "role_mult":     round(mult, 2),
                # Bet principal
                "market":        best["label"],
                "market_type":   best["type"],
                "our_prob":      best["prob"],
                "edge_pct":      best["edge"],
                "kelly":         best["kelly"],
                "market_detail": best["detail"],
                "b365_odds":     "-110",
                "b365_implied":  round(b365_impl_pct, 1),
                # Tous les marches +EV
                "all_markets":   markets,
                # Stats shots
                "shots_pg":     round(p["shots_pg"], 1),
                "shots_adj":    round(shots_adj, 1),
                "shots_line":   shots_line,
                "shots_prob":   shots_prob,
                "shots_edge":   shots_edge,
                "last5_shots":  p.get("last5_shots", 0),
                "last10_shots": p.get("last10_shots", 0),
                # Stats buts
                "goals_pg":     round(p["goals_pg"], 2),
                "goals_adj":    round(goals_adj, 2),
                "goals_prob":   goals_prob,
                "goals_edge":   goals_edge,
                "last5_goals":  p.get("last5_goals", 0),
                "season_goals": p.get("season_goals", 0),
                # Stats points
                "points_pg":     round(p["points_pg"], 2),
                "points_adj":    round(points_adj, 2),
                "points_prob":   points_prob,
                "points_edge":   points_edge,
                "last5_points":  p.get("last5_points", 0),
                "season_points": p.get("season_points", 0),
                # Contexte
                "context_notes": context_notes,
                "opp_shots_rank": shots_rank_opp,
                "opp_ga_rank":    ga_rank_opp,
                "opp_shots_pg":   round(opp_shots, 1),
                "opp_ga_pg":      round(opp_ga, 2),
            })

        candidates.sort(key=lambda x: x["edge_pct"], reverse=True)
        return candidates[:n]

    def _get_top_players(self, team_name: str, top_n: int = 10) -> list:
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
                # Filtre les joueurs blesses selon Daily Faceoff
                fn  = p.get("firstName", {}).get("default", "")
                ln  = p.get("lastName",  {}).get("default", "")
                full_name = fn + " " + ln
                if self._lineup_fetcher and self._lineup_fetcher.is_injured(full_name, team_name):
                    continue
                pid = p.get("id")
                pos = p.get("positionCode", "")
                stats = self._get_player_stats(pid, full_name)
                if stats:
                    stats["name"]     = full_name
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

        logs = data.get("gameLog", [])
        if not logs:
            return None

        logs10 = logs[:10]
        logs5  = logs[:5]

        weights = [math.exp(-0.1 * i) for i in range(len(logs10))]
        total_w = sum(weights)

        def parse_toi(val):
            if isinstance(val, str) and ":" in val:
                parts = val.split(":")
                return int(parts[0]) * 60 + int(parts[1])
            return float(val) if val else 0.0

        def wavg(field):
            return sum(
                parse_toi(logs10[i].get(field, 0)) * weights[i] if field == "toi"
                else logs10[i].get(field, 0) * weights[i]
                for i in range(len(logs10))
            ) / total_w

        toi_sec = wavg("toi")

        result = {
            "shots_pg":      round(wavg("shots"),   2),
            "goals_pg":      round(wavg("goals"),   3),
            "assists_pg":    round(wavg("assists"),  3),
            "points_pg":     round(wavg("points"),   3),
            "toi_str":       f"{int(toi_sec//60)}:{int(toi_sec%60):02d}",
            "n_games":       len(logs10),
            "last5_shots":   sum(g.get("shots",  0) for g in logs5),
            "last5_goals":   sum(g.get("goals",  0) for g in logs5),
            "last5_points":  sum(g.get("points", 0) for g in logs5),
            "last10_shots":  sum(g.get("shots",  0) for g in logs10),
            "last10_goals":  sum(g.get("goals",  0) for g in logs10),
            "last10_points": sum(g.get("points", 0) for g in logs10),
            "season_goals":  sum(g.get("goals",  0) for g in logs),
            "season_points": sum(g.get("points", 0) for g in logs),
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

        # Utilise le gardien Daily Faceoff si disponible
        df_goalie = ""
        if self._lineup_fetcher:
            lineup = self._lineup_fetcher.get_lineup(team_name)
            df_goalie = lineup.get("goalie", "")

        if df_goalie:
            starter = next(
                (g for g in goalies
                 if (g.get("firstName", {}).get("default", "") + " " +
                     g.get("lastName",  {}).get("default", "")).strip() == df_goalie),
                None
            )
        else:
            starter = None

        if not starter:
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
            "confirmed": bool(df_goalie),
        }
