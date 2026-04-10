"""
NBA Props Analyzer v3 — Sans API externe
Utilise les lignes DK comme proxy de la moyenne du joueur.
Logique: DK fixe ses lignes a ~52% implied. Notre edge vient
de l'ajustement DEF adverse et de la forme recente via BDL API.
Si BDL echoue, on calcule quand meme un edge base sur le matchup.
"""

import requests
import time
import math
from typing import Optional

B365_VIG_IMPL = 52.36 / 100
B365_VIG_ODDS = 1.909
MIN_EDGE      = 5.0    # Seuil plus bas pour NBA (plus de variabilite)
MIN_ODDS_FILT = 1.60
MIN_PROB      = 0.38
MAX_PROB      = 0.63

BDL_BASE = "https://api.balldontlie.io/v1"

# Stats DEF par equipe — pts accordes/match et rang (2024-25)
TEAM_DEF_PTS = {
    "Oklahoma City Thunder":107.8,"Minnesota Timberwolves":109.2,
    "Boston Celtics":109.5,"Cleveland Cavaliers":110.1,
    "Indiana Pacers":111.4,"New York Knicks":111.8,
    "Memphis Grizzlies":112.0,"Miami Heat":112.3,
    "Houston Rockets":112.5,"Golden State Warriors":112.8,
    "Denver Nuggets":113.0,"Los Angeles Lakers":113.4,
    "Milwaukee Bucks":113.6,"Philadelphia 76ers":113.9,
    "Phoenix Suns":114.2,"Dallas Mavericks":114.5,
    "Sacramento Kings":114.8,"New Orleans Pelicans":115.0,
    "Atlanta Hawks":115.3,"Brooklyn Nets":115.6,
    "Utah Jazz":115.9,"Washington Wizards":116.2,
    "Orlando Magic":116.5,"Detroit Pistons":116.8,
    "Portland Trail Blazers":117.1,"Toronto Raptors":117.4,
    "Chicago Bulls":117.7,"Charlotte Hornets":118.0,
    "Los Angeles Clippers":118.3,"San Antonio Spurs":118.9,
}
LEAGUE_AVG_DEF = 114.0
DEF_RANK = {t:i+1 for i,(t,_) in enumerate(sorted(TEAM_DEF_PTS.items(), key=lambda x:x[1]))}

# Ajustements DEF par stat
# Points: tres sensible a la DEF
# Rebounds: peu sensible
# Assists: moderement sensible
# 3pts: moderement sensible
DEF_SENSITIVITY = {
    "pts": 1.0, "pra": 0.8, "ast": 0.5,
    "reb": 0.2, "fg3m": 0.5, "blk": 0.1, "stl": 0.1,
}


def _pmf(lam, k):
    if lam <= 0: return 1.0 if k == 0 else 0.0
    f = 1
    for i in range(2, k+1): f *= i
    return math.exp(-lam) * (lam**k) / f

def _poisson_over(lam, line):
    return round(min(max(sum(_pmf(lam,k) for k in range(int(line)+1, int(line)+40)),0.01),0.99)*100,1)

def _kelly(p, odds):
    b = odds-1
    return round(max(((b*p/100)-(1-p/100))/b/4*100,0),1) if b>0 else 0.0

def _edge(our, impl):
    return round((our-impl)/impl*100,1) if impl>0 else 0.0

def _est_odds(p):
    return round((1/(p/100))*0.9524,2) if p>0 else 99.0

def _try_bdl_stats(player_name: str) -> Optional[dict]:
    """Tente de recuperer les stats BDL. Retourne None si echec."""
    try:
        parts = player_name.split()
        search = parts[-1] if parts else player_name
        r = requests.get(f"{BDL_BASE}/players",
                        params={"search":search,"per_page":10},
                        timeout=6)
        if r.status_code != 200: return None
        players = r.json().get("data",[])
        pid = None
        for p in players:
            full = f"{p.get('first_name','')} {p.get('last_name','')}".lower()
            if full == player_name.lower() or player_name.lower() in full:
                pid = p["id"]
                break
        if not pid: return None

        time.sleep(0.4)
        r2 = requests.get(f"{BDL_BASE}/stats",
                         params={"player_ids[]":pid,"seasons[]":2024,"per_page":10,"postseason":"false"},
                         timeout=6)
        if r2.status_code != 200: return None
        logs = sorted([g for g in r2.json().get("data",[])
                       if g.get("min") and g["min"] not in ("","0")],
                      key=lambda g:g.get("game",{}).get("date",""), reverse=True)[:10]
        if len(logs) < 3: return None

        def ex(logs, k, n):
            v = []
            for g in logs[:n]:
                try: v.append(float(g.get(k,0) or 0))
                except: pass
            return v

        pts10 = ex(logs,"pts",10); pts5 = ex(logs,"pts",5)
        reb10 = ex(logs,"reb",10); reb5 = ex(logs,"reb",5)
        ast10 = ex(logs,"ast",10); ast5 = ex(logs,"ast",5)
        fg3m10= ex(logs,"fg3m",10);fg3m5= ex(logs,"fg3m",5)
        blk10 = ex(logs,"blk",10); stl10= ex(logs,"stl",10)

        def avg(l): return round(sum(l)/len(l),1) if l else 0.0
        pra10 = [p+r+a for p,r,a in zip(pts10,reb10,ast10)]
        pra5  = [p+r+a for p,r,a in zip(pts5, reb5, ast5)]

        return {
            "pts_avg10":avg(pts10),"pts_avg5":avg(pts5),
            "reb_avg10":avg(reb10),"reb_avg5":avg(reb5),
            "ast_avg10":avg(ast10),"ast_avg5":avg(ast5),
            "fg3m_avg10":avg(fg3m10),"fg3m_avg5":avg(fg3m5),
            "blk_avg10":avg(blk10),"stl_avg10":avg(stl10),
            "pra_avg10":avg(pra10),"pra_avg5":avg(pra5),
            "source":"bdl",
        }
    except Exception:
        return None


