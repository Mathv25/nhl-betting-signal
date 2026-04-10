"""
Props Analyzer - Signal joueurs +EV v2
Ajustements post-backtest:
- Shots uniquement sur defense >= rang #20
- Selection intelligente shots/buts/points selon matchup
- Blocage si lineup Daily Faceoff non confirme
- Bloc retour de flamme (regression vers la moyenne)
- Vig bet365 -110
"""

import requests
import time
import math
from typing import Optional

NHL_API   = "https://api-web.nhle.com/v1"
SEASON    = "20252026"
GAME_TYPE = "2"

MIN_EDGE             = 8.0
B365_VIG_IMPL        = 52.36 / 100
B365_VIG_ODDS        = 1.909
MIN_DEF_RANK_SHOTS   = 20   # shots only vs weak defenses
MIN_DEF_RANK_GOALS   = 20   # goals only vs weak defenses

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

LEAGUE_AVG_SHOTS = 31.0
LEAGUE_AVG_GA    = 3.10

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


def _est_odds(prob_pct):
    if prob_pct <= 0: return 99.0
    return round((1 / (prob_pct / 100)) * 0.9524, 2)


def _def_label(rank):
    if rank <= 4:  return "Elite (#" + str(rank) + ")"
    if rank <= 10: return "Bonne (#" + str(rank) + ")"
    if rank <= 22: return "Moyenne (#" + str(rank) + ")"
    return "Faible (#" + str(rank) + ")"


def _build_context(shots_pg, shots_adj, goals_pg, points_pg,
                   last5_shots, last5_goals, last5_points,
                   last10_shots, last10_goals, last10_points,
                   season_goals, season_points, opponent,
                   shots_rank_opp, ga_rank_opp, pp_unit, line_num):
    notes = []
    if season_goals > 0:
        for m in [20, 25, 30, 35, 40, 45, 50, 55, 60]:
            rem = m - season_goals
            if 0 < rem <= 5:
                notes.append("🎯 Chase du " + str(m) + "e but — " + str(rem) + " restant" + ("s" if rem > 1 else ""))
                break
    if season_points > 0:
        for m in [30, 40, 50, 60, 70, 80, 90, 100]:
            rem = m - season_points
            if 0 < rem <= 6:
                notes.append("📈 Chase du " + str(m) + "e point — " + str(rem) + " pt" + ("s" if rem > 1 else "") + " restant" + ("s" if rem > 1 else ""))
                break
    if pp_unit == 1:
        notes.append("⚡ PP1 — avantage numerique")
    elif pp_unit == 2:
        notes.append("PP2 — opportunites PP")
    avg5  = round(last5_shots / 5,  1) if last5_shots  else 0
    avg10 = round(last10_shots / 10, 1) if last10_shots else shots_pg
    if avg5 > avg10 * 1.20:
        notes.append("🔥 Shots en hausse — " + str(avg5) + "/m last 5 vs " + str(avg10) + "/m last 10")
    elif avg5 < avg10 * 0.75:
        notes.append("❄️ Shots en baisse — " + str(avg5) + "/m last 5 vs " + str(avg10) + "/m last 10")
    if last5_goals >= 5:
        notes.append("🚨 " + str(last5_goals) + " buts dans ses 5 derniers matchs")
    elif last5_goals >= 3:
        notes.append(str(last5_goals) + " buts dans ses 5 derniers matchs")
    if last5_points >= 8:
        notes.append("⭐ " + str(last5_points) + " pts dans ses 5 derniers matchs")
    elif last5_points >= 5:
        notes.append(str(last5_points) + " pts dans ses 5 derniers matchs")
    opp_shots = DEF_SHOTS_ALLOWED.get(opponent, LEAGUE_AVG_SHOTS)
    if shots_rank_opp >= 28:
        notes.append("🎯 Matchup ideal — " + opponent[:12] + " accorde " + str(opp_shots) + " shots/m (#" + str(shots_rank_opp) + ")")
    elif shots_rank_opp <= 5:
        notes.append("⚠️ Defense solide — " + opponent[:12] + " (#" + str(shots_rank_opp) + " ligue)")
    opp_ga = DEF_GA_ALLOWED.get(opponent, LEAGUE_AVG_GA)
    if ga_rank_opp >= 28:
        notes.append("Defense poreuse — " + str(opp_ga) + " buts/m (#" + str(ga_rank_opp) + ")")
    return notes[:4]


