"""
Props Analyzer - Signal joueurs +EV v3
Corrections:
- VIG corrige: -115 DraftKings = 53.49% implied (etait 52.36%)
- Liste KNOWN_INJURED: joueurs blessés long terme a mettre a jour manuellement
- L'API NHL.com ne met pas toujours a jour les statuts IR correctement
"""

import requests
import time
import math
from typing import Optional

NHL_API   = "https://api-web.nhle.com/v1"
SEASON    = "20252026"
GAME_TYPE = "2"

MIN_EDGE             = 10.0   # Abaisse de 15 — 10% edge est rentable si calibration correcte
MIN_EDGE_SHOTS       = 15.0   # Abaisse de 20 — 20% etait introuvable en pratique
MAX_EDGE_DISPLAY     = 25.0
B365_VIG_IMPL        = 53.49 / 100
B365_VIG_ODDS        = 1.870
MIN_DEF_RANK_SHOTS   = 23    # Remonte de 25 — permet ~10 equipes (pas seulement 8)
MIN_DEF_RANK_GOALS   = 24

# Ratios max par marche — si notre modele est plus optimiste que DK au-dela de ce seuil, skip
# Calibres sur donnees reelles: 1.18 permet des edges reels sans aller trop loin
MAX_DISAGREEMENT_SHOTS  = 1.18  # Shots: legerement assoupli (1.15 trop strict en playoffs)
MAX_DISAGREEMENT_POINTS = 1.18  # Points: meme logique
MAX_DISAGREEMENT_GOALS  = 1.22  # Buts: volatile, plus de marge toleree
MAX_DISAGREEMENT_RATIO  = 1.20  # Fallback generique

# Total moyen par match NHL (saison reguliere 2024-25) — sert de calibrant hors playoffs
LEAGUE_AVG_GAME_TOTAL  = 6.2
# Total moyen en series — les series sont plus defensives (~11% moins de buts)
# Base pour game_env_factor en mode playoff (evite de doubler la penalite d'ajustement)
PLAYOFF_AVG_GAME_TOTAL = 5.5

GAME_TYPE_PLAYOFFS   = "3"

# ── AJUSTEMENTS LIGUE EN SERIES ────────────────────────────────────────────────
# Les series = jeu plus defensif, moins de tirs et de buts qu'en saison reguliere
# NOTE: Ces facteurs s'appliquent UNE SEULE FOIS dans _get_player_stats.
# game_env_factor dans _best_bets utilise PLAYOFF_AVG_GAME_TOTAL comme base
# pour eviter le double-comptage (la penalite playoff ne s'applique pas deux fois).
PLAYOFF_LEAGUE_SHOTS = 0.93   # ~93% des tirs: calibre sur donnees reelles (era 0.90 surestimait)
PLAYOFF_LEAGUE_GOALS = 0.91   # ~91% des buts: meme recalibration

