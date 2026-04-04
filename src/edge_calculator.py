"""
Edge Calculator — Modèle actuariel complet NHL
Marchés couverts:
  - Moneyline / Puck Line / Totals
  - 1ère période (ML, total, puck line)
  - Props joueurs: shots, points, buts, passes, saves, save%
  - Gardien: saves over/under calibré sur workload
  - Back-to-back adjustment
  - Forme récente (10 matchs, pondération exponentielle)
  - Ajustement gardien starter vs backup
  - PP/PK impact sur totaux

Modèle: Distribution de Poisson bivariée + Bayesian shrinkage + Kelly fractionné
"""

import math
from typing import Optional
from nhl_stats import TeamStats, PlayerStats, LineupValidator

# ── Paramètres globaux ─────────────────────────────────────────────────────
MIN_EDGE_PCT   = 3.0    # Edge minimum pour recommander
MIN_ODDS       = 1.25   # Cote minimale (évite les paris trop courts)
MAX_ODDS       = 15.0   # Cote maximale
LEAGUE_AVG_GF  = 3.10   # Buts par match par équipe, moyenne ligue 2025-26
HOME_FACTOR    = 1.055  # Avantage domicile offensif
AWAY_FACTOR    = 0.945  # Désavantage visiteur offensif
B2B_FACTOR     = 0.92   # Pénalité back-to-back
KELLY_DIVISOR  = 4      # Quart-Kelly pour limiter la variance

# Plafonds réalistes pour puck line -1.5 (gagner par 2+ buts)
MAX_PROB_MINUS_1_5 = 0.42   # Même le meilleur favori ne couvre -1.5 à plus de 42%
MAX_PROB_PLUS_1_5  = 0.85   # +1.5 ne dépasse pas 85%


