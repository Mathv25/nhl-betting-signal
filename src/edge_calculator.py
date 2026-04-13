"""
Edge Calculator v3 — Modele NHL calibre post-backtest
Corrections majeures:
1. Motivation reduite vers 1.0 (0.95-1.03 au lieu de 0.80-1.08)
2. Application differentielle motivation (pas multiplicative sur les deux equipes)
3. Caps edges conserves (15% ML, 12% PL, 20% Totals)
4. MIN_EDGE remonte a 5% (les 3-5% ne sont pas rentables)
"""

import math
import time
import requests
from typing import Optional
from nhl_stats import TeamStats, PlayerStats, LineupValidator

MIN_EDGE_PCT  = 5.0   # Monte de 3 a 5 — les 3-5% perdent de l'argent
MIN_ODDS      = 1.25
MAX_ODDS      = 10.0
LEAGUE_AVG_GF = 3.10
HOME_FACTOR   = 1.045
AWAY_FACTOR   = 0.955
B2B_FACTOR    = 0.93
KELLY_DIVISOR = 4
SHRINKAGE     = 0.25

MAX_EDGE_ML    = 15.0
MAX_EDGE_PL    = 12.0
MAX_EDGE_TOT   = 20.0

MAX_PROB_MINUS_15 = 0.40
MAX_PROB_PLUS_15  = 0.82

NHL_API = "https://api-web.nhle.com/v1"
SEASON  = "20252026"

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

# ── MOTIVATION RECALIBREE ────────────────────────────────────────────────────
# Range reduit: 0.95-1.03 au lieu de 0.80-1.08
# Une equipe NHL joue toujours a ~95%+ de son niveau meme sans enjeu
# L'effet reel d'une equipe "sans enjeu" = -3 a -5% max, pas -15 a -20%
# Source backtest: les bets "motivation" avaient 25% WR = pire que le hasard
MOTIVATION_OVERRIDE = {
    # Equipes sans enjeu — reduction MINIMALE
    "Florida Panthers":   0.97,
    "Vancouver Canucks":  0.96,
    "Toronto Maple Leafs": 0.97,
    "Chicago Blackhawks": 0.96,
    "Anaheim Ducks":      0.97,
    "San Jose Sharks":    0.95,
    "Calgary Flames":     0.96,
    "Nashville Predators": 0.96,
    "Detroit Red Wings":  0.97,
    "New York Rangers":   0.97,
    "St. Louis Blues":    0.96,
    "Winnipeg Jets":      0.97,
    # Equipes en course playoff — boost modere
    "Ottawa Senators":    1.03,
    "Buffalo Sabres":     1.02,
    "Tampa Bay Lightning": 1.02,
    "Montreal Canadiens": 1.02,
    "Carolina Hurricanes": 1.02,
    "Colorado Avalanche": 1.03,
    "Dallas Stars":       1.02,
    "Minnesota Wild":     1.02,
    "Utah Mammoth":       1.01,
    "New York Islanders": 1.02,
    "Columbus Blue Jackets": 1.02,
    "Philadelphia Flyers": 1.02,
}

# Seuil minimum de differentiel de motivation pour mentionner dans le signal
# (evite de signaler chaque match comme "motivation" alors que l'effet est minimal)
MOTIV_NOTE_THRESHOLD = 0.03  # seulement si ecart >= 3% entre les deux equipes


def _api_get(url: str) -> Optional[dict]:
    time.sleep(0.3)
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _parse_toi(val) -> float:
    if isinstance(val, str) and ":" in val:
        p = val.split(":")
        return int(p[0]) * 60 + int(p[1])
    return float(val) if val else 0.0