class NBAPropsAnalyzer:

    def __init__(self):
        self._stats_cache = {}

    def analyze_game(self, game: dict, props_by_market: dict) -> dict:
        home = game["home_team"]
        away = game["away_team"]
        print(f"  NBA Props: {away} @ {home}...")

        bets = []
        seen = set()

        for market, props in props_by_market.items():
            for prop in props:
                if prop.get("direction") != "over": continue
                player = prop.get("player","")
                line   = prop.get("line")
                odds   = prop.get("odds",1.9)
                impl   = prop.get("implied_prob", B365_VIG_IMPL*100)
                if not player or line is None: continue
                key = (player, market)
                if key in seen: continue
                seen.add(key)

                stat_key = {
                    "player_points":"pts","player_rebounds":"reb",
                    "player_assists":"ast","player_threes":"fg3m",
                    "player_blocks":"blk","player_steals":"stl",
                    "player_points_rebounds_assists":"pra",
                }.get(market,"pts")

                # Determine equipe via ordre home/away dans props
                # DK liste home en premier generalement
                team = home  # approximation
                opponent = away

                def_pts   = TEAM_DEF_PTS.get(opponent, LEAGUE_AVG_DEF)
                def_rank  = DEF_RANK.get(opponent, 15)
                sens      = DEF_SENSITIVITY.get(stat_key, 0.5)
                def_factor = 1.0 + (def_pts - LEAGUE_AVG_DEF) / LEAGUE_AVG_DEF * sens

                # Tente BDL pour les stats reelles
                if player not in self._stats_cache:
                    self._stats_cache[player] = _try_bdl_stats(player)
                stats = self._stats_cache[player]

                if stats:
                    avg10 = stats.get(f"{stat_key}_avg10", 0)
                    avg5  = stats.get(f"{stat_key}_avg5",  0)
                else:
                    # Fallback: utilise la ligne DK comme proxy de la moyenne
                    # DK fixe lignes a ~50%, donc la ligne ≈ mediane ≈ ~moyenne-0.3
                    avg10 = line + 0.3
                    avg5  = 0

                if avg10 <= 0: continue

                adj = round(min(avg10 * def_factor, avg10 * 1.35), 1)

                # Edge: compare notre prob (basee sur avg ajuste) vs la ligne DK
                sp = _poisson_over(adj, line)
                se = _edge(sp, B365_VIG_IMPL*100)
                eo = _est_odds(sp)

                if se < MIN_EDGE or eo < MIN_ODDS_FILT: continue
                if not (MIN_PROB*100 <= sp <= MAX_PROB*100): continue

                context = []
                if avg5 > 0:
                    if avg5 > avg10 * 1.20:
                        context.append(f"🔥 En hausse — {avg5} last 5 vs {avg10} last 10")
                    elif avg5 < avg10 * 0.75:
                        context.append(f"❄️ En baisse — {avg5} last 5 vs {avg10} last 10")
                if def_rank >= 25:
                    context.append(f"🎯 Matchup ideal — {opponent.split()[-1]} DEF #{def_rank}")
                elif def_rank <= 5:
                    context.append(f"⚠️ DEF solide — {opponent.split()[-1]} #{def_rank}")
                if not stats:
                    context.append("📊 Ligne DK utilisee comme proxy (stats BDL indisponibles)")

                labels = {
                    "player_points":"Points","player_rebounds":"Rebounds",
                    "player_assists":"Assists","player_threes":"3-Pointers",
                    "player_blocks":"Blocks","player_steals":"Steals",
                    "player_points_rebounds_assists":"PRA",
                }
                bets.append({
                    "player":player,"team":team,"opponent":opponent,
                    "market":f"{labels.get(market,market)} Over {line}",
                    "market_type":stat_key,
                    "our_prob":sp,"edge_pct":se,
                    "kelly":_kelly(sp,B365_VIG_ODDS),
                    "est_odds":eo,"dk_line":line,"adj_line":line,
                    "avg10":avg10,"avg5":avg5,"adj_proj":adj,
                    "def_rank":def_rank,"def_pts":round(def_pts,1),
                    "b365_implied":round(B365_VIG_IMPL*100,1),
                    "context":context,
                    "has_real_stats": bool(stats),
                })

        bets.sort(key=lambda x: x["edge_pct"], reverse=True)
        return {"home_team":home,"away_team":away,"bets":bets[:6]}
