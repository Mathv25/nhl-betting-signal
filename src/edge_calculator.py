"""
Edge Calculator — Modele NHL calibre
- Moneyline / Puck Line / Totals
- Shrinkage bayesien vers la moyenne ligue
- Plafonds realistes puck line
- Vig bet365 (-110)
"""

import math
from typing import Optional
from nhl_stats import TeamStats, PlayerStats, LineupValidator

MIN_EDGE_PCT  = 3.0
MIN_ODDS      = 1.25
MAX_ODDS      = 10.0
LEAGUE_AVG_GF = 3.10
HOME_FACTOR   = 1.045
AWAY_FACTOR   = 0.955
B2B_FACTOR    = 0.93
KELLY_DIVISOR = 4

# Plafonds realistes puck line -1.5 / +1.5
MAX_PROB_MINUS_15 = 0.40
MAX_PROB_PLUS_15  = 0.82

# Shrinkage bayesien — tire les lambdas vers la moyenne ligue
# Plus la valeur est haute, plus on se fie a la moyenne ligue
SHRINKAGE = 0.25


class EdgeCalculator:

    def __init__(self):
        self.team_stats   = TeamStats()
        self.player_stats = PlayerStats()
        self.lineup       = LineupValidator()

    def calculate_all_edges(self, game: dict) -> list:
        edges  = []
        home   = game["home_team"]
        away   = game["away_team"]
        mkts   = game.get("markets", {})
        label  = f"{away} @ {home}"
        date   = game.get("commence_time", "")[:10]

        home_stats = self.team_stats.get(home)
        away_stats = self.team_stats.get(away)

        home_b2b = self.lineup.is_back_to_back(home, date)
        away_b2b = self.lineup.is_back_to_back(away, date)

        home_goalie = self.lineup.get_probable_starter(home)
        away_goalie = self.lineup.get_probable_starter(away)

        lh, la = self._lambdas(home_stats, away_stats, home_b2b, away_b2b)

        if "moneyline" in mkts:
            edges += self._moneyline_edges(mkts["moneyline"], lh, la, label, home, away)
        if "puck_line" in mkts:
            edges += self._puck_line_edges(mkts["puck_line"], lh, la, label)
        if "totals" in mkts:
            edges += self._total_edges(mkts["totals"], lh, la, label)
        if "first_period_ml" in mkts:
            edges += self._first_period_ml(mkts["first_period_ml"], lh, la, label)
        if "first_period_totals" in mkts:
            edges += self._first_period_totals(mkts["first_period_totals"], lh, la, label)

        props = mkts.get("player_props", [])
        edges += self._player_prop_edges(props, home, away, home_goalie, away_goalie, label)

        return [e for e in edges if e.get("edge_pct", 0) >= MIN_EDGE_PCT]

    def _lambdas(self, hs, as_, home_b2b, away_b2b):
        """
        Calcul des lambdas Poisson avec shrinkage bayesien.
        Tire les estimates vers la moyenne ligue pour eviter les extremes.
        """
        # Lambda brut
        lh_raw = (hs["gf_pg"] * HOME_FACTOR * as_["ga_pg"]) / LEAGUE_AVG_GF
        la_raw = (as_["gf_pg"] * AWAY_FACTOR * hs["ga_pg"]) / LEAGUE_AVG_GF

        # Shrinkage vers la moyenne ligue (LEAGUE_AVG_GF)
        lh = lh_raw * (1 - SHRINKAGE) + LEAGUE_AVG_GF * SHRINKAGE
        la = la_raw * (1 - SHRINKAGE) + LEAGUE_AVG_GF * SHRINKAGE

        # Ajustement PP/PK
        lh *= self._pp_factor(hs["pp_pct"], as_["pk_pct"])
        la *= self._pp_factor(as_["pp_pct"], hs["pk_pct"])

        # Ajustement gardien
        league_sv = 0.910
        lh *= (league_sv / max(as_["starter_sv_pct"], 0.880))
        la *= (league_sv / max(hs["starter_sv_pct"], 0.880))

        # Back-to-back
        if home_b2b: lh *= B2B_FACTOR
        if away_b2b: la *= B2B_FACTOR

        # Plafonds realistes
        lh = round(min(max(lh, 0.8), 5.0), 4)
        la = round(min(max(la, 0.8), 5.0), 4)

        return lh, la

    @staticmethod
    def _pp_factor(pp_pct, pk_pct):
        league_pp = 20.0
        league_pk = 80.0
        off_edge = (pp_pct - league_pp) / league_pp
        def_edge = (pk_pct - league_pk) / league_pk
        # Limite l'impact du PP a +/-5%
        return 1.0 + min(max((off_edge - def_edge) * 0.12, -0.05), 0.05)

    def _moneyline_edges(self, market, lh, la, label, home, away):
        edges = []
        hp = self._win_prob(lh, la)
        ap = 1 - hp
        for side, prob in [("home", hp), ("away", ap)]:
            m = market.get(side)
            if not m: continue
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"])
            if e:
                edges.append({**e,
                    "type":         "Moneyline",
                    "bet":          f"{m['team']} ML",
                    "our_prob":     round(prob * 100, 1),
                    "b365_implied": m["implied_prob"],
                    "b365_odds":    m["odds_decimal"],
                    "game":         label,
                    "note":         f"vs {away if side == 'home' else home}",
                })
        return edges

    def _puck_line_edges(self, market, lh, la, label):
        edges = []
        for side in ["home", "away"]:
            m = market.get(side)
            if not m: continue
            spread = m.get("spread", -1.5 if side == "home" else 1.5)
            prob   = self._spread_prob(lh, la, spread, side)
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"])
            if e:
                sign = "+" if spread > 0 else ""
                edges.append({**e,
                    "type":         "Puck Line",
                    "bet":          f"{m['team']} {sign}{spread}",
                    "our_prob":     round(prob * 100, 1),
                    "b365_implied": m["implied_prob"],
                    "b365_odds":    m["odds_decimal"],
                    "game":         label,
                    "note":         f"Spread {sign}{spread} buts",
                })
        return edges

    def _total_edges(self, market, lh, la, label):
        edges = []
        expected = lh + la
        for direction in ["over", "under"]:
            m = market.get(direction)
            if not m or not m.get("line"): continue
            line = m["line"]
            prob = self._total_prob(expected, line, direction)
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"])
            if e:
                edges.append({**e,
                    "type":         "Total buts",
                    "bet":          f"{direction.capitalize()} {line}",
                    "our_prob":     round(prob * 100, 1),
                    "b365_implied": m["implied_prob"],
                    "b365_odds":    m["odds_decimal"],
                    "game":         label,
                    "note":         f"Total attendu: {round(expected, 1)} buts",
                })
        return edges

    def _first_period_ml(self, market, lh, la, label):
        edges = []
        lh1, la1 = lh * 0.33, la * 0.33
        hp = self._win_prob(lh1, la1)
        for side, prob in [("home", hp), ("away", 1 - hp)]:
            m = market.get(side)
            if not m: continue
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"])
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
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"])
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

    # ── Distributions ──────────────────────────────────────────────────────

    def _win_prob(self, lh, la):
        p_home = p_tie = 0.0
        for h in range(12):
            ph = self._pmf(lh, h)
            for a in range(12):
                pa = self._pmf(la, a)
                p  = ph * pa
                if h > a:   p_home += p
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

        if spread <= -1.0:   p = min(p, MAX_PROB_MINUS_15)
        elif spread >= 1.0:  p = min(p, MAX_PROB_PLUS_15)

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

    # ── Edge & Kelly ───────────────────────────────────────────────────────

    def _edge(self, our_prob, b365_prob, b365_odds):
        if not (MIN_ODDS <= b365_odds <= MAX_ODDS) or b365_prob <= 0:
            return None
        edge_pct = round((our_prob - b365_prob) / b365_prob * 100, 2)
        if edge_pct < MIN_EDGE_PCT:
            return None
        b = b365_odds - 1
        if b <= 0:
            return None
        kelly_full = ((b * our_prob) - (1 - our_prob)) / b
        kelly = round(max(kelly_full / KELLY_DIVISOR * 100, 0), 2)
        # Plafonne Kelly a 15% BR max
        kelly = min(kelly, 15.0)
        verdict = (
            "🔥 Forte valeur"      if edge_pct >= 8 else
            "✅ Bonne valeur"      if edge_pct >= 5 else
            "👍 Valeur acceptable"
        )
        return {"edge_pct": edge_pct, "kelly_fraction": kelly, "verdict": verdict}

    # ── Helpers ────────────────────────────────────────────────────────────

    def _find_player_team(self, name, home, away):
        if name.lower() in self.lineup.get_active_players(home):
            return home
        return away

    @staticmethod
    def _matchup_note(team, opp):
        return f"vs {opp}"

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