class EdgeCalculator:

    def __init__(self):
        self.team_stats   = TeamStats()
        self.player_stats = PlayerStats()
        self.lineup       = LineupValidator()
        self._standings_cache = None
        self._recent_cache    = {}

    def calculate_all_edges(self, game: dict) -> list:
        edges = []
        home  = game["home_team"]
        away  = game["away_team"]
        mkts  = game.get("markets", {})
        label = f"{away} @ {home}"
        date  = game.get("commence_time", "")[:10]

        home_stats = self.team_stats.get(home)
        away_stats = self.team_stats.get(away)

        home_b2b = self.lineup.is_back_to_back(home, date)
        away_b2b = self.lineup.is_back_to_back(away, date)

        home_goalie = self.lineup.get_probable_starter(home)
        away_goalie = self.lineup.get_probable_starter(away)

        home_recent = self._get_recent_stats(home)
        away_recent = self._get_recent_stats(away)
        home_hybrid = self._hybrid_stats(home_stats, home_recent)
        away_hybrid = self._hybrid_stats(away_stats, away_recent)

        home_motiv = self._motivation(home)
        away_motiv = self._motivation(away)

        lh, la = self._lambdas(
            home_hybrid, away_hybrid,
            home_b2b, away_b2b,
            home_motiv, away_motiv
        )

        # Notes contextuelles — seulement si ecart significatif
        context_notes = []
        motiv_diff = abs(home_motiv - away_motiv)
        if motiv_diff >= MOTIV_NOTE_THRESHOLD:
            if home_motiv < away_motiv and home_motiv < 0.97:
                context_notes.append(f"⚠️ {home.split()[0]} sans enjeu")
            elif away_motiv < home_motiv and away_motiv < 0.97:
                context_notes.append(f"⚠️ {away.split()[0]} sans enjeu")
            if home_motiv > 1.02 and home_motiv > away_motiv:
                context_notes.append(f"🔥 {home.split()[0]} en course playoff")
            elif away_motiv > 1.02 and away_motiv > home_motiv:
                context_notes.append(f"🔥 {away.split()[0]} en course playoff")

        if "moneyline" in mkts:
            edges += self._moneyline_edges(mkts["moneyline"], lh, la, label, home, away, context_notes)
        if "puck_line" in mkts:
            edges += self._puck_line_edges(mkts["puck_line"], lh, la, label, context_notes)
        if "totals" in mkts:
            edges += self._total_edges(mkts["totals"], lh, la, label,
                                        home_goalie, away_goalie, context_notes)
        if "first_period_ml" in mkts:
            edges += self._first_period_ml(mkts["first_period_ml"], lh, la, label)
        if "first_period_totals" in mkts:
            edges += self._first_period_totals(mkts["first_period_totals"], lh, la, label)

        props = mkts.get("player_props", [])
        edges += self._player_prop_edges(props, home, away, home_goalie, away_goalie, label)

        return [e for e in edges if e.get("edge_pct", 0) >= MIN_EDGE_PCT]

    # ── Stats hybrides ────────────────────────────────────────────────────────

    def _get_recent_stats(self, team_name: str, n: int = 15) -> dict:
        if team_name in self._recent_cache:
            return self._recent_cache[team_name]

        abbr = TEAM_ABBR.get(team_name, "")
        if not abbr:
            return {}

        schedule = _api_get(f"{NHL_API}/club-schedule-season/{abbr}/now")
        if not schedule:
            self._recent_cache[team_name] = {}
            return {}

        games = [g for g in schedule.get("games", [])
                 if g.get("gameState") in ("FINAL", "OFF", "CRIT")]
        games = sorted(games, key=lambda g: g.get("gameDate", ""), reverse=True)[:n]

        if not games:
            self._recent_cache[team_name] = {}
            return {}

        gf_list, ga_list = [], []
        for g in games:
            h_abbr  = g.get("homeTeam", {}).get("abbrev", "")
            is_home = (h_abbr == abbr)
            home_score = g.get("homeTeam", {}).get("score", 0) or 0
            away_score = g.get("awayTeam", {}).get("score", 0) or 0
            if is_home:
                gf_list.append(home_score)
                ga_list.append(away_score)
            else:
                gf_list.append(away_score)
                ga_list.append(home_score)

        if not gf_list:
            self._recent_cache[team_name] = {}
            return {}

        recent = {
            "gf_pg": round(sum(gf_list) / len(gf_list), 3),
            "ga_pg": round(sum(ga_list) / len(ga_list), 3),
            "games": len(gf_list),
        }
        print(f"  Recent {team_name} (last {len(gf_list)}): GF {recent['gf_pg']:.2f} GA {recent['ga_pg']:.2f}")
        self._recent_cache[team_name] = recent
        return recent

    def _hybrid_stats(self, season_stats: dict, recent_stats: dict) -> dict:
        if not recent_stats or recent_stats.get("games", 0) < 5:
            return season_stats
        hybrid = dict(season_stats)
        hybrid["gf_pg"] = round(
            recent_stats["gf_pg"] * 0.60 + season_stats.get("gf_pg", LEAGUE_AVG_GF) * 0.40, 3
        )
        hybrid["ga_pg"] = round(
            recent_stats["ga_pg"] * 0.60 + season_stats.get("ga_pg", LEAGUE_AVG_GF) * 0.40, 3
        )
        return hybrid

    # ── Motivation ────────────────────────────────────────────────────────────

    def _motivation(self, team_name: str) -> float:
        return MOTIVATION_OVERRIDE.get(team_name, 1.0)

    # ── Lambdas Poisson ───────────────────────────────────────────────────────

    def _lambdas(self, hs, as_, home_b2b, away_b2b, home_motiv, away_motiv):
        lh_raw = (hs["gf_pg"] * HOME_FACTOR * as_["ga_pg"]) / LEAGUE_AVG_GF
        la_raw = (as_["gf_pg"] * AWAY_FACTOR * hs["ga_pg"]) / LEAGUE_AVG_GF

        lh = lh_raw * (1 - SHRINKAGE) + LEAGUE_AVG_GF * SHRINKAGE
        la = la_raw * (1 - SHRINKAGE) + LEAGUE_AVG_GF * SHRINKAGE

        lh *= self._pp_factor(hs.get("pp_pct", 20.0), as_.get("pk_pct", 80.0))
        la *= self._pp_factor(as_.get("pp_pct", 20.0), hs.get("pk_pct", 80.0))

        league_sv = 0.910
        lh *= (league_sv / max(as_.get("starter_sv_pct", 0.910), 0.880))
        la *= (league_sv / max(hs.get("starter_sv_pct", 0.910), 0.880))

        if home_b2b: lh *= B2B_FACTOR
        if away_b2b: la *= B2B_FACTOR

        # Motivation — applique seulement le DIFFERENTIEL, pas les valeurs absolues
        # Evite de doubler l'effet quand les deux equipes ont des motivations differentes
        motiv_diff = home_motiv - away_motiv
        if abs(motiv_diff) >= 0.01:
            # Home beneficie si home_motiv > away_motiv et vice versa
            lh *= (1.0 + motiv_diff * 0.5)   # effet attenue de 50%
            la *= (1.0 - motiv_diff * 0.5)

        lh = round(min(max(lh, 0.8), 5.0), 4)
        la = round(min(max(la, 0.8), 5.0), 4)
        return lh, la

    @staticmethod
    def _pp_factor(pp_pct, pk_pct):
        off_edge = (pp_pct - 20.0) / 20.0
        def_edge = (pk_pct - 80.0) / 80.0
        return 1.0 + min(max((off_edge - def_edge) * 0.12, -0.05), 0.05)

    # ── Marchés ───────────────────────────────────────────────────────────────

    def _moneyline_edges(self, market, lh, la, label, home, away, context_notes):
        edges = []
        hp = self._win_prob(lh, la)
        ap = 1 - hp
        for side, prob in [("home", hp), ("away", ap)]:
            m = market.get(side)
            if not m: continue
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"],
                           max_edge=MAX_EDGE_ML)
            if e:
                edges.append({**e,
                    "type":          "Moneyline",
                    "bet":           f"{m['team']} ML",
                    "our_prob":      round(prob * 100, 1),
                    "b365_implied":  m["implied_prob"],
                    "b365_odds":     m["odds_decimal"],
                    "game":          label,
                    "note":          " | ".join(context_notes) if context_notes else f"vs {away if side == 'home' else home}",
                    "context_notes": context_notes,
                })
        return edges

    def _puck_line_edges(self, market, lh, la, label, context_notes):
        edges = []
        for side in ["home", "away"]:
            m = market.get(side)
            if not m: continue
            spread = m.get("spread", -1.5 if side == "home" else 1.5)
            prob   = self._spread_prob(lh, la, spread, side)
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"],
                           max_edge=MAX_EDGE_PL)
            if e:
                sign = "+" if spread > 0 else ""
                edges.append({**e,
                    "type":          "Puck Line",
                    "bet":           f"{m['team']} {sign}{spread}",
                    "our_prob":      round(prob * 100, 1),
                    "b365_implied":  m["implied_prob"],
                    "b365_odds":     m["odds_decimal"],
                    "game":          label,
                    "note":          " | ".join(context_notes) if context_notes else f"Spread {sign}{spread} buts",
                    "context_notes": context_notes,
                })
        return edges

    def _total_edges(self, market, lh, la, label, home_goalie, away_goalie, context_notes):
        edges    = []
        expected = lh + la

        goalies_confirmed = bool(home_goalie and away_goalie)
        if not goalies_confirmed:
            print(f"  Total skip {label}: gardiens non confirmes")
            return []

        for direction in ["over", "under"]:
            m = market.get(direction)
            if not m or not m.get("line"): continue
            line = m["line"]
            prob = self._total_prob(expected, line, direction)
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"],
                           max_edge=MAX_EDGE_TOT)
            if e:
                notes = list(context_notes)
                notes.append(f"Total attendu: {round(expected, 1)} buts")
                edges.append({**e,
                    "type":          "Total buts",
                    "bet":           f"{direction.capitalize()} {line}",
                    "our_prob":      round(prob * 100, 1),
                    "b365_implied":  m["implied_prob"],
                    "b365_odds":     m["odds_decimal"],
                    "game":          label,
                    "note":          " | ".join(notes),
                    "context_notes": notes,
                })
        return edges

    def _first_period_ml(self, market, lh, la, label):
        edges = []
        lh1, la1 = lh * 0.33, la * 0.33
        hp = self._win_prob(lh1, la1)
        for side, prob in [("home", hp), ("away", 1 - hp)]:
            m = market.get(side)
            if not m: continue
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"],
                           max_edge=MAX_EDGE_ML)
            if e:
                edges.append({**e,
                    "type":         "1re periode ML",
                    "bet":          f"{m['team']} gagne 1re periode",
                    "our_prob":     round(prob * 100, 1),
                    "b365_implied": m["implied_prob"],
                    "b365_odds":    m["odds_decimal"],
                    "game":         label,
                    "note":         "33% des buts en 1P",
                })
        return edges

    def _first_period_totals(self, market, lh, la, label):
        edges = []
        exp1p = (lh + la) * 0.33
        for direction in ["over", "under"]:
            m = market.get(direction)
            if not m or not m.get("line"): continue
            prob = self._total_prob(exp1p, m["line"], direction)
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"],
                           max_edge=MAX_EDGE_TOT)
            if e:
                edges.append({**e,
                    "type":         "Total 1re periode",
                    "bet":          f"{direction.capitalize()} {m['line']} (1P)",
                    "our_prob":     round(prob * 100, 1),
                    "b365_implied": m["implied_prob"],
                    "b365_odds":    m["odds_decimal"],
                    "game":         label,
                    "note":         f"Total 1P attendu: {round(exp1p, 2)}",
                })
        return edges

    def _player_prop_edges(self, props, home, away, home_goalie, away_goalie, label):
        edges = []
        for prop in props:
            player    = prop.get("player", "")
            market    = prop.get("market", "")
            direction = prop.get("direction", "").lower()
            line      = prop.get("line")
            b365_odds = prop.get("odds_decimal", 0)
            b365_impl = prop.get("implied_prob", 0)
            if not player or line is None: continue

            team     = self._find_player_team(player, home, away)
            opponent = away if team == home else home
            our_prob = None
            note     = ""

            if market == "player_shots_on_goal":
                stats    = self.player_stats.get_skater(player, team)
                our_prob = self._shots_prob(stats["shots_pg"], stats["shots_std"], line, direction)
                note     = f"Moy. {stats['shots_pg']} shots/m"
            elif market == "player_goals":
                stats    = self.player_stats.get_skater(player, team)
                our_prob = self._goals_prob(stats["goals_pg"], line, direction)
                note     = f"Moy. {stats['goals_pg']} buts/m"
            elif market == "player_assists":
                stats    = self.player_stats.get_skater(player, team)
                our_prob = self._goals_prob(stats["assists_pg"], line, direction)
                note     = f"Moy. {stats['assists_pg']} passes/m"
            elif market == "player_points":
                stats    = self.player_stats.get_skater(player, team)
                our_prob = self._goals_prob(stats["points_pg"], line, direction)
                note     = f"Moy. {stats['points_pg']} pts/m"
            elif market == "player_saves":
                g_name   = (home_goalie if team == home else away_goalie) or player
                stats    = self.player_stats.get_goalie(g_name, team)
                opp_stat = self.team_stats.get(opponent)
                exp_sv   = opp_stat["shots_pg"] * stats["sv_pct"]
                our_prob = self._saves_prob(exp_sv, stats["saves_std"], line, direction)
                note     = f"Moy. {stats['saves_pg']} saves/m"
            else:
                continue

            if our_prob is None: continue
            e = self._edge(our_prob, b365_impl / 100, b365_odds)
            if e:
                labels = {
                    "player_shots_on_goal": "Shots on goal",
                    "player_goals":         "Buts",
                    "player_assists":       "Passes",
                    "player_points":        "Points",
                    "player_saves":         "Saves",
                }
                edges.append({**e,
                    "type":         f"Prop — {labels.get(market, market)}",
                    "bet":          f"{player} {direction.capitalize()} {line}",
                    "our_prob":     round(our_prob * 100, 1),
                    "b365_implied": b365_impl,
                    "b365_odds":    b365_odds,
                    "game":         label,
                    "note":         note,
                })
        return edges

    # ── Distributions ──────────────────────────────────────────────────────────

    def _win_prob(self, lh, la):
        p_home = p_tie = 0.0
        for h in range(12):
            ph = self._pmf(lh, h)
            for a in range(12):
                pa = self._pmf(la, a)
                p  = ph * pa
                if h > a:    p_home += p
                elif h == a: p_tie  += p
        return round(min(max(p_home + p_tie * 0.5, 0.05), 0.95), 4)

    def _spread_prob(self, lh, la, spread, side):
        p = 0.0
        for h in range(15):
            ph = self._pmf(lh, h)
            for a in range(15):
                pa   = self._pmf(la, a)
                diff = h - a
                if side == "home":
                    covers = diff >= math.ceil(abs(spread)) if spread < 0 else diff >= -math.floor(spread)
                else:
                    covers = diff <= -math.ceil(abs(spread)) if spread < 0 else diff <= math.floor(spread)
                if covers:
                    p += ph * pa
        if spread <= -1.0:  p = min(p, MAX_PROB_MINUS_15)
        elif spread >= 1.0: p = min(p, MAX_PROB_PLUS_15)
        return round(min(max(p, 0.05), 0.95), 4)

    def _total_prob(self, expected, line, direction):
        p_over = sum(self._pmf(expected, k) for k in range(int(line) + 1, 20))
        prob   = p_over if direction == "over" else 1 - p_over
        return round(min(max(prob, 0.05), 0.95), 4)

    def _shots_prob(self, avg, std, line, direction):
        p_over = sum(self._pmf(avg, k) for k in range(int(line) + 1, 15))
        prob   = p_over if direction == "over" else 1 - p_over
        return round(min(max(prob, 0.05), 0.95), 4)

    def _goals_prob(self, avg, line, direction):
        p_over = sum(self._pmf(avg, k) for k in range(int(line) + 1, 10))
        prob   = p_over if direction == "over" else 1 - p_over
        return round(min(max(prob, 0.05), 0.95), 4)

    def _saves_prob(self, expected, std, line, direction):
        if std <= 0: std = 4.5
        z = (line - expected) / std
        p_under = self._normal_cdf(z)
        prob    = (1 - p_under) if direction == "over" else p_under
        return round(min(max(prob, 0.05), 0.95), 4)

    # ── Edge & Kelly ──────────────────────────────────────────────────────────

    def _edge(self, our_prob, b365_prob, b365_odds,
              max_edge: float = 50.0) -> Optional[dict]:
        if not (MIN_ODDS <= b365_odds <= MAX_ODDS) or b365_prob <= 0:
            return None

        raw_edge = (our_prob - b365_prob) / b365_prob * 100
        edge_pct = round(min(raw_edge, max_edge), 2)

        if edge_pct < MIN_EDGE_PCT:
            return None

        b = b365_odds - 1
        if b <= 0:
            return None

        if b365_odds < 1.5:
            vig_adj = 1.0
        elif b365_odds < 2.0:
            vig_adj = 0.98
        else:
            vig_adj = 0.96

        kelly_full = ((b * our_prob) - (1 - our_prob)) / b * vig_adj
        kelly      = round(max(kelly_full / KELLY_DIVISOR * 100, 0), 2)
        kelly      = min(kelly, 15.0)

        verdict = (
            "🔥 Forte valeur"      if edge_pct >= 8 else
            "✅ Bonne valeur"      if edge_pct >= 5 else
            "👍 Valeur acceptable"
        )

        return {
            "edge_pct":       edge_pct,
            "edge_raw":       round(raw_edge, 2),
            "kelly_fraction": kelly,
            "verdict":        verdict,
        }

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _find_player_team(self, name, home, away):
        if name.lower() in self.lineup.get_active_players(home):
            return home
        return away

    @staticmethod
    def _pmf(lam, k):
        if lam <= 0:
            return 1.0 if k == 0 else 0.0
        return math.exp(-lam) * (lam ** k) / math.factorial(k)

    @staticmethod
    def _normal_cdf(z):
        if z < -6: return 0.0
        if z >  6: return 1.0
        t = 1 / (1 + 0.2316419 * abs(z))
        d = 0.3989423 * math.exp(-z * z / 2)
        p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.7814779 + t * (-1.8212560 + t * 1.3302744))))
        return 1 - p if z > 0 else p