# ── FACTEURS HISTORIQUES JOUEURS EN SERIES ────────────────────────────────────
# Ratio performance series / saison reguliere sur 3 derniers ans de playoffs
# Source: NHL Stats, Hockey Reference 2022-2025
PLAYOFF_FACTORS = {
    # Elite performers en series — surpassent leur niveau regulier
    "nathan mackinnon":  {"shots": 1.12, "goals": 1.18, "points": 1.15},
    "leon draisaitl":    {"shots": 1.05, "goals": 1.12, "points": 1.10},
    "nikita kucherov":   {"shots": 1.03, "goals": 1.10, "points": 1.22},  # 92pts en 2024
    "cale makar":        {"shots": 1.08, "goals": 1.15, "points": 1.18},
    "brad marchand":     {"shots": 1.10, "goals": 1.14, "points": 1.16},
    "david pastrnak":    {"shots": 1.08, "goals": 1.10, "points": 1.08},
    "victor hedman":     {"shots": 1.05, "goals": 1.08, "points": 1.12},
    "andrei vasilevskiy":{"shots": 1.00, "goals": 0.88, "points": 0.88},  # gardien — buts contre
    "matthew tkachuk":   {"shots": 1.05, "goals": 1.08, "points": 1.10},
    "aleksander barkov": {"shots": 1.02, "goals": 1.05, "points": 1.08},
    "sam reinhart":      {"shots": 1.05, "goals": 1.10, "points": 1.08},
    "evan rodrigues":    {"shots": 1.02, "goals": 1.00, "points": 1.02},
    "brayden point":     {"shots": 1.05, "goals": 1.15, "points": 1.18},
    "mitchell marner":   {"shots": 1.00, "goals": 0.92, "points": 0.95},  # critiques en series
    "auston matthews":   {"shots": 1.05, "goals": 0.95, "points": 0.97},  # production baisee
    "connor mcdavid":    {"shots": 1.02, "goals": 1.05, "points": 1.12},
    "mika zibanejad":    {"shots": 1.02, "goals": 1.05, "points": 1.05},
    "artemi panarin":    {"shots": 0.95, "goals": 0.90, "points": 0.92},  # struggles en series
    "jason robertson":   {"shots": 1.00, "goals": 0.95, "points": 0.97},
    "jake oettinger":    {"shots": 1.00, "goals": 0.90, "points": 0.90},
    "william nylander":  {"shots": 1.00, "goals": 0.95, "points": 0.97},
    "bo horvat":         {"shots": 1.02, "goals": 1.05, "points": 1.05},
    "sam reinhart":      {"shots": 1.05, "goals": 1.10, "points": 1.08},
    "j.t. miller":       {"shots": 1.00, "goals": 0.95, "points": 0.97},
    "mark scheifele":    {"shots": 1.05, "goals": 1.12, "points": 1.10},
    "kyle connor":       {"shots": 1.02, "goals": 1.05, "points": 1.05},
    "kirill kaprizov":   {"shots": 1.02, "goals": 1.00, "points": 1.02},
    "roman josi":        {"shots": 1.05, "goals": 1.08, "points": 1.10},
    "adam fox":          {"shots": 1.02, "goals": 1.05, "points": 1.08},
    "quinn hughes":      {"shots": 1.00, "goals": 1.00, "points": 1.05},
    "mikko rantanen":    {"shots": 1.05, "goals": 1.10, "points": 1.08},
    "charlie mcavoy":    {"shots": 1.02, "goals": 1.05, "points": 1.05},
    "jake guentzel":     {"shots": 1.05, "goals": 1.15, "points": 1.12},  # excellent en series
    "evgeni malkin":     {"shots": 1.02, "goals": 1.05, "points": 1.08},
    "sidney crosby":     {"shots": 1.05, "goals": 1.10, "points": 1.15},
    "nico hischier":     {"shots": 1.02, "goals": 1.05, "points": 1.05},
    # Grinders / vétérans playoffs — seuils assouplis (voir PLAYOFF_GRINDERS)
    "brendan gallagher": {"shots": 1.12, "goals": 1.08, "points": 1.02},  # validé 2026-04-29
    "ryan reaves":       {"shots": 1.05, "goals": 1.05, "points": 1.00},
    "nick foligno":      {"shots": 1.08, "goals": 1.08, "points": 1.02},
    "patrick maroon":    {"shots": 1.05, "goals": 1.10, "points": 1.00},  # big game player
    "tyler toffoli":     {"shots": 1.08, "goals": 1.12, "points": 1.05},
    "tanner pearson":    {"shots": 1.05, "goals": 1.05, "points": 1.02},
    "josh anderson":     {"shots": 1.10, "goals": 1.08, "points": 1.00},  # MTL grinder
    "joel armia":        {"shots": 1.05, "goals": 1.05, "points": 1.00},
    "tom wilson":        {"shots": 1.08, "goals": 1.08, "points": 1.02},
    "lars eller":        {"shots": 1.05, "goals": 1.05, "points": 1.00},
    "nicolas deslauriers": {"shots": 1.05, "goals": 1.02, "points": 1.00},
    "wayne simmonds":    {"shots": 1.05, "goals": 1.05, "points": 1.00},
    "zach hyman":        {"shots": 1.08, "goals": 1.12, "points": 1.05},  # net-front EDM
    "evan rodrigues":    {"shots": 1.05, "goals": 1.02, "points": 1.02},
    # PHI/PIT séries ce soir
    "sean couturier":    {"shots": 1.05, "goals": 1.10, "points": 1.08},
    "travis konecny":    {"shots": 1.05, "goals": 1.08, "points": 1.05},
    "carter hart":       {"shots": 1.00, "goals": 0.90, "points": 0.90},
    "evgeni malkin":     {"shots": 1.02, "goals": 1.05, "points": 1.08},
    # UTA/VGK séries ce soir
    "jack eichel":       {"shots": 1.05, "goals": 1.10, "points": 1.12},  # leadership Vegas
    "mark stone":        {"shots": 1.08, "goals": 1.10, "points": 1.12},  # clutch player
    "jonathan marchessault": {"shots": 1.05, "goals": 1.15, "points": 1.10},
    "dylan guenther":    {"shots": 1.05, "goals": 1.08, "points": 1.05},
    "clayton keller":    {"shots": 1.02, "goals": 1.05, "points": 1.05},
}

