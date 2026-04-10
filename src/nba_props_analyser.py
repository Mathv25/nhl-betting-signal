"""
NBA Props Analyzer — Meme logique que NHL
- Stats joueurs via Ball Don't Lie API (gratuite, pas de cle)
- Poisson sur points/rebounds/assists/3pts
- Filtre DEF adverse, forme recente last 5/10
- Meme calcul edge vs vig bet365 -110
"""

import requests
import time
import math
from typing import Optional

BDL_API = "https://api.balldontlie.io/v1"
# Ball Don't Lie v1 est accessible sans cle pour un usage modere

B365_VIG_IMPL = 52.36 / 100
B365_VIG_ODDS = 1.909
MIN_EDGE      = 8.0
MIN_ODDS_FILT = 1.65
MIN_PROB      = 0.40
MAX_PROB      = 0.61

# Stats defensives NBA — points accordes par match par equipe (2024-25)
# Rang 1 = meilleure defense, rang 30 = pire defense
TEAM_DEF_RATING = {
    "Oklahoma City Thunder":     107.8,
    "Minnesota Timberwolves":    109.2,
    "Boston Celtics":            109.5,
    "Cleveland Cavaliers":       110.1,
    "Indiana Pacers":            111.4,
    "New York Knicks":           111.8,
    "Memphis Grizzlies":         112.0,
    "Miami Heat":                112.3,
    "Houston Rockets":           112.5,
    "Golden State Warriors":     112.8,
    "Denver Nuggets":            113.0,
    "Los Angeles Lakers":        113.4,
    "Milwaukee Bucks":           113.6,
    "Philadelphia 76ers":        113.9,
    "Phoenix Suns":              114.2,
    "Dallas Mavericks":          114.5,
    "Sacramento Kings":          114.8,
    "New Orleans Pelicans":      115.0,
    "Atlanta Hawks":             115.3,
    "Brooklyn Nets":             115.6,
    "Utah Jazz":                 115.9,
    "Washington Wizards":        116.2,
    "Orlando Magic":             116.5,
    "Detroit Pistons":           116.8,
    "Portland Trail Blazers":    117.1,
    "Toronto Raptors":           117.4,
    "Chicago Bulls":             117.7,
    "Charlotte Hornets":         118.0,
    "Los Angeles Clippers":      118.3,
    "San Antonio Spurs":         118.9,
}

LEAGUE_AVG_DEF = 114.0

DEF_RANK = {}
def _build_ranks():
    for i, (t, _) in enumerate(sorted(TEAM_DEF_RATING.items(), key=lambda x: x[1])):
        DEF_RANK[t] = i + 1
_build_ranks()