class EdgeCalculator:

    def __init__(self):
        self.team_stats   = TeamStats()
        self.player_stats = PlayerStats()
        self.lineup       = LineupValidator()

    def calculate_all_edges(self, game: dict) -> list:
        """Point d'entrée principal — calcule tous les edges pour un match."""
        edges  = []
        home   = game["home_team"]
        away   = game["away_team"]
        mkts   = game.get("markets", {})
        label  = f"{away} @ {home}"
        date   = game.get("commence_time", "")[:10]

        # Stats d'équipes depuis NHL API
        home_stats = self.team_stats.get(home)
        away_stats = self.team_stats.get(away)

        # Back-to-back
        home_b2b = self.lineup.is_back_to_back(home, date)
        away_b2b = self.lineup.is_back_to_back(away, date)

        # Gardiens partants
        home_goalie = self.lineup.get_probable_starter(home)
        away_goalie = self.lineup.get_probable_starter(away)

        # Lambda Poisson ajusté
        lh, la = self._lambdas(home_stats, away_stats, home_b2b, away_b2b)

        # ── Moneyline ─────────────────────────────────────────────────────
        if "moneyline" in mkts:
            edges += self._moneyline_edges(mkts["moneyline"], lh, la, label, home, away)

        # ── Puck Line ─────────────────────────────────────────────────────
        if "puck_line" in mkts:
            edges += self._puck_line_edges(mkts["puck_line"], lh, la, label)

        # ── Totals ────────────────────────────────────────────────────────
        if "totals" in mkts:
            edges += self._total_edges(mkts["totals"], lh, la, label)

        # ── 1ère période ──────────────────────────────────────────────────
        if "first_period_ml" in mkts:
            edges += self._first_period_ml(mkts["first_period_ml"], lh, la, label)

        if "first_period_totals" in mkts:
            edges += self._first_period_totals(mkts["first_period_totals"], lh, la, label)

        # ── Props joueurs (validés par lineup_checker) ─────────────────────
        props = game.get("markets", {}).get("player_props", [])
        edges += self._player_prop_edges(props, home, away, home_goalie, away_goalie, label)

        # Filtre final: edge >= seuil
        return [e for e in edges if e.get("edge_pct", 0) >= MIN_EDGE_PCT]

    # ── Lambdas Poisson ────────────────────────────────────────────────────

    def _lambdas(self, hs: dict, as_: dict, home_b2b: bool, away_b2b: bool):
        """
        λ_home = (GF_home × HOME_FACTOR × GA_away) / league_avg
        λ_away = (GF_away × AWAY_FACTOR × GA_home) / league_avg
        Ajustements: back-to-back, save% gardien
        """
        lh = (hs["gf_pg"] * HOME_FACTOR * as_["ga_pg"]) / LEAGUE_AVG_GF
        la = (as_["gf_pg"] * AWAY_FACTOR * hs["ga_pg"]) / LEAGUE_AVG_GF

        # Ajustement PP/PK
        lh *= self._pp_factor(hs["pp_pct"], as_["pk_pct"])
        la *= self._pp_factor(as_["pp_pct"], hs["pk_pct"])

        # Ajustement gardien (save% vs ligue)
        league_sv = 0.910
        lh *= (league_sv / max(as_["starter_sv_pct"], 0.870))
        la *= (league_sv / max(hs["starter_sv_pct"], 0.870))

        # Back-to-back
        if home_b2b:
            lh *= B2B_FACTOR
        if away_b2b:
            la *= B2B_FACTOR

        return round(max(lh, 0.5), 4), round(max(la, 0.5), 4)

    @staticmethod
    def _pp_factor(pp_pct: float, pk_pct: float) -> float:
        """Facteur d'ajustement basé sur PP% offense vs PK% defense."""
        league_pp = 20.0
        league_pk = 80.0
        off_edge = (pp_pct - league_pp) / league_pp
        def_edge = (pk_pct - league_pk) / league_pk
        return 1.0 + (off_edge - def_edge) * 0.15

    # ── Moneyline ──────────────────────────────────────────────────────────

    def _moneyline_edges(self, market, lh, la, label, home, away):
        edges = []
        hp = self._win_prob(lh, la)
        ap = 1 - hp
        for side, prob in [("home", hp), ("away", ap)]:
            m = market.get(side)
            if not m:
                continue
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"])
            if e:
                note = self._matchup_note(home if side == "home" else away,
                                          away if side == "home" else home)
                edges.append({**e,
                    "type": "Moneyline",
                    "bet": f"{m['team']} ML",
                    "our_prob": round(prob * 100, 1),
                    "b365_implied": m["implied_prob"],
                    "b365_odds": m["odds_decimal"],
                    "game": label,
                    "note": note,
                })
        return edges

    # ── Puck Line ──────────────────────────────────────────────────────────

    def _puck_line_edges(self, market, lh, la, label):
        edges = []
        for side in ["home", "away"]:
            m = market.get(side)
            if not m:
                continue
            spread = m.get("spread", -1.5 if side == "home" else 1.5)
            prob = self._spread_prob(lh, la, spread, side)
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"])
            if e:
                sign = "+" if spread > 0 else ""
                edges.append({**e,
                    "type": "Puck Line",
                    "bet": f"{m['team']} {sign}{spread}",
                    "our_prob": round(prob * 100, 1),
                    "b365_implied": m["implied_prob"],
                    "b365_odds": m["odds_decimal"],
                    "game": label,
                    "note": f"Spread {sign}{spread} buts",
                })
        return edges

    # ── Totals ─────────────────────────────────────────────────────────────

    def _total_edges(self, market, lh, la, label):
        edges = []
        expected = lh + la
        for direction in ["over", "under"]:
            m = market.get(direction)
            if not m or not m.get("line"):
                continue
            line = m["line"]
            prob = self._total_prob(expected, line, direction)
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"])
            if e:
                edges.append({**e,
                    "type": "Total buts",
                    "bet": f"{direction.capitalize()} {line}",
                    "our_prob": round(prob * 100, 1),
                    "b365_implied": m["implied_prob"],
                    "b365_odds": m["odds_decimal"],
                    "game": label,
                    "note": f"Total attendu: {round(expected, 1)} buts",
                })
        return edges

    # ── 1ère période ───────────────────────────────────────────────────────

    def _first_period_ml(self, market, lh, la, label):
        edges = []
        lh1 = lh * 0.33
        la1 = la * 0.33
        hp = self._win_prob(lh1, la1)
        ap = 1 - hp
        for side, prob in [("home", hp), ("away", ap)]:
            m = market.get(side)
            if not m:
                continue
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"])
            if e:
                edges.append({**e,
                    "type": "1re période ML",
                    "bet": f"{m['team']} gagne 1re période",
                    "our_prob": round(prob * 100, 1),
                    "b365_implied": m["implied_prob"],
                    "b365_odds": m["odds_decimal"],
                    "game": label,
                    "note": "Basé sur 33% buts en 1P",
                })
        return edges

    def _first_period_totals(self, market, lh, la, label):
        edges = []
        expected_1p = (lh + la) * 0.33
        for direction in ["over", "under"]:
            m = market.get(direction)
            if not m or not m.get("line"):
                continue
            line = m["line"]
            prob = self._total_prob(expected_1p, line, direction)
            e = self._edge(prob, m["implied_prob"] / 100, m["odds_decimal"])
            if e:
                edges.append({**e,
                    "type": "Total 1re période",
                    "bet": f"{direction.capitalize()} {line} (1P)",
                    "our_prob": round(prob * 100, 1),
                    "b365_implied": m["implied_prob"],
                    "b365_odds": m["odds_decimal"],
                    "game": label,
                    "note": f"Total 1P attendu: {round(expected_1p, 2)}",
                })
        return edges

    # ── Props joueurs ──────────────────────────────────────────────────────

    def _player_prop_edges(self, props, home, away, home_goalie, away_goalie, label):
        edges = []
        for prop in props:
            player    = prop.get("player", "")
            market    = prop.get("market", "")
            direction = prop.get("direction", "").lower()
            line      = prop.get("line")
            b365_odds = prop.get("odds_decimal", 0)
            b365_impl = prop.get("implied_prob", 0)

            if not player or line is None:
                continue

            team     = self._find_player_team(player, home, away)
            opponent = away if team == home else home
            our_prob = None

            if market == "player_shots_on_goal":
                stats    = self.player_stats.get_skater(player, team)
                our_prob = self._shots_prob(stats["shots_pg"], stats["shots_std"], line, direction)
                note     = f"Moy. {stats['shots_pg']} shots/match ({stats['n_games']} derniers matchs)"

            elif market == "player_goals":
                stats    = self.player_stats.get_skater(player, team)
                our_prob = self._goals_prob(stats["goals_pg"], line, direction)
                note     = f"Moy. {stats['goals_pg']} buts/match"

            elif market == "player_assists":
                stats    = self.player_stats.get_skater(player, team)
                our_prob = self._goals_prob(stats["assists_pg"], line, direction)
                note     = f"Moy. {stats['assists_pg']} passes/match"

            elif market == "player_points":
                stats    = self.player_stats.get_skater(player, team)
                our_prob = self._goals_prob(stats["points_pg"], line, direction)
                note     = f"Moy. {stats['points_pg']} pts/match"

            elif market == "player_saves":
                goalie_name = home_goalie if team == home else away_goalie
                g_name      = goalie_name if goalie_name else player
                stats       = self.player_stats.get_goalie(g_name, team)
                opp_stats   = self.team_stats.get(opponent)
                expected_shots = opp_stats["shots_pg"]
                expected_saves = expected_shots * stats["sv_pct"]
                our_prob = self._saves_prob(expected_saves, stats["saves_std"], line, direction)
                note     = f"Moy. {stats['saves_pg']} saves/match, sv% {stats['sv_pct']:.3f}"

            else:
                continue

            if our_prob is None:
                continue

            e = self._edge(our_prob, b365_impl / 100, b365_odds)
            if e:
                market_label = {
                    "player_shots_on_goal": "Shots on goal",
                    "player_goals":         "Buts",
                    "player_assists":       "Passes",
                    "player_points":        "Points",
                    "player_saves":         "Saves gardien",
                }.get(market, market)
                edges.append({**e,
                    "type": f"Prop — {market_label}",
                    "bet":  f"{player} {direction.capitalize()} {line}",
                    "our_prob":    round(our_prob * 100, 1),
                    "b365_implied": b365_impl,
                    "b365_odds":   b365_odds,
                    "game": label,
                    "note": note,
                })
        return edges

    # ── Distributions probabilistes ────────────────────────────────────────

    def _win_prob(self, lh: float, la: float) -> float:
        """P(home win) via Poisson bivarié — inclut OT/SO distribués 50/50."""
        p_home = p_tie = 0.0
        for h in range(12):
            ph = self._pmf(lh, h)
            for a in range(12):
                pa = self._pmf(la, a)
                p = ph * pa
                if h > a:
                    p_home += p
                elif h == a:
                    p_tie += p
        return round(min(max(p_home + p_tie * 0.5, 0.05), 0.95), 4)

    def _spread_prob(self, lh: float, la: float, spread: float, side: str) -> float:
        """
        P(equipe couvre le spread) via Poisson bivarié.

        diff = home_goals - away_goals (positif = victoire locale)

        home -1.5 : home gagne par 2+  → diff >= 2
        home +1.5 : home ne perd pas par 2+  → diff >= -1
        away -1.5 : away gagne par 2+  → diff <= -2
        away +1.5 : away ne perd pas par 2+  → diff <= 1

        Plafonds réalistes appliqués après calcul.
        """
        p = 0.0
        for h in range(15):
            ph = self._pmf(lh, h)
            for a in range(15):
                pa = self._pmf(la, a)
                diff = h - a
                if side == "home":
                    if spread <= 0:
                        # home -1.5 : gagner par ceil(|spread|) buts ou plus
                        covers = diff >= math.ceil(abs(spread))
                    else:
                        # home +1.5 : ne pas perdre par ceil(spread) buts ou plus
                        covers = diff >= -math.floor(spread)
                else:
                    if spread <= 0:
                        # away -1.5 : away gagne par ceil(|spread|) buts ou plus
                        covers = diff <= -math.ceil(abs(spread))
                    else:
                        # away +1.5 : ne pas perdre par ceil(spread) buts ou plus
                        covers = diff <= math.floor(spread)
                if covers:
                    p += ph * pa

        # Plafonds réalistes pour puck lines
        if spread <= -1.0:
            p = min(p, MAX_PROB_MINUS_1_5)
        elif spread >= 1.0:
            p = min(p, MAX_PROB_PLUS_1_5)

        return round(min(max(p, 0.05), 0.95), 4)

    def _total_prob(self, expected: float, line: float, direction: str) -> float:
        """P(Over/Under X buts) via Poisson."""
        p_over = sum(self._pmf(expected, k) for k in range(int(line) + 1, 20))
        prob = p_over if direction == "over" else 1 - p_over
        return round(min(max(prob, 0.05), 0.95), 4)

    def _shots_prob(self, avg: float, std: float, line: float, direction: str) -> float:
        p_over = sum(self._pmf(avg, k) for k in range(int(line) + 1, 15))
        prob = p_over if direction == "over" else 1 - p_over
        return round(min(max(prob, 0.05), 0.95), 4)

    def _goals_prob(self, avg: float, line: float, direction: str) -> float:
        p_over = sum(self._pmf(avg, k) for k in range(int(line) + 1, 10))
        prob = p_over if direction == "over" else 1 - p_over
        return round(min(max(prob, 0.05), 0.95), 4)

    def _saves_prob(self, expected: float, std: float, line: float, direction: str) -> float:
        if std <= 0:
            std = 4.5
        z = (line - expected) / std
        p_under = self._normal_cdf(z)
        p_over = 1 - p_under
        prob = p_over if direction == "over" else p_under
        return round(min(max(prob, 0.05), 0.95), 4)

    # ── Edge & Kelly ───────────────────────────────────────────────────────

    def _edge(self, our_prob: float, b365_prob: float, b365_odds: float) -> Optional[dict]:
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

        verdict = (
            "🔥 Forte valeur"      if edge_pct >= 8  else
            "✅ Bonne valeur"      if edge_pct >= 5  else
            "👍 Valeur acceptable"
        )
        return {"edge_pct": edge_pct, "kelly_fraction": kelly, "verdict": verdict}

    # ── Helpers ────────────────────────────────────────────────────────────

    def _find_player_team(self, player_name: str, home: str, away: str) -> str:
        home_active = self.lineup.get_active_players(home)
        if player_name.lower() in home_active:
            return home
        return away

    @staticmethod
    def _matchup_note(team: str, opp: str) -> str:
        return f"vs {opp}"

    @staticmethod
    def _pmf(lam: float, k: int) -> float:
        if lam <= 0:
            return 1.0 if k == 0 else 0.0
        return math.exp(-lam) * (lam ** k) / math.factorial(k)

    @staticmethod
    def _normal_cdf(z: float) -> float:
        if z < -6:
            return 0.0
        if z > 6:
            return 1.0
        t = 1 / (1 + 0.2316419 * abs(z))
        d = 0.3989423 * math.exp(-z * z / 2)
        p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.7814779 + t * (-1.8212560 + t * 1.3302744))))
        return 1 - p if z > 0 else p