class PropsAnalyzer:

    def __init__(self):
        self._roster_cache   = {}
        self._stats_cache    = {}
        self._lineup_fetcher = None

    def analyze_game(self, home_team: str, away_team: str) -> dict:
        print(f"  Analyse props: {away_team} @ {home_team}...")

        lineup_confirmed = self._lineup_confirmed(home_team, away_team)
        home_players = self._get_top_players(home_team)
        away_players = self._get_top_players(away_team)
        home_goalie  = self._get_goalie_stats(home_team)
        away_goalie  = self._get_goalie_stats(away_team)

        home_bets = self._best_bets(home_players, away_team, home_team, 3, lineup_confirmed)
        away_bets = self._best_bets(away_players, home_team, away_team, 3, lineup_confirmed)

        all_bets = home_bets + away_bets
        all_bets.sort(key=lambda x: x["edge_pct"], reverse=True)
        all_bets = all_bets[:6]

        retour = self._retour_de_flamme(home_players, away_players, home_team, away_team)

        print(f"    -> {len(all_bets)} bets +EV · {len(retour)} retours de flamme")

        return {
            "home_team":        home_team,
            "away_team":        away_team,
            "home_goalie":      home_goalie,
            "away_goalie":      away_goalie,
            "home_def_shots":   DEF_SHOTS_ALLOWED.get(home_team, LEAGUE_AVG_SHOTS),
            "away_def_shots":   DEF_SHOTS_ALLOWED.get(away_team, LEAGUE_AVG_SHOTS),
            "home_def_ga":      DEF_GA_ALLOWED.get(home_team, LEAGUE_AVG_GA),
            "away_def_ga":      DEF_GA_ALLOWED.get(away_team, LEAGUE_AVG_GA),
            "home_shots_rank":  DEF_SHOTS_RANK.get(home_team, 16),
            "away_shots_rank":  DEF_SHOTS_RANK.get(away_team, 16),
            "home_ga_rank":     DEF_GA_RANK.get(home_team, 16),
            "away_ga_rank":     DEF_GA_RANK.get(away_team, 16),
            "lineup_confirmed": lineup_confirmed,
            "bets":             all_bets,
            "retour_de_flamme": retour,
        }

    def _lineup_confirmed(self, home: str, away: str) -> bool:
        if self._lineup_fetcher is None:
            return False
        h = self._lineup_fetcher.get_lineup(home)
        a = self._lineup_fetcher.get_lineup(away)
        return len(h.get("forwards", [])) >= 6 and len(a.get("forwards", [])) >= 6

    def _get_role_multiplier(self, name: str, team: str) -> tuple:
        if self._lineup_fetcher is None:
            return (1.0, 0, 2, False)
        role = self._lineup_fetcher.get_player_role(name, team)
        return (role.get("multiplier", 1.0), role.get("pp", 0),
                role.get("line", 2), role.get("is_defense", False))

    def _best_bets(self, players, opponent, team, n, lineup_confirmed):
        opp_shots      = DEF_SHOTS_ALLOWED.get(opponent, LEAGUE_AVG_SHOTS)
        opp_ga         = DEF_GA_ALLOWED.get(opponent, LEAGUE_AVG_GA)
        shots_factor   = opp_shots / LEAGUE_AVG_SHOTS
        goals_factor   = opp_ga    / LEAGUE_AVG_GA
        shots_rank_opp = DEF_SHOTS_RANK.get(opponent, 16)
        ga_rank_opp    = DEF_GA_RANK.get(opponent, 16)
        b365_impl_pct  = B365_VIG_IMPL * 100
        MIN_PROB, MAX_PROB, MIN_ODDS = 0.40, 0.61, 1.65

        candidates = []
        for p in players:
            if self._lineup_fetcher and self._lineup_fetcher.is_injured(p["name"], team):
                continue

            mult, pp_unit, line_num, is_defense = self._get_role_multiplier(p["name"], team)
            shots_adj  = min(p["shots_pg"]  * shots_factor * mult, 8.0)
            goals_adj  = min(p["goals_pg"]  * goals_factor * mult, 1.5)
            points_adj = min(p["points_pg"] * ((shots_factor + goals_factor) / 2) * mult, 3.0)

            markets = []

            # SHOTS — seulement vs defense faible
            if shots_rank_opp >= MIN_DEF_RANK_SHOTS:
                sl, sp, se = None, 0.0, 0.0
                for cl in [5.5, 4.5, 3.5, 2.5, 1.5, 0.5]:
                    pv = _poisson_over(shots_adj, cl) / 100
                    if MIN_PROB <= pv <= MAX_PROB:
                        sl, sp, se = cl, round(pv*100,1), _edge(round(pv*100,1), b365_impl_pct)
                        break
                if sl is None:
                    bd = 99.0
                    for cl in [0.5,1.5,2.5,3.5,4.5,5.5]:
                        pv = _poisson_over(shots_adj, cl) / 100
                        d = abs(pv - 0.5)
                        if d < bd:
                            bd, sl, sp, se = d, cl, round(pv*100,1), _edge(round(pv*100,1), b365_impl_pct)
                so = _est_odds(sp)
                if sl and se >= MIN_EDGE and so >= MIN_ODDS:
                    markets.append({"type":"shots","label":"Shots Over "+str(sl),
                        "prob":sp,"edge":se,"kelly":_kelly(sp,B365_VIG_IMPL,B365_VIG_ODDS),
                        "est_odds":so,"detail":str(round(shots_adj,1))+" shots proj. · moy "+str(p["shots_pg"])+"/m · DEF #"+str(shots_rank_opp)})

            # BUTS — vs defense poreuse ET buteur
            if ga_rank_opp >= MIN_DEF_RANK_GOALS and p["goals_pg"] >= 0.35:
                gr = _poisson_over(goals_adj, 0.5) / 100
                if gr > MAX_PROB:
                    gp, gl = round(_poisson_over(goals_adj, 1.5), 1), "Buts Over 1.5"
                else:
                    gp, gl = round(gr*100,1), "Buts Over 0.5"
                ge, go = _edge(gp, b365_impl_pct), _est_odds(gp)
                if ge >= MIN_EDGE and go >= MIN_ODDS:
                    markets.append({"type":"goals","label":gl,
                        "prob":gp,"edge":ge,"kelly":_kelly(gp,B365_VIG_IMPL,B365_VIG_ODDS),
                        "est_odds":go,"detail":str(round(goals_adj,2))+" buts proj. · moy "+str(round(p["goals_pg"],2))+"/m · DEF buts #"+str(ga_rank_opp)})

            # POINTS — playmaker ou si pas d'autre option
            is_playmaker = p.get("assists_pg", 0) > p["goals_pg"] * 1.5
            if not markets or is_playmaker:
                pr_raw = _poisson_over(points_adj, 0.5) / 100
                if pr_raw > MAX_PROB:
                    pp2, pl = round(_poisson_over(points_adj, 1.5), 1), "Points Over 1.5"
                else:
                    pp2, pl = round(pr_raw*100,1), "Points Over 0.5"
                pe, po = _edge(pp2, b365_impl_pct), _est_odds(pp2)
                if pe >= MIN_EDGE and po >= MIN_ODDS:
                    markets.append({"type":"points","label":pl,
                        "prob":pp2,"edge":pe,"kelly":_kelly(pp2,B365_VIG_IMPL,B365_VIG_ODDS),
                        "est_odds":po,"detail":str(round(points_adj,2))+" pts proj. · moy "+str(round(p["points_pg"],2))+"/m"})

            if not markets:
                continue

            markets.sort(key=lambda x: x["edge"], reverse=True)
            best = markets[0]

            context_notes = _build_context(
                p["shots_pg"], shots_adj, p["goals_pg"], p["points_pg"],
                p.get("last5_shots",0), p.get("last5_goals",0), p.get("last5_points",0),
                p.get("last10_shots",0), p.get("last10_goals",0), p.get("last10_points",0),
                p.get("season_goals",0), p.get("season_points",0),
                opponent, shots_rank_opp, ga_rank_opp, pp_unit, line_num,
            )

            # Recalcul shots_adj pour affichage dans la card
            s_adj_display = round(min(p["shots_pg"] * shots_factor * mult, 8.0), 1)
            # Determine shots_line et shots_prob pour affichage
            s_line_display = None
            s_prob_display = 0.0
            s_edge_display = 0.0
            for cl in [5.5,4.5,3.5,2.5,1.5,0.5]:
                pv = _poisson_over(s_adj_display, cl) / 100
                if MIN_PROB <= pv <= MAX_PROB:
                    s_line_display = cl
                    s_prob_display = round(pv*100,1)
                    s_edge_display = _edge(s_prob_display, b365_impl_pct)
                    break
            if s_line_display is None:
                bd = 99.0
                for cl in [0.5,1.5,2.5,3.5,4.5,5.5]:
                    pv = _poisson_over(s_adj_display, cl) / 100
                    d = abs(pv-0.5)
                    if d < bd:
                        bd,s_line_display = d,cl
                        s_prob_display = round(pv*100,1)
                        s_edge_display = _edge(s_prob_display, b365_impl_pct)

            candidates.append({
                "name":p["name"],"position":p.get("position",""),"team":team,
                "opponent":opponent,"toi":p.get("toi_str","--"),"n_games":p.get("n_games",0),
                "line_num":line_num,"pp_unit":pp_unit,"is_defense":is_defense,
                "lineup_ok":lineup_confirmed,
                "market":best["label"],"market_type":best["type"],
                "our_prob":best["prob"],"edge_pct":best["edge"],"kelly":best["kelly"],
                "market_detail":best["detail"],"est_odds":best["est_odds"],
                "b365_implied":round(b365_impl_pct,1),"all_markets":markets,
                "shots_pg":round(p["shots_pg"],1),"goals_pg":round(p["goals_pg"],2),
                "points_pg":round(p["points_pg"],2),
                "shots_adj":s_adj_display,
                "shots_line":s_line_display,
                "shots_prob":s_prob_display,
                "shots_edge":s_edge_display,
                "goals_adj":round(min(p["goals_pg"]*goals_factor*mult,1.5),2),
                "points_adj":round(min(p["points_pg"]*((shots_factor+goals_factor)/2)*mult,3.0),2),
                "last5_shots":p.get("last5_shots",0),"last10_shots":p.get("last10_shots",0),
                "last5_goals":p.get("last5_goals",0),"last5_points":p.get("last5_points",0),
                "season_goals":p.get("season_goals",0),"season_points":p.get("season_points",0),
                "opp_shots_rank":shots_rank_opp,"opp_ga_rank":ga_rank_opp,
                "context_notes":context_notes,
            })

        candidates.sort(key=lambda x: x["edge_pct"], reverse=True)
        return candidates[:n]

    def _retour_de_flamme(self, home_players, away_players, home_team, away_team) -> list:
        """
        Joueurs qui tiraient bien (moy last 10 >= 2.5 shots/m) mais sont
        en dessous de 75% de cette moyenne sur les 5 derniers matchs.
        DK va probablement baisser leur ligne => edge sur le Over base sur
        leur vraie moyenne.
        """
        retour = []
        seen   = set()

        for players, team, opponent in [
            (home_players, home_team, away_team),
            (away_players, away_team, home_team),
        ]:
            shots_rank_opp = DEF_SHOTS_RANK.get(opponent, 16)

            for p in players:
                name = p.get("name", "")
                if not name or name in seen:
                    continue
                seen.add(name)

                last10 = p.get("last10_shots", 0)
                last5  = p.get("last5_shots",  0)
                if last10 < 2: continue

                avg10 = round(last10 / 10, 1)
                avg5  = round(last5  / 5,  1)

                if avg10 < 2.5: continue        # joueur pas assez actif
                if avg5 >= avg10 * 0.75: continue  # pas assez froid

                drop_pct = round((1 - avg5 / avg10) * 100)

                # DK va setter la ligne sur last 5 (forme recente)
                adj_factor   = DEF_SHOTS_ALLOWED.get(opponent, LEAGUE_AVG_SHOTS) / LEAGUE_AVG_SHOTS
                adj_deprime  = avg5  * adj_factor
                adj_reel     = avg10 * adj_factor
                dk_line_est  = max(round(adj_deprime * 0.85 * 2) / 2, 0.5)

                our_prob = _poisson_over(adj_reel, dk_line_est)
                dk_impl  = B365_VIG_IMPL * 100
                edge     = _edge(our_prob, dk_impl)
                est_odds = _est_odds(our_prob)

                if edge < MIN_EDGE or est_odds < 1.65:
                    continue

                retour.append({
                    "name":          name,
                    "position":      p.get("position", ""),
                    "team":          team,
                    "opponent":      opponent,
                    "toi":           p.get("toi_str", "--"),
                    "avg10_shots":   avg10,
                    "avg5_shots":    avg5,
                    "drop_pct":      drop_pct,
                    "dk_line_est":   dk_line_est,
                    "shots_adj":     round(adj_reel, 1),
                    "our_prob":      our_prob,
                    "edge_pct":      edge,
                    "est_odds":      est_odds,
                    "kelly":         _kelly(our_prob, B365_VIG_IMPL, B365_VIG_ODDS),
                    "opp_shots_rank": shots_rank_opp,
                    "season_goals":  p.get("season_goals", 0),
                    "season_points": p.get("season_points", 0),
                })

        retour.sort(key=lambda x: x["edge_pct"], reverse=True)
        return retour[:5]

    def _get_top_players(self, team_name: str, top_n: int = 10) -> list:
        abbr = TEAM_ABBR.get(team_name, "")
        if not abbr: return []
        if abbr in self._roster_cache:
            roster = self._roster_cache[abbr]
        else:
            data = _get(f"{NHL_API}/roster/{abbr}/current")
            if not data: return []
            self._roster_cache[abbr] = data
            roster = data

        players = []
        for group in ["forwards", "defensemen"]:
            for p in roster.get(group, []):
                if p.get("injuryStatus") in ("IR","LTIR","Day-to-Day","Injured"): continue
                fn   = p.get("firstName", {}).get("default", "")
                ln   = p.get("lastName",  {}).get("default", "")
                full = fn + " " + ln
                if self._lineup_fetcher and self._lineup_fetcher.is_injured(full, team_name): continue
                pid  = p.get("id")
                pos  = p.get("positionCode", "")
                stats = self._get_player_stats(pid, full)
                if stats:
                    stats["name"]     = full
                    stats["position"] = pos
                    stats["team"]     = team_name
                    players.append(stats)

        print(f"    -> {team_name}: {len(players)} joueurs avec stats")
        players.sort(key=lambda x: x.get("points_pg", 0), reverse=True)
        return players[:top_n]

    def _get_player_stats(self, player_id: int, name: str) -> Optional[dict]:
        if not player_id: return None
        key = str(player_id)
        if key in self._stats_cache: return self._stats_cache[key]
        data = _get(f"{NHL_API}/player/{player_id}/game-log/{SEASON}/{GAME_TYPE}")
        if not data: return None
        logs = data.get("gameLog", [])
        if not logs: return None
        logs10, logs5 = logs[:10], logs[:5]
        weights = [math.exp(-0.1*i) for i in range(len(logs10))]
        total_w = sum(weights)

        def parse_toi(val):
            if isinstance(val, str) and ":" in val:
                parts = val.split(":")
                return int(parts[0])*60 + int(parts[1])
            return float(val) if val else 0.0

        def wavg(field):
            return sum(
                parse_toi(logs10[i].get(field,0))*weights[i] if field=="toi"
                else logs10[i].get(field,0)*weights[i]
                for i in range(len(logs10))
            ) / total_w

        toi_sec = wavg("toi")
        result = {
            "shots_pg":     round(wavg("shots"),  2),
            "goals_pg":     round(wavg("goals"),  3),
            "assists_pg":   round(wavg("assists"), 3),
            "points_pg":    round(wavg("points"),  3),
            "toi_str":      f"{int(toi_sec//60)}:{int(toi_sec%60):02d}",
            "n_games":      len(logs10),
            "last5_shots":  sum(g.get("shots",0)  for g in logs5),
            "last5_goals":  sum(g.get("goals",0)  for g in logs5),
            "last5_points": sum(g.get("points",0) for g in logs5),
            "last10_shots": sum(g.get("shots",0)  for g in logs10),
            "last10_goals": sum(g.get("goals",0)  for g in logs10),
            "last10_points":sum(g.get("points",0) for g in logs10),
            "season_goals": sum(g.get("goals",0)  for g in logs),
            "season_points":sum(g.get("points",0) for g in logs),
        }
        self._stats_cache[key] = result
        return result

    def _get_goalie_stats(self, team_name: str) -> dict:
        abbr = TEAM_ABBR.get(team_name, "")
        if not abbr: return {}
        if abbr in self._roster_cache:
            roster = self._roster_cache[abbr]
        else:
            data = _get(f"{NHL_API}/roster/{abbr}/current")
            if not data: return {}
            self._roster_cache[abbr] = data
            roster = data
        goalies = roster.get("goalies", [])
        if not goalies: return {}
        df_goalie = ""
        if self._lineup_fetcher:
            lineup = self._lineup_fetcher.get_lineup(team_name)
            df_goalie = lineup.get("goalie", "")
        starter = None
        if df_goalie:
            starter = next((g for g in goalies if
                (g.get("firstName",{}).get("default","")+
                 " "+g.get("lastName",{}).get("default","")).strip()==df_goalie), None)
        if not starter:
            starter = max(goalies, key=lambda g: g.get("gamesPlayed",0)
                          if isinstance(g.get("gamesPlayed"),int) else 0)
        pid = starter.get("id")
        fn  = starter.get("firstName",{}).get("default","")
        ln  = starter.get("lastName", {}).get("default","")
        data = _get(f"{NHL_API}/player/{pid}/game-log/{SEASON}/{GAME_TYPE}")
        if not data: return {"name": fn+" "+ln}
        logs = data.get("gameLog",[])[:10]
        if not logs: return {"name": fn+" "+ln}
        weights = [math.exp(-0.1*i) for i in range(len(logs))]
        total_w = sum(weights)
        def parse_toi_g(val):
            if isinstance(val,str) and ":" in val:
                p = val.split(":")
                return int(p[0])*60+int(p[1])
            return float(val) if val else 0.0
        def wavg(field):
            return sum(parse_toi_g(logs[i].get(field,0))*weights[i] if field=="toi"
                       else logs[i].get(field,0)*weights[i]
                       for i in range(len(logs))) / total_w
        sa, ga = wavg("shotsAgainst"), wavg("goalsAgainst")
        saves  = sa - ga
        sv_pct = saves / max(sa, 1)
        gaa    = ga / max(wavg("toi")/3600, 0.01)
        return {"name":fn+" "+ln,"sv_pct":round(sv_pct,3),
                "saves_pg":round(saves,1),"gaa":round(gaa,2),"confirmed":bool(df_goalie)}