# ── GRINDERS PLAYOFFS ─────────────────────────────────────────────────────────
# Joueurs dont le style (net-front, physique, vétéran) génère des shots
# indépendamment de la qualité défensive adverse en playoffs.
# Seuils assouplis: shots_min 1.5 (vs 2.0) + filtre DEF_RANK ignoré.
# Insight validé: Gallagher 2026-04-29 (shots payant malgré défense TBL).
PLAYOFF_GRINDERS = {
    "brendan gallagher", "josh anderson", "joel armia", "nicolas deslauriers",
    "nick foligno", "tom wilson", "zach hyman", "ryan reaves",
    "patrick maroon", "tyler toffoli", "wayne simmonds", "tanner pearson",
    "lars eller", "evan rodrigues",
    "sean couturier", "travis konecny",
    "mark stone", "jonathan marchessault",
    "jake guentzel", "brad marchand",
}

# ── LISTE BLESSURES MANUELLE ──────────────────────────────────────────────────
# L'API NHL.com ne met pas toujours a jour les statuts IR/LTIR correctement.
# Ajouter ici les joueurs confirmes blessés long terme (nom exact comme dans l'API).
# Format: "Prenom Nom" en minuscules.
# Mettre a jour quand un joueur revient au jeu ou est blessé.
KNOWN_INJURED = {
    # DAL
    "tyler seguin",
    "mason marchment",
    # TOR
    "john tavares",
    "ryan reaves",
    # BOS
    "charlie coyle",
    # EDM
    "ryan nugent-hopkins",
    # FLA
    "matthew tkachuk",
    # MTL
    "christian dvorak",
    # NYR
    "jacob trouba",
    "ryan lindgren",
    # PIT
    "reilly smith",
    "evgeni malkin",
    # WSH
    "dylan strome",
    # VAN
    "elias pettersson",
    "tyler myers",
    # COL
    "valeri nichushkin",
    # MIN
    "marcus foligno",
    # STL
    "jordan kyrou",
    # NJD
    "dougie hamilton",
    # BUF
    "tage thompson",
    # CGY
    "nazem kadri",
    # ANA
    "troy terry",
    # SJS
    "logan couture",
    # CHI
    "taylor hall",
    "patrick kane",
    # NSH
    "ryan o'reilly",
    # SEA
    "jordan eberle",
}
# ─────────────────────────────────────────────────────────────────────────────

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


def _is_known_injured(name: str) -> bool:
    return name.lower().strip() in KNOWN_INJURED


# Mapping marche DK → type interne
_MKT_API_TO_TYPE = {
    "player_shots_on_goal": "shots",
    "player_goals":         "goals",
    "player_points":        "points",
}


def _build_real_props_lookup(real_props: dict) -> dict:
    """Construit {name_lower: {mkt_type: prop_data}} depuis le dict real_props de l'API."""
    lookup = {}
    if not real_props:
        return lookup
    for api_key, mkt_type in _MKT_API_TO_TYPE.items():
        for prop in real_props.get(api_key, []):
            name_lower = prop["player"].lower()
            if name_lower not in lookup:
                lookup[name_lower] = {}
            lookup[name_lower][mkt_type] = prop
    return lookup