def _get(url, params=None):
    time.sleep(0.5)
    try:
        r = requests.get(url, params=params or {}, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  BDL API: {e}")
        return None


def _pmf(lam, k):
    if lam <= 0: return 1.0 if k == 0 else 0.0
    fact = 1
    for i in range(2, k + 1): fact *= i
    return math.exp(-lam) * (lam ** k) / fact


def _poisson_over(lam, line):
    p = sum(_pmf(lam, k) for k in range(int(line) + 1, int(line) + 40))
    return round(min(max(p, 0.01), 0.99) * 100, 1)


def _kelly(our_prob_pct, odds):
    b = odds - 1
    if b <= 0: return 0.0
    k = ((b * our_prob_pct / 100) - (1 - our_prob_pct / 100)) / b / 4 * 100
    return round(max(k, 0), 1)


def _edge(our_pct, impl_pct):
    if impl_pct <= 0: return 0.0
    return round((our_pct - impl_pct) / impl_pct * 100, 1)


def _est_odds(prob_pct):
    if prob_pct <= 0: return 99.0
    return round((1 / (prob_pct / 100)) * 0.9524, 2)


class NBAPropsAnalyzer:

    def __init__(self):
        self._player_cache = {}   # name -> BDL player id
        self._stats_cache  = {}   # player_id -> stats dict
        self._season       = "2024-25"

    def analyze_game(self, game: dict, props_by_market: dict) -> dict:
        """
        Analyse les props d'un match NBA.
        game: dict avec home_team, away_team
        props_by_market: {"player_points": [...], "player_rebounds": [...], ...}
        """
        home = game["home_team"]
        away = game["away_team"]
        print(f"  NBA Props: {away} @ {home}...")

        bets = []
        seen_players = set()

        for market, props in props_by_market.items():
            for prop in props:
                if prop.get("direction") != "over": continue

                player = prop.get("player", "")
                line   = prop.get("line")
                odds   = prop.get("odds", 0)
                impl   = prop.get("implied_prob", 52.4)

                if not player or line is None: continue
                key = (player, market)
                if key in seen_players: continue
                seen_players.add(key)

                stats = self._get_player_stats(player)
                if not stats: continue

                team     = home if player in stats.get("_team_guess_home", set()) else away
                opponent = away if team == home else home
                def_rank = DEF_RANK.get(opponent, 15)
                def_pts  = TEAM_DEF_RATING.get(opponent, LEAGUE_AVG_DEF)
                def_factor = def_pts / LEAGUE_AVG_DEF

                stat_key = {
                    "player_points":   "pts",
                    "player_rebounds": "reb",
                    "player_assists":  "ast",
                    "player_threes":   "fg3m",
                    "player_blocks":   "blk",
                    "player_steals":   "stl",
                    "player_points_rebounds_assists": "pra",
                }.get(market, "pts")

                avg = stats.get(f"{stat_key}_avg10", 0)
                if avg <= 0: continue

                # Ajustement DEF adverse (points et PRA sensibles, rebounds/assists moins)
                if stat_key in ("pts", "pra"):
                    adj = avg * def_factor
                elif stat_key in ("ast",):
                    adj = avg * (def_factor * 0.5 + 0.5)  # moins sensible
                else:
                    adj = avg  # rebounds/blk/stl peu affectes par la DEF

                adj = round(min(adj, avg * 1.3), 1)  # plafond +30%

                # Ligne optimale
                best_line = line
                sl = None
                sp = 0.0
                se = 0.0
                for cl_mult in [1.0, 0.5, 1.5]:
                    cl = round(line * cl_mult * 2) / 2
                    if cl <= 0: continue
                    pv = _poisson_over(adj, cl) / 100
                    if MIN_PROB <= pv <= MAX_PROB:
                        sl = cl
                        sp = round(pv * 100, 1)
                        se = _edge(sp, B365_VIG_IMPL * 100)
                        break

                if sl is None:
                    # Fallback: utilise la vraie ligne DK
                    sl = line
                    sp = _poisson_over(adj, sl)
                    se = _edge(sp, B365_VIG_IMPL * 100)

                est_odds_val = _est_odds(sp)

                if se < MIN_EDGE or est_odds_val < MIN_ODDS_FILT:
                    continue

                # Contexte
                last5  = stats.get(f"{stat_key}_last5",  [])
                last10 = stats.get(f"{stat_key}_last10", [])
                avg5   = round(sum(last5) / len(last5), 1) if last5 else 0
                avg10  = round(sum(last10) / len(last10), 1) if last10 else avg

                context = []
                if avg5 > avg10 * 1.20:
                    context.append(f"🔥 En hausse — {avg5} last 5 vs {avg10} last 10")
                elif avg5 < avg10 * 0.75:
                    context.append(f"❄️ En baisse — {avg5} last 5 vs {avg10} last 10")
                if def_rank >= 25:
                    context.append(f"🎯 Matchup ideal — {opponent.split()[-1]} DEF #{def_rank} ligue")
                elif def_rank <= 5:
                    context.append(f"⚠️ DEF solide — {opponent.split()[-1]} #{def_rank} ligue")

                market_labels = {
                    "player_points":   "Points",
                    "player_rebounds": "Rebounds",
                    "player_assists":  "Assists",
                    "player_threes":   "3-Pointers",
                    "player_blocks":   "Blocks",
                    "player_steals":   "Steals",
                    "player_points_rebounds_assists": "PRA",
                }
                label = market_labels.get(market, market)

                bets.append({
                    "player":       player,
                    "team":         team,
                    "opponent":     opponent,
                    "market":       f"{label} Over {sl}",
                    "market_type":  stat_key,
                    "our_prob":     sp,
                    "edge_pct":     se,
                    "kelly":        _kelly(sp, B365_VIG_ODDS),
                    "est_odds":     est_odds_val,
                    "dk_line":      line,
                    "adj_line":     sl,
                    "avg10":        avg10,
                    "avg5":         avg5,
                    "adj_proj":     adj,
                    "def_rank":     def_rank,
                    "def_pts":      round(def_pts, 1),
                    "b365_implied": round(B365_VIG_IMPL * 100, 1),
                    "context":      context,
                })

        bets.sort(key=lambda x: x["edge_pct"], reverse=True)

        return {
            "home_team": home,
            "away_team": away,
            "bets":      bets[:6],
        }

    def _get_player_stats(self, player_name: str) -> Optional[dict]:
        if player_name in self._stats_cache:
            return self._stats_cache[player_name]

        # 1. Trouver le joueur
        player_id = self._find_player(player_name)
        if not player_id:
            return None

        # 2. Game logs — saison courante
        data = _get(f"{BDL_API}/stats", {
            "player_ids[]": player_id,
            "seasons[]":    2024,
            "per_page":     15,
            "postseason":   "false",
        })
        if not data:
            return None

        logs = sorted(
            [g for g in data.get("data", []) if g.get("min") and g["min"] not in ("", "0")],
            key=lambda g: g.get("game", {}).get("date", ""),
            reverse=True
        )[:10]

        if len(logs) < 3:
            return None

        def extract(logs, key, n):
            vals = []
            for g in logs[:n]:
                v = g.get(key)
                if v is not None:
                    try: vals.append(float(v))
                    except: pass
            return vals

        pts10  = extract(logs, "pts",  10)
        reb10  = extract(logs, "reb",  10)
        ast10  = extract(logs, "ast",  10)
        fg3m10 = extract(logs, "fg3m", 10)
        blk10  = extract(logs, "blk",  10)
        stl10  = extract(logs, "stl",  10)
        pts5   = extract(logs, "pts",  5)
        reb5   = extract(logs, "reb",  5)
        ast5   = extract(logs, "ast",  5)
        fg3m5  = extract(logs, "fg3m", 5)
        blk5   = extract(logs, "blk",  5)
        stl5   = extract(logs, "stl",  5)

        def avg(lst): return round(sum(lst) / len(lst), 2) if lst else 0.0
        def pra(lst_pts, lst_reb, lst_ast):
            return [p+r+a for p,r,a in zip(lst_pts, lst_reb, lst_ast)]

        pra10 = pra(pts10, reb10, ast10)
        pra5  = pra(pts5,  reb5,  ast5)

        result = {
            "pts_avg10":  avg(pts10),  "pts_last10": pts10,  "pts_last5": pts5,
            "reb_avg10":  avg(reb10),  "reb_last10": reb10,  "reb_last5": reb5,
            "ast_avg10":  avg(ast10),  "ast_last10": ast10,  "ast_last5": ast5,
            "fg3m_avg10": avg(fg3m10), "fg3m_last10": fg3m10, "fg3m_last5": fg3m5,
            "blk_avg10":  avg(blk10),  "blk_last10": blk10,  "blk_last5": blk5,
            "stl_avg10":  avg(stl10),  "stl_last10": stl10,  "stl_last5": stl5,
            "pra_avg10":  avg(pra10),  "pra_last10": pra10,  "pra_last5": pra5,
            "n_games":    len(logs),
        }
        self._stats_cache[player_name] = result
        return result

    def _find_player(self, name: str) -> Optional[int]:
        if name in self._player_cache:
            return self._player_cache[name]
        parts = name.split()
        search = parts[-1] if parts else name
        data = _get(f"{BDL_API}/players", {"search": search, "per_page": 10})
        if not data:
            return None
        name_lower = name.lower()
        for p in data.get("data", []):
            fn = p.get("first_name", "")
            ln = p.get("last_name", "")
            full = f"{fn} {ln}".lower()
            if full == name_lower or name_lower in full:
                pid = p.get("id")
                self._player_cache[name] = pid
                return pid
        return None
