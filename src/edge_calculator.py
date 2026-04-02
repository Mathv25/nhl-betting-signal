"""
Calcule les edges entre les probabilités du modèle et les cotes bet365.
Formule: Edge% = (prob_modèle - prob_implicite_b365) / prob_implicite_b365 * 100

Seuil minimum: 3% d'edge pour recommander un bet.
"""

from typing import Optional
import math


MIN_EDGE_PCT = 3.0       # Edge minimum pour recommander
MIN_ODDS = 1.30          # Cote minimale (évite les paris trop courts)
MAX_ODDS = 10.0          # Cote maximale (trop risqué)


class EdgeCalculator:

    def calculate_all_edges(self, game: dict) -> list:
        """Calcule tous les edges pour un match donné."""
        edges = []
        home = game["home_team"]
        away = game["away_team"]
        markets = game.get("markets", {})

        # --- Moneyline ---
        if "moneyline" in markets:
            ml = markets["moneyline"]
            home_prob = self._poisson_win_prob(home, away, home_advantage=True)
            away_prob = 1 - home_prob

            for side, prob in [("home", home_prob), ("away", away_prob)]:
                if side in ml:
                    edge = self._compute_edge(prob, ml[side]["implied_prob"] / 100)
                    if edge and edge["edge_pct"] >= MIN_EDGE_PCT:
                        edges.append({
                            "type": "Moneyline",
                            "bet": f"{ml[side]['team']} ML",
                            "our_prob": round(prob * 100, 1),
                            "b365_implied": ml[side]["implied_prob"],
                            "b365_odds": ml[side]["odds_decimal"],
                            "edge_pct": edge["edge_pct"],
                            "kelly_fraction": edge["kelly"],
                            "verdict": self._verdict(edge["edge_pct"]),
                            "game": f"{away} @ {home}"
                        })

        # --- Puck Line ---
        if "puck_line" in markets:
            pl = markets["puck_line"]
            for side in ["home", "away"]:
                if side in pl:
                    spread = pl[side]["spread"]
                    prob = self._puck_line_prob(home, away, spread, side)
                    edge = self._compute_edge(prob, pl[side]["implied_prob"] / 100)
                    if edge and edge["edge_pct"] >= MIN_EDGE_PCT:
                        sign = "+" if spread > 0 else ""
                        edges.append({
                            "type": "Puck Line",
                            "bet": f"{pl[side]['team']} {sign}{spread}",
                            "our_prob": round(prob * 100, 1),
                            "b365_implied": pl[side]["implied_prob"],
                            "b365_odds": pl[side]["odds_decimal"],
                            "edge_pct": edge["edge_pct"],
                            "kelly_fraction": edge["kelly"],
                            "verdict": self._verdict(edge["edge_pct"]),
                            "game": f"{away} @ {home}"
                        })

        # --- Totals ---
        if "totals" in markets:
            totals = markets["totals"]
            avg_total = self._expected_total(home, away)
            for direction in ["over", "under"]:
                if direction in totals:
                    line = totals[direction]["line"]
                    prob = self._total_prob(avg_total, line, direction)
                    edge = self._compute_edge(prob, totals[direction]["implied_prob"] / 100)
                    if edge and edge["edge_pct"] >= MIN_EDGE_PCT:
                        edges.append({
                            "type": "Total buts",
                            "bet": f"{direction.capitalize()} {line}",
                            "our_prob": round(prob * 100, 1),
                            "b365_implied": totals[direction]["implied_prob"],
                            "b365_odds": totals[direction]["odds_decimal"],
                            "edge_pct": edge["edge_pct"],
                            "kelly_fraction": edge["kelly"],
                            "verdict": self._verdict(edge["edge_pct"]),
                            "game": f"{away} @ {home}"
                        })

        # --- Props joueurs ---
        for prop in game.get("markets", {}).get("player_props", []):
            edge = self._compute_prop_edge(prop)
            if edge and edge["edge_pct"] >= MIN_EDGE_PCT:
                market_label = self._market_label(prop["market"])
                edges.append({
                    "type": f"Prop — {market_label}",
                    "bet": f"{prop['player']} {prop['direction']} {prop['line']}",
                    "our_prob": edge["our_prob"],
                    "b365_implied": prop["implied_prob"],
                    "b365_odds": prop["odds_decimal"],
                    "edge_pct": edge["edge_pct"],
                    "kelly_fraction": edge["kelly"],
                    "verdict": self._verdict(edge["edge_pct"]),
                    "game": f"{away} @ {home}"
                })

        return edges

    # ------------------------------------------------------------------ #
    # Modèles probabilistes                                                #
    # ------------------------------------------------------------------ #

    def _poisson_win_prob(self, home: str, away: str, home_advantage: bool = True) -> float:
        """
        Probabilité de victoire via distribution de Poisson.
        Utilise les moyennes de buts de la saison ajustées H/A.
        """
        home_avg = self._team_goals_for(home) * (1.06 if home_advantage else 1.0)
        away_avg = self._team_goals_for(away) * (0.94 if home_advantage else 1.0)

        home_def = self._team_goals_against(home)
        away_def = self._team_goals_against(away)

        # Lambda attendu = offense équipe × défense adverse / moyenne ligue
        league_avg = 3.1
        lambda_home = (home_avg * away_def) / league_avg
        lambda_away = (away_avg * home_def) / league_avg

        # Probabilité via somme Poisson (max 10 buts par équipe)
        p_home_win = 0.0
        p_tie = 0.0
        for h in range(11):
            for a in range(11):
                p = self._poisson_pmf(lambda_home, h) * self._poisson_pmf(lambda_away, a)
                if h > a:
                    p_home_win += p
                elif h == a:
                    p_tie += p

        # En hockey, les matchs nuls vont en OT/SO — distribue 50/50
        p_home_win += p_tie * 0.50
        return round(min(max(p_home_win, 0.05), 0.95), 4)

    def _puck_line_prob(self, home: str, away: str, spread: float, side: str) -> float:
        """Probabilité de couvrir le spread de ±1.5."""
        base_prob = self._poisson_win_prob(home, away)
        if side == "home":
            # Couvrir −1.5: gagner par 2+
            return round(base_prob * 0.62, 4)  # Ajustement empirique NHL
        else:
            # Couvrir +1.5: perdre par 1 ou gagner
            return round((1 - base_prob) + base_prob * 0.38, 4)

    def _expected_total(self, home: str, away: str) -> float:
        """Total de buts attendu pour le match."""
        home_off = self._team_goals_for(home)
        away_off = self._team_goals_for(away)
        home_def = self._team_goals_against(home)
        away_def = self._team_goals_against(away)
        league_avg = 3.1
        expected_home = (home_off * away_def) / league_avg
        expected_away = (away_off * home_def) / league_avg
        return round(expected_home + expected_away, 2)

    def _total_prob(self, expected: float, line: float, direction: str) -> float:
        """Probabilité Over/Under via distribution de Poisson."""
        prob_over = 0.0
        for total in range(int(line) + 1, 20):
            prob_over += self._poisson_pmf(expected, total)
        if direction == "over":
            return round(min(max(prob_over, 0.05), 0.95), 4)
        else:
            return round(min(max(1 - prob_over, 0.05), 0.95), 4)

    def _compute_prop_edge(self, prop: dict) -> Optional[dict]:
        """
        Pour les props, utilise un ajustement conservateur de ±5%
        sur la probabilité implicite du bookmaker comme proxy modèle.
        À terme: remplacer par stats joueur réelles via NHL API.
        """
        implied = prop["implied_prob"] / 100
        # Conservateur: notre estimation légèrement différente de b365
        # (remplacer par stats réelles dans une V2)
        our_prob = implied  # Placeholder — sans données joueur = pas d'edge
        edge = self._compute_edge(our_prob, implied)
        if edge:
            edge["our_prob"] = round(our_prob * 100, 1)
        return edge

    # ------------------------------------------------------------------ #
    # Calcul d'edge et Kelly                                               #
    # ------------------------------------------------------------------ #

    def _compute_edge(self, our_prob: float, b365_prob: float) -> Optional[dict]:
        """
        Edge = notre prob - prob implicite b365
        Kelly = (b × p − q) / b  où b = cote − 1, p = notre prob, q = 1−p
        """
        if b365_prob <= 0 or our_prob <= 0:
            return None

        b365_odds = 1 / b365_prob
        if not (MIN_ODDS <= b365_odds <= MAX_ODDS):
            return None

        edge_pct = round((our_prob - b365_prob) / b365_prob * 100, 2)

        b = b365_odds - 1
        kelly = round(((b * our_prob) - (1 - our_prob)) / b * 100, 2) if b > 0 else 0
        kelly = max(kelly, 0)
        # Demi-Kelly pour réduire la variance
        half_kelly = round(kelly / 2, 2)

        return {
            "edge_pct": edge_pct,
            "kelly": half_kelly  # % du bankroll recommandé
        }

    # ------------------------------------------------------------------ #
    # Stats d'équipes (moyennes de saison 2025-26)                        #
    # À terme: remplacer par fetch live NHL Stats API                     #
    # ------------------------------------------------------------------ #

    def _team_goals_for(self, team: str) -> float:
        gf = {
            "Colorado Avalanche": 3.85, "Edmonton Oilers": 3.70,
            "Toronto Maple Leafs": 3.45, "Tampa Bay Lightning": 3.30,
            "Florida Panthers": 3.20, "Boston Bruins": 3.40,
            "Washington Capitals": 3.25, "Carolina Hurricanes": 3.10,
            "Winnipeg Jets": 3.15, "Dallas Stars": 3.05,
            "Vegas Golden Knights": 3.10, "New York Rangers": 3.20,
            "Minnesota Wild": 3.00, "Pittsburgh Penguins": 3.30,
            "Montreal Canadiens": 3.10, "New Jersey Devils": 3.00,
            "Ottawa Senators": 2.95, "Buffalo Sabres": 3.05,
            "Philadelphia Flyers": 2.90, "Detroit Red Wings": 2.85,
            "New York Islanders": 2.75, "Los Angeles Kings": 2.95,
            "Vancouver Canucks": 3.00, "St. Louis Blues": 2.90,
            "Calgary Flames": 2.85, "Seattle Kraken": 2.80,
            "Nashville Predators": 2.75, "Columbus Blue Jackets": 2.70,
            "Anaheim Ducks": 2.65, "San Jose Sharks": 2.60,
            "Chicago Blackhawks": 2.55,
        }
        return gf.get(team, 3.0)

    def _team_goals_against(self, team: str) -> float:
        ga = {
            "Carolina Hurricanes": 2.60, "Florida Panthers": 2.65,
            "Colorado Avalanche": 2.70, "Vegas Golden Knights": 2.75,
            "Boston Bruins": 2.75, "Dallas Stars": 2.80,
            "Winnipeg Jets": 2.85, "Minnesota Wild": 2.85,
            "Los Angeles Kings": 2.90, "Tampa Bay Lightning": 2.90,
            "Toronto Maple Leafs": 3.00, "Edmonton Oilers": 3.05,
            "New York Rangers": 3.00, "New York Islanders": 2.95,
            "Washington Capitals": 3.00, "Seattle Kraken": 3.05,
            "Ottawa Senators": 3.10, "New Jersey Devils": 3.10,
            "Pittsburgh Penguins": 3.05, "Montreal Canadiens": 3.15,
            "Vancouver Canucks": 3.10, "Buffalo Sabres": 3.20,
            "Philadelphia Flyers": 3.20, "Nashville Predators": 3.25,
            "Detroit Red Wings": 3.30, "Calgary Flames": 3.25,
            "St. Louis Blues": 3.30, "Columbus Blue Jackets": 3.40,
            "Chicago Blackhawks": 3.55, "Anaheim Ducks": 3.50,
            "San Jose Sharks": 3.60,
        }
        return ga.get(team, 3.1)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _poisson_pmf(lam: float, k: int) -> float:
        return (math.exp(-lam) * (lam ** k)) / math.factorial(k)

    @staticmethod
    def _verdict(edge_pct: float) -> str:
        if edge_pct >= 8:
            return "🔥 Forte valeur"
        elif edge_pct >= 5:
            return "✅ Bonne valeur"
        elif edge_pct >= 3:
            return "👍 Valeur acceptable"
        else:
            return "➖ Neutre"

    @staticmethod
    def _market_label(key: str) -> str:
        labels = {
            "player_points": "Points",
            "player_goals": "Buts",
            "player_assists": "Passes",
            "player_shots_on_goal": "Shots on goal",
            "player_saves": "Saves",
        }
        return labels.get(key, key)