def _find_real_prop(lookup: dict, player_name: str, mkt_type: str) -> Optional[dict]:
    """Trouve la prop reelle pour un joueur (exact puis par nom de famille)."""
    name_lower = player_name.lower()
    if name_lower in lookup:
        return lookup[name_lower].get(mkt_type)
    # Fallback: correspondance sur le nom de famille uniquement
    last = name_lower.split()[-1] if name_lower else ""
    for k, v in lookup.items():
        if last and k.split()[-1] == last:
            return v.get(mkt_type)
    return None


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

    def analyze_game(self, home_team: str, away_team: str, real_props: dict = None,
                     game_total: float = None) -> dict:
        """
        real_props: dict retourne par OddsFetcher.get_nhl_player_props(event_id).
        Si None -> mode synthetique (retrocompatibilite).
        Si dict vide ou avec donnees -> mode reel, seules les props presentes dans DK sont evaluees.
        """
        print(f"  Analyse props: {away_team} @ {home_team}...")

        props_lkp = _build_real_props_lookup(real_props) if real_props is not None else None
        mode = "reel" if real_props is not None else "synthetique"
        if real_props is not None:
            n_lines = sum(len(v) for v in real_props.values())
            print(f"    Mode {mode}: {n_lines} lignes DK disponibles")

        lineup_confirmed = self._lineup_confirmed(home_team, away_team)
        home_players = self._get_top_players(home_team)
        away_players = self._get_top_players(away_team)
        home_goalie  = self._get_goalie_stats(home_team)
        away_goalie  = self._get_goalie_stats(away_team)

        gt = game_total if game_total and game_total > 0 else LEAGUE_AVG_GAME_TOTAL
        home_bets = self._best_bets(home_players, away_team, home_team, 3, lineup_confirmed, props_lkp, gt)
        away_bets = self._best_bets(away_players, home_team, away_team, 3, lineup_confirmed, props_lkp, gt)

        all_bets = home_bets + away_bets
        all_bets.sort(key=lambda x: x["edge_pct"], reverse=True)
        all_bets = all_bets[:6]

        retour = self._retour_de_flamme(home_players, away_players, home_team, away_team, props_lkp)

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

    def _best_bets(self, players, opponent, team, n, lineup_confirmed, props_lkp=None,
                   game_total: float = LEAGUE_AVG_GAME_TOTAL):
        """
        props_lkp: dict cree par _build_real_props_lookup(real_props).
        game_total: total over/under du match (encode l'environnement de scoring).
        """
        opp_shots      = DEF_SHOTS_ALLOWED.get(opponent, LEAGUE_AVG_SHOTS)
        opp_ga         = DEF_GA_ALLOWED.get(opponent, LEAGUE_AVG_GA)
        shots_factor   = opp_shots / LEAGUE_AVG_SHOTS
        goals_factor   = opp_ga    / LEAGUE_AVG_GA
        shots_rank_opp = DEF_SHOTS_RANK.get(opponent, 16)
        ga_rank_opp    = DEF_GA_RANK.get(opponent, 16)
        b365_impl_pct  = B365_VIG_IMPL * 100
        MIN_PROB, MAX_PROB, MIN_ODDS = 0.42, 0.62, 1.60
        use_real = props_lkp is not None

        candidates = []
        for p in players:
            if self._lineup_fetcher and self._lineup_fetcher.is_injured(p["name"], team):
                continue

            mult, pp_unit, line_num, is_defense = self._get_role_multiplier(p["name"], team)

            # ─── game_env_factor: encode l'environnement de scoring via le total O/U ───
            # IMPORTANT: si les stats du joueur sont deja en mode playoff (playoff_mode=True),
            # la reduction (~7%) a DEJA ete appliquee dans _get_player_stats.
            # On utilise PLAYOFF_AVG_GAME_TOTAL comme base pour eviter le double-comptage.
            # Ex saison reguliere: game_total=6.0 → 6.0/6.2 = 0.97 (legere reduction)
            # Ex match playoff neutre: game_total=5.5 → 5.5/5.5 = 1.0 (neutre — deja encode)
            # Ex match playoff defensif: game_total=4.8 → 4.8/5.5 = 0.87 → clamp 0.92
            is_playoff = p.get("playoff_mode", False)
            if is_playoff:
                raw_gef = game_total / PLAYOFF_AVG_GAME_TOTAL if game_total > 0 else 1.0
                game_env_factor = max(0.92, min(1.10, raw_gef))
            else:
                game_env_factor = game_total / LEAGUE_AVG_GAME_TOTAL if game_total > 0 else 1.0

            # ── REGRESSION-TO-MEAN EN PLAYOFFS ────────────────────────────────────────
            # Quand un joueur est >25% sous sa moyenne L5 ET en mode playoff,
            # il y a une pression accrue d'elever son jeu (elimination, role de star).
            # Insight utilisateur: Pastrnak sous moyenne en game elimination → retour attendu.
            # Formule: max +8% tirant vers la moyenne, proportionnel a l'ecart.
            last5_shots_raw = p.get("last5_shots", 0)
            last5_avg_s = last5_shots_raw / 5 if last5_shots_raw else p["shots_pg"]
            regression_boost = 1.0
            regression_note = None
            if is_playoff and p["shots_pg"] > 0 and last5_avg_s > 0:
                ratio_l5 = last5_avg_s / p["shots_pg"]
                if ratio_l5 < 0.75:  # >25% sous la moyenne L5
                    regression_boost = min(1.08, 1.0 + (1.0 - ratio_l5) * 0.15)
                    regression_note = (f"⚡ Régression attendue — L5: {round(last5_avg_s,1)}/m"
                                       f" vs moy {p['shots_pg']}/m (+{round((regression_boost-1)*100)}%)")

            # Shots: facteur adversaire × environnement scoring × régression playoffs
            shots_adj  = min(p["shots_pg"]  * shots_factor * game_env_factor * mult * regression_boost, 8.0)
            goals_adj  = min(p["goals_pg"]  * goals_factor * mult, 1.5)

            # Points: part du joueur dans les buts attendus du match
            # Modele scoring-share: player_pts / league_avg_ga × expected_team_goals
            # Base: expected_team_goals calcule a partir du total O/U encode dans game_total
            # En playoff: expected_team_goals = game_total/2 (reflete environnement reel du match)
            player_pts_share = p["points_pg"] / LEAGUE_AVG_GA  # part historique du joueur
            expected_team_goals = game_total / 2               # buts attendus pour son equipe
            points_adj = min(player_pts_share * expected_team_goals * mult, 3.0)

            markets = []

            # Grinder playoff: seuils assouplis — valide quel que soit le rang défensif adverse
            is_grinder = is_playoff and p["name"].lower() in PLAYOFF_GRINDERS
            shots_min_threshold  = 1.5 if is_grinder else 2.0
            shots_rank_threshold = 1   if is_grinder else MIN_DEF_RANK_SHOTS  # tous les matchups OK

            # SHOTS — seuils standards, assouplis pour grinders playoffs
            if shots_rank_opp >= shots_rank_threshold and p["shots_pg"] >= shots_min_threshold:
                if use_real:
                    rp = _find_real_prop(props_lkp, p["name"], "shots")
                    if rp:
                        sl = rp["line"]
                        dk_impl = rp["over_implied"]
                        dk_odds = rp["over_odds"]
                        pv = _poisson_over(shots_adj, sl) / 100
                        sp = round(pv * 100, 1)
                        se = min(_edge(sp, dk_impl), MAX_EDGE_DISPLAY)
                        ratio = (sp / dk_impl) if dk_impl > 0 else 0
                        if se >= MIN_EDGE_SHOTS and dk_odds >= MIN_ODDS and ratio <= MAX_DISAGREEMENT_SHOTS:
                            markets.append({"type":"shots","label":"Shots Over "+str(sl),
                                "prob":sp,"edge":se,"kelly":_kelly(sp, dk_impl/100, dk_odds),
                                "est_odds":dk_odds,"dk_implied":round(dk_impl,1),
                                "detail":str(round(shots_adj,1))+" shots proj. · moy "+str(p["shots_pg"])+"/m · DEF #"+str(shots_rank_opp)})
                else:
                    sl, sp, se = None, 0.0, 0.0
                    for cl in [5.5, 4.5, 3.5, 2.5, 1.5, 0.5]:
                        pv = _poisson_over(shots_adj, cl) / 100
                        if MIN_PROB <= pv <= MAX_PROB:
                            sl, sp, se = cl, round(pv*100,1), min(_edge(round(pv*100,1), b365_impl_pct), MAX_EDGE_DISPLAY)
                            break
                    if sl is None:
                        bd = 99.0
                        for cl in [0.5,1.5,2.5,3.5,4.5,5.5]:
                            pv = _poisson_over(shots_adj, cl) / 100
                            d = abs(pv - 0.5)
                            if d < bd:
                                bd, sl, sp, se = d, cl, round(pv*100,1), min(_edge(round(pv*100,1), b365_impl_pct), MAX_EDGE_DISPLAY)
                    so = _est_odds(sp)
                    if sl and se >= MIN_EDGE_SHOTS and so >= MIN_ODDS:
                        markets.append({"type":"shots","label":"Shots Over "+str(sl),
                            "prob":sp,"edge":se,"kelly":_kelly(sp,B365_VIG_IMPL,B365_VIG_ODDS),
                            "est_odds":so,"dk_implied":round(b365_impl_pct,1),
                            "detail":str(round(shots_adj,1))+" shots proj. · moy "+str(p["shots_pg"])+"/m · DEF #"+str(shots_rank_opp)})

            # BUTS — vs defense poreuse ET buteur solide
            if ga_rank_opp >= MIN_DEF_RANK_GOALS and p["goals_pg"] >= 0.40:
                if use_real:
                    rp = _find_real_prop(props_lkp, p["name"], "goals")
                    if rp:
                        gl = "Goals Over " + str(rp["line"])
                        dk_impl = rp["over_implied"]
                        dk_odds = rp["over_odds"]
                        pv = _poisson_over(goals_adj, rp["line"]) / 100
                        gp = round(pv * 100, 1)
                        ge = min(_edge(gp, dk_impl), MAX_EDGE_DISPLAY)
                        ratio_g = (gp / dk_impl) if dk_impl > 0 else 0
                        if ge >= MIN_EDGE and dk_odds >= MIN_ODDS and ratio_g <= MAX_DISAGREEMENT_GOALS:
                            markets.append({"type":"goals","label":gl,
                                "prob":gp,"edge":ge,"kelly":_kelly(gp, dk_impl/100, dk_odds),
                                "est_odds":dk_odds,"dk_implied":round(dk_impl,1),
                                "detail":str(round(goals_adj,2))+" buts proj. · moy "+str(round(p["goals_pg"],2))+"/m · DEF buts #"+str(ga_rank_opp)})
                else:
                    gr = _poisson_over(goals_adj, 0.5) / 100
                    if gr > MAX_PROB:
                        gp, gl = round(_poisson_over(goals_adj, 1.5), 1), "Buts Over 1.5"
                    else:
                        gp, gl = round(gr*100,1), "Buts Over 0.5"
                    ge, go = min(_edge(gp, b365_impl_pct), MAX_EDGE_DISPLAY), _est_odds(gp)
                    if ge >= MIN_EDGE and go >= MIN_ODDS:
                        markets.append({"type":"goals","label":gl,
                            "prob":gp,"edge":ge,"kelly":_kelly(gp,B365_VIG_IMPL,B365_VIG_ODDS),
                            "est_odds":go,"dk_implied":round(b365_impl_pct,1),
                            "detail":str(round(goals_adj,2))+" buts proj. · moy "+str(round(p["goals_pg"],2))+"/m · DEF buts #"+str(ga_rank_opp)})

            # POINTS — seulement pour joueurs avec production suffisante
            is_playmaker = p.get("assists_pg", 0) > p["goals_pg"] * 1.5
            has_min_points = p["points_pg"] >= 0.50  # Abaisse de 0.55 — 0.50 pts/m suffit
            if has_min_points and (not markets or is_playmaker):
                if use_real:
                    rp = _find_real_prop(props_lkp, p["name"], "points")
                    if rp:
                        pl = "Points Over " + str(rp["line"])
                        dk_impl = rp["over_implied"]
                        dk_odds = rp["over_odds"]
                        pv = _poisson_over(points_adj, rp["line"]) / 100
                        pp2 = round(pv * 100, 1)
                        pe = min(_edge(pp2, dk_impl), MAX_EDGE_DISPLAY)
                        ratio_p = (pp2 / dk_impl) if dk_impl > 0 else 0
                        if pe >= MIN_EDGE and dk_odds >= MIN_ODDS and ratio_p <= MAX_DISAGREEMENT_POINTS:
                            markets.append({"type":"points","label":pl,
                                "prob":pp2,"edge":pe,"kelly":_kelly(pp2, dk_impl/100, dk_odds),
                                "est_odds":dk_odds,"dk_implied":round(dk_impl,1),
                                "detail":str(round(points_adj,2))+" pts proj. · moy "+str(round(p["points_pg"],2))+"/m"})
                else:
                    pr_raw = _poisson_over(points_adj, 0.5) / 100
                    if pr_raw > MAX_PROB:
                        pp2, pl = round(_poisson_over(points_adj, 1.5), 1), "Points Over 1.5"
                    else:
                        pp2, pl = round(pr_raw*100,1), "Points Over 0.5"
                    pe, po = min(_edge(pp2, b365_impl_pct), MAX_EDGE_DISPLAY), _est_odds(pp2)
                    if pe >= MIN_EDGE and po >= MIN_ODDS:
                        markets.append({"type":"points","label":pl,
                            "prob":pp2,"edge":pe,"kelly":_kelly(pp2,B365_VIG_IMPL,B365_VIG_ODDS),
                            "est_odds":po,"dk_implied":round(b365_impl_pct,1),
                            "detail":str(round(points_adj,2))+" pts proj. · moy "+str(round(p["points_pg"],2))+"/m"})

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
            if regression_note:
                context_notes = [regression_note] + context_notes[:3]
            if is_grinder and not regression_note:
                context_notes = ["💪 Grinder playoff — net-front, shots indép. de la défense"] + context_notes[:3]

            # Shots display: utilise la vraie ligne DK si disponible
            s_adj_display = round(min(p["shots_pg"] * shots_factor * mult, 8.0), 1)
            s_line_display = None
            s_prob_display = 0.0
            s_edge_display = 0.0
            if use_real:
                rp_s = _find_real_prop(props_lkp, p["name"], "shots")
                if rp_s:
                    s_line_display = rp_s["line"]
                    pv = _poisson_over(s_adj_display, s_line_display) / 100
                    s_prob_display = round(pv * 100, 1)
                    s_edge_display = _edge(s_prob_display, rp_s["over_implied"])
            else:
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
                "b365_implied":best.get("dk_implied", round(b365_impl_pct,1)),"all_markets":markets,
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

    def _retour_de_flamme(self, home_players, away_players, home_team, away_team, props_lkp=None) -> list:
        retour = []
        seen   = set()
        use_real = props_lkp is not None

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

                if avg10 < 2.5: continue
                if avg5 >= avg10 * 0.75: continue

                drop_pct = round((1 - avg5 / avg10) * 100)

                adj_factor  = DEF_SHOTS_ALLOWED.get(opponent, LEAGUE_AVG_SHOTS) / LEAGUE_AVG_SHOTS
                adj_deprime = avg5  * adj_factor
                adj_reel    = avg10 * adj_factor

                # Ligne DK: utilise la vraie si disponible, sinon estimee
                if use_real:
                    rp = _find_real_prop(props_lkp, name, "shots")
                    if not rp:
                        continue  # Pas de ligne DK disponible — skip
                    dk_line_est = rp["line"]
                    dk_impl     = rp["over_implied"]
                    est_odds    = rp["over_odds"]
                else:
                    dk_line_est = max(round(adj_deprime * 0.85 * 2) / 2, 0.5)
                    dk_impl     = B365_VIG_IMPL * 100
                    est_odds    = _est_odds(_poisson_over(adj_reel, dk_line_est))

                our_prob = _poisson_over(adj_reel, dk_line_est)
                edge     = _edge(our_prob, dk_impl)

                if use_real:
                    if edge < 12.0:
                        continue
                else:
                    if edge < 12.0 or est_odds < 1.65:
                        continue

                kelly_val = _kelly(our_prob, dk_impl/100, est_odds) if use_real else _kelly(our_prob, B365_VIG_IMPL, B365_VIG_ODDS)

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
                    "kelly":         kelly_val,
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
                # Filtre 1: statut IR/LTIR de l'API
                if p.get("injuryStatus") in ("IR","LTIR","Day-to-Day","Injured"): continue
                fn   = p.get("firstName", {}).get("default", "")
                ln   = p.get("lastName",  {}).get("default", "")
                full = fn + " " + ln
                # Filtre 2: liste blessures manuelle (plus fiable que l'API)
                if _is_known_injured(full):
                    print(f"    ⛔ {full} exclu (KNOWN_INJURED)")
                    continue
                # Filtre 3: lineup fetcher
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

    def _compute_stats_from_logs(self, logs: list) -> dict:
        """Calcule les stats moyennes ponderees a partir d'une liste de game logs."""
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
        return {
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

    def _get_player_stats(self, player_id: int, name: str) -> Optional[dict]:
        if not player_id:
            return None
        key = str(player_id)
        if key in self._stats_cache:
            return self._stats_cache[key]

        # 1. Stats saison reguliere
        rs_data = _get(f"{NHL_API}/player/{player_id}/game-log/{SEASON}/{GAME_TYPE}")
        rs_logs = rs_data.get("gameLog", []) if rs_data else []

        # 2. Stats series en cours (game_type=3) — vides si pas encore en series
        po_data = _get(f"{NHL_API}/player/{player_id}/game-log/{SEASON}/{GAME_TYPE_PLAYOFFS}")
        po_logs = po_data.get("gameLog", []) if po_data else []

        if not rs_logs and not po_logs:
            return None

        name_lower = name.lower().strip()
        pf = PLAYOFF_FACTORS.get(name_lower, {})

        if len(po_logs) >= 2:
            # Assez de matchs de series: blender 70% series / 30% saison reguliere
            po_stats = self._compute_stats_from_logs(po_logs)
            rs_stats = self._compute_stats_from_logs(rs_logs) if rs_logs else po_stats
            result = {
                "shots_pg":      round(po_stats["shots_pg"]  * 0.70 + rs_stats["shots_pg"]  * 0.30, 2),
                "goals_pg":      round(po_stats["goals_pg"]  * 0.70 + rs_stats["goals_pg"]  * 0.30, 3),
                "assists_pg":    round(po_stats["assists_pg"] * 0.70 + rs_stats["assists_pg"] * 0.30, 3),
                "points_pg":     round(po_stats["points_pg"] * 0.70 + rs_stats["points_pg"] * 0.30, 3),
                "toi_str":       po_stats["toi_str"],
                "n_games":       po_stats["n_games"],
                "last5_shots":   po_stats["last5_shots"],
                "last5_goals":   po_stats["last5_goals"],
                "last5_points":  po_stats["last5_points"],
                "last10_shots":  po_stats["last10_shots"],
                "last10_goals":  po_stats["last10_goals"],
                "last10_points": po_stats["last10_points"],
                "season_goals":  po_stats["season_goals"],
                "season_points": po_stats["season_points"],
                "playoff_games": len(po_logs),
                "playoff_mode":  True,
            }
            print(f"      Series: {len(po_logs)} matchs — stats blendees 70/30 pour {name}")
        else:
            # Pas encore de stats de series: saison reguliere × facteurs historiques + ajust. ligue
            result = self._compute_stats_from_logs(rs_logs) if rs_logs else None
            if not result:
                return None

            shots_f  = pf.get("shots",  PLAYOFF_LEAGUE_SHOTS)
            goals_f  = pf.get("goals",  PLAYOFF_LEAGUE_GOALS)
            points_f = pf.get("points", (PLAYOFF_LEAGUE_SHOTS + PLAYOFF_LEAGUE_GOALS) / 2)

            # Appliquer l'ajustement ligue si le joueur n'est pas dans PLAYOFF_FACTORS
            if not pf:
                shots_f  *= PLAYOFF_LEAGUE_SHOTS / 0.90   # deja inclu dans la constante
                goals_f  *= PLAYOFF_LEAGUE_GOALS / 0.88
                points_f = (shots_f + goals_f) / 2

            adj_shots  = min(result["shots_pg"]  * shots_f,  8.0)
            adj_goals  = min(result["goals_pg"]  * goals_f,  1.5)
            adj_points = min(result["points_pg"] * points_f, 3.0)

            if pf:
                print(f"      Facteur series historique applique: {name} ({shots_f:.2f}x shots)")
            else:
                print(f"      Ajust. ligue series applique: {name} ({PLAYOFF_LEAGUE_SHOTS:.2f}x shots)")

            result["shots_pg"]  = round(adj_shots,  2)
            result["goals_pg"]  = round(adj_goals,  3)
            result["points_pg"] = round(adj_points, 3)
            result["playoff_games"] = len(po_logs)
            result["playoff_mode"]  = True

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
