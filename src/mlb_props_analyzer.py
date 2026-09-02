"""
MLB Props Analyzer
Marches: pitcher_strikeouts UNIQUEMENT (seul marche profitable — WR 59%+, ROI +13%)
Retires: batter_hits (WR 45%, ROI -10%), batter_total_bases (WR 37%, ROI -24%),
         batter_runs_scored (non resolvable par le backtester)
Edge minimum: 12% (anciennement 8%) — filtre volume/qualite

Meilleures pratiques integrees:
  1. Props lanceurs = marche le plus predictible du baseball (K rate stable)
  2. Ajustement taux K adverse (equipe qui frappe mal = avantage lanceur)
  3. Park factors (Coors +runs, Oracle Park -runs)
  4. Distribution normale calibree MLB
  5. Critere de Kelly fractionne (1/4) pour gestion du risque
  6. Edge reel vs cotes DraftKings — on ne recommande QUE les Overs a valeur
     (notre prob > prob implicite du marche) et on enregistre la vraie cote
     pour un suivi de profit fiable
"""
from __future__ import annotations

import math

# Modele K en deux etapes (manches puis retraits). Dependance dure: sans lui on
# n'a plus de ladder, et un repli silencieux sur l'ancienne normale publierait
# des probabilites differentes sans le dire.
import mlb_k_distribution as KD
import odds_api

try:
    from mlb_rolling_stats import get_pitcher_ip_starts as _get_pitcher_ip_starts
    from mlb_rolling_stats import get_batter_rolling as _mlb_batter_rolling
    from mlb_rolling_stats import get_pitcher_rolling as _mlb_pitcher_rolling
    from mlb_rolling_stats import get_team_k_rate_season as _get_team_k_rate_season
    from mlb_rolling_stats import get_league_k_rate as _get_league_k_rate
    from mlb_rolling_stats import get_pitcher_hand as _get_pitcher_hand
    HAS_MLB_ROLLING = True
except ImportError:
    HAS_MLB_ROLLING = False
    def _get_pitcher_ip_starts(name, n=15): return None
    def _get_team_k_rate_season(team, vs_hand=None):
        return {"k_pct": 0.22, "source": "defaut", "pa": 0}
    def _get_league_k_rate(): return 0.22
    def _get_pitcher_hand(name): return None

# ── MODELES STATISTIQUES ──────────────────────────────────────────────────────
STD_FLOOR = {
    "strikeouts":    0.33,
    "hits":          0.62,
    "total_bases":   0.58,
    "home_runs":     0.80,  # HR tres volatile — STD large
    "runs_scored":   0.55,  # Runs marqués — assez stable pour les hauts de l'ordre
}

LINE_OFFSET = {
    "strikeouts":    1.0,
    "hits":          0.5,
    "total_bases":   0.5,
    "home_runs":     0.0,   # Ligne toujours 0.5
    "runs_scored":   0.0,   # Ligne toujours 0.5
}

STAT_CONFIGS = [
    {"key": "strikeouts",  "label": "Retraits au baton", "min_avg": 5.0,  "player_type": "pitcher"},
]

MIN_EDGE   = 15.0  # Relevé de 12% → 15% — on ne garde que la tranche edge>=15 (52% WR, seule profitable au backtest)
MAX_EDGE   = 35.0
# Plancher de cote. Mesuré sur 397 bets avec cote réelle enregistrée:
#   cote 1.50-1.64 → ROI -19.0%   |   1.65-1.84 → ROI  -7.8%
#   cote 1.85-2.09 → ROI  +9.6%   |   2.10+     → ROI +76.5% (n=10)
# Confirmé par la marge de projection (415 picks appariés aux archives): même
# quand la projection dépasse la ligne de 1.5-2.0 K, la WR réelle est 53.6% —
# rendre la ligne plus facile n'augmente PAS la WR, l'erreur est dans la
# projection elle-même. À 53% de WR le breakeven est 1.89.
# Donc: rien sous 1.90. À 1.75 le ROI attendu reste négatif (-7%).
MIN_ODDS   = 1.90
B365_IMPLIED = 52.63  # ~1.909 cotes b365 standard — référence fixe (algo 70% WR)
B365_ODDS    = 1.909
MAX_BETS   = 5
MAX_DISAGREEMENT_RATIO = 1.30  # Légèrement plus permissif que l'ancien 1.25

_STAT_TO_MARKET = {
    "strikeouts":  "pitcher_strikeouts",
    "hits":        "batter_hits",
    "total_bases": "batter_total_bases",
    "home_runs":   "batter_home_runs",
    "runs_scored": "batter_runs_scored",
}

# ── PARK FACTORS ─────────────────────────────────────────────────────────────
PARK_FACTORS = {
    "Colorado Rockies":       1.15,
    "Cincinnati Reds":        1.08,
    "Texas Rangers":          1.05,
    "Arizona Diamondbacks":   1.04,
    "Baltimore Orioles":      1.04,
    "Chicago Cubs":           1.02,
    "Atlanta Braves":         1.02,
    "New York Yankees":       1.00,
    "Los Angeles Angels":     1.00,
    "Boston Red Sox":         1.00,
    "Philadelphia Phillies":  1.00,
    "Toronto Blue Jays":      1.00,
    "Detroit Tigers":         0.99,
    "Minnesota Twins":        0.99,
    "Kansas City Royals":     0.99,
    "Oakland Athletics":      0.98,
    "St. Louis Cardinals":    0.98,
    "Pittsburgh Pirates":     0.97,
    "Tampa Bay Rays":         0.97,
    "Cleveland Guardians":    0.97,
    "Houston Astros":         0.97,
    "New York Mets":          0.97,
    "Washington Nationals":   0.97,
    "Chicago White Sox":      0.96,
    "Milwaukee Brewers":      0.96,
    "Los Angeles Dodgers":    0.95,
    "Seattle Mariners":       0.95,
    "Miami Marlins":          0.95,
    "San Diego Padres":       0.92,
    "San Francisco Giants":   0.90,
}

# ── TAUX DE RETRAITS EQUIPES ADVERSES (pour props lanceurs) ──────────────────
TEAM_K_RATES = {
    "Colorado Rockies":       0.245,
    "Pittsburgh Pirates":     0.240,
    "Oakland Athletics":      0.238,
    "Chicago Cubs":           0.232,
    "Arizona Diamondbacks":   0.230,
    "Miami Marlins":          0.228,
    "Washington Nationals":   0.225,
    "Texas Rangers":          0.224,
    "San Francisco Giants":   0.220,
    "New York Mets":          0.220,
    "Chicago White Sox":      0.218,
    "Tampa Bay Rays":         0.218,
    "Detroit Tigers":         0.216,
    "Boston Red Sox":         0.215,
    "Cincinnati Reds":        0.215,
    "Toronto Blue Jays":      0.215,
    "Atlanta Braves":         0.215,
    "Minnesota Twins":        0.213,
    "Baltimore Orioles":      0.212,
    "Milwaukee Brewers":      0.212,
    "Kansas City Royals":     0.210,
    "Cleveland Guardians":    0.210,
    "San Diego Padres":       0.210,
    "Los Angeles Dodgers":    0.208,
    "Philadelphia Phillies":  0.206,
    "Seattle Mariners":       0.206,
    "Los Angeles Angels":     0.205,
    "St. Louis Cardinals":    0.200,
    "New York Yankees":       0.200,
    "Houston Astros":         0.185,
}
LEAGUE_AVG_K     = 0.215  # obsolete: le K% de ligue est maintenant calcule en
                          # direct (get_league_k_rate) — garde pour reference
LEAGUE_AVG_K_SP  = 7.5   # K/depart moyen lanceur partant MLB

# ── AJUSTEMENT K% ADVERSE (regresse) ─────────────────────────────────────────
# Ancienne formule: proj = blend * (K%_adverse_10j / 0.215)
#   → un blend de 5.82K devenait 7.8K (+34%). Deux defauts cumules:
#     1. le ratio etait applique en entier (elasticite implicite = 1.0), alors
#        qu'un lanceur ne recupere qu'une fraction du K% de l'equipe adverse;
#     2. le numerateur venait d'une fenetre 10 jours (~350 PA), donc surtout
#        du bruit, et le denominateur d'une constante figee.
# Nouvelle formule:
#   lambda_ajuste = blend * (K%_adverse_saison / K%_ligue) ** K_REGRESSION_EXP
#                         * park_factor
# A 0.5 (racine carree) le meme ecart de K% adverse ne deplace la projection
# que de la moitie (en log), ce qui ramene l'ajustement dans une plage
# defendable (~ +/- 8% au lieu de +/- 20%).
K_REGRESSION_EXP  = 0.5
LEAGUE_K_FALLBACK = 0.22   # si l'API ne donne pas la moyenne de la saison


# ── LANCEURS PARTANTS ─────────────────────────────────────────────────────────
# hand: "R" droitier, "L" gaucher
MLB_PITCHERS = {
    # Elite
    "Tyler Glasnow":        {"strikeouts": 9.5,  "team": "Los Angeles Dodgers",    "hand": "R"},
    "Shohei Ohtani":        {"strikeouts": 9.2,  "team": "Los Angeles Dodgers",    "hand": "L"},
    "Tarik Skubal":         {"strikeouts": 8.8,  "team": "Detroit Tigers",         "hand": "L"},
    "Blake Snell":          {"strikeouts": 8.7,  "team": "San Francisco Giants",   "hand": "L"},
    "Freddy Peralta":       {"strikeouts": 8.5,  "team": "Milwaukee Brewers",      "hand": "R"},
    "Gerrit Cole":          {"strikeouts": 8.5,  "team": "New York Yankees",       "hand": "R"},
    "Zack Wheeler":         {"strikeouts": 8.5,  "team": "Philadelphia Phillies",  "hand": "R"},
    "Aaron Nola":           {"strikeouts": 8.5,  "team": "Philadelphia Phillies",  "hand": "R"},
    "Cole Ragans":          {"strikeouts": 8.5,  "team": "Kansas City Royals",     "hand": "L"},
    # Tier 2
    "Yoshinobu Yamamoto":   {"strikeouts": 8.2,  "team": "Los Angeles Dodgers",    "hand": "R"},
    "Dylan Cease":          {"strikeouts": 8.2,  "team": "San Diego Padres",       "hand": "R"},
    "Kevin Gausman":        {"strikeouts": 8.0,  "team": "Toronto Blue Jays",      "hand": "R"},
    "Chris Sale":           {"strikeouts": 8.0,  "team": "Atlanta Braves",         "hand": "L"},
    "MacKenzie Gore":       {"strikeouts": 8.0,  "team": "Washington Nationals",   "hand": "L"},
    "Carlos Rodon":         {"strikeouts": 8.0,  "team": "New York Yankees",       "hand": "L"},
    "Max Fried":            {"strikeouts": 7.8,  "team": "New York Yankees",       "hand": "L"},
    "Logan Gilbert":        {"strikeouts": 7.8,  "team": "Seattle Mariners",       "hand": "R"},
    "Joe Ryan":             {"strikeouts": 7.8,  "team": "Minnesota Twins",        "hand": "R"},
    "Cody Morris":          {"strikeouts": 5.5,  "team": "Minnesota Twins",        "hand": "R"},
    "Sonny Gray":           {"strikeouts": 7.8,  "team": "St. Louis Cardinals",    "hand": "R"},
    "Luis Castillo":        {"strikeouts": 7.5,  "team": "Seattle Mariners",       "hand": "R"},
    "Corbin Burnes":        {"strikeouts": 7.5,  "team": "Baltimore Orioles",      "hand": "R"},
    "Pablo Lopez":          {"strikeouts": 7.5,  "team": "Minnesota Twins",        "hand": "R"},
    "Tanner Houck":         {"strikeouts": 7.5,  "team": "Boston Red Sox",         "hand": "R"},
    "Reid Detmers":         {"strikeouts": 7.5,  "team": "Los Angeles Angels",     "hand": "L"},
    "Patrick Sandoval":     {"strikeouts": 7.5,  "team": "Los Angeles Angels",     "hand": "L"},
    "Brandon Woodruff":     {"strikeouts": 7.5,  "team": "Milwaukee Brewers",      "hand": "R"},
    "Edward Cabrera":       {"strikeouts": 7.5,  "team": "Miami Marlins",          "hand": "R"},
    # Tier 3
    "George Kirby":         {"strikeouts": 7.2,  "team": "Seattle Mariners",       "hand": "R"},
    "Nestor Cortes":        {"strikeouts": 7.2,  "team": "New York Yankees",       "hand": "L"},
    "Hunter Brown":         {"strikeouts": 7.2,  "team": "Houston Astros",         "hand": "R"},
    "Jesus Luzardo":        {"strikeouts": 7.2,  "team": "Miami Marlins",          "hand": "L"},
    "Shane Bieber":         {"strikeouts": 7.0,  "team": "Cleveland Guardians",    "hand": "R"},
    "Tanner Bibee":         {"strikeouts": 6.8,  "team": "Cleveland Guardians",    "hand": "R"},
    "Gavin Williams":       {"strikeouts": 7.0,  "team": "Cleveland Guardians",    "hand": "R"},
    "Ben Lively":           {"strikeouts": 5.5,  "team": "Cleveland Guardians",    "hand": "R"},
    "Carlos Carrasco":      {"strikeouts": 5.5,  "team": "Cleveland Guardians",    "hand": "R"},
    "Zac Gallen":           {"strikeouts": 7.0,  "team": "Arizona Diamondbacks",   "hand": "R"},
    "Mitch Keller":         {"strikeouts": 7.0,  "team": "Pittsburgh Pirates",     "hand": "R"},
    "Sandy Alcantara":      {"strikeouts": 6.8,  "team": "Miami Marlins",          "hand": "R"},
    "Justin Steele":        {"strikeouts": 6.8,  "team": "Chicago Cubs",           "hand": "L"},
    "Seth Lugo":            {"strikeouts": 6.5,  "team": "Kansas City Royals",     "hand": "R"},
    "Ranger Suarez":        {"strikeouts": 6.5,  "team": "Philadelphia Phillies",  "hand": "L"},
    "Framber Valdez":       {"strikeouts": 6.5,  "team": "Houston Astros",         "hand": "L"},
    "Logan Webb":           {"strikeouts": 6.0,  "team": "San Francisco Giants",   "hand": "R"},
    # Tier 4 — partants reguliers (5.0–6.4)
    "Trevor Rogers":        {"strikeouts": 6.2,  "team": "Baltimore Orioles",      "hand": "L"},
    "Grayson Rodriguez":    {"strikeouts": 6.5,  "team": "Baltimore Orioles",      "hand": "R"},
    "Dean Kremer":          {"strikeouts": 5.8,  "team": "Baltimore Orioles",      "hand": "R"},
    "Cade Povich":          {"strikeouts": 5.5,  "team": "Baltimore Orioles",      "hand": "L"},
    "Chayce McDermott":     {"strikeouts": 6.0,  "team": "Baltimore Orioles",      "hand": "R"},
    "Albert Suarez":        {"strikeouts": 5.0,  "team": "Baltimore Orioles",      "hand": "R"},
    "B. Young":             {"strikeouts": 5.5,  "team": "Baltimore Orioles",      "hand": "L"},
    "Braxton Garrett":      {"strikeouts": 6.0,  "team": "Miami Marlins",          "hand": "L"},
    "Roddery Munoz":        {"strikeouts": 5.5,  "team": "Miami Marlins",          "hand": "R"},
    "Paul Skenes":          {"strikeouts": 8.8,  "team": "Pittsburgh Pirates",     "hand": "R"},
    "Marco Gonzales":       {"strikeouts": 5.5,  "team": "Seattle Mariners",       "hand": "L"},
    "Bryan Woo":            {"strikeouts": 6.5,  "team": "Seattle Mariners",       "hand": "R"},
    "Bryce Elder":          {"strikeouts": 5.8,  "team": "Atlanta Braves",         "hand": "R"},
    "Spencer Schwellenbach":{"strikeouts": 6.5,  "team": "Atlanta Braves",         "hand": "R"},
    "Bailey Ober":          {"strikeouts": 7.0,  "team": "Minnesota Twins",        "hand": "R"},
    "Simeon Woods Richardson":{"strikeouts": 6.0,"team": "Minnesota Twins",        "hand": "R"},
    "Nathan Eovaldi":       {"strikeouts": 6.5,  "team": "Texas Rangers",          "hand": "R"},
    "Jack Leiter":          {"strikeouts": 6.5,  "team": "Texas Rangers",          "hand": "R"},
    "Reese Olson":          {"strikeouts": 6.5,  "team": "Detroit Tigers",         "hand": "R"},
    "Kenta Maeda":          {"strikeouts": 6.0,  "team": "Detroit Tigers",         "hand": "R"},
    "Clarke Schmidt":       {"strikeouts": 6.5,  "team": "New York Yankees",       "hand": "R"},
    "Nick Lodolo":          {"strikeouts": 7.0,  "team": "Cincinnati Reds",        "hand": "L"},
    "Andrew Abbott":        {"strikeouts": 7.2,  "team": "Cincinnati Reds",        "hand": "L"},
    "Gavin Stone":          {"strikeouts": 6.8,  "team": "Los Angeles Dodgers",    "hand": "R"},
    "James Paxton":         {"strikeouts": 6.0,  "team": "Los Angeles Dodgers",    "hand": "L"},
    "Chris Bassitt":        {"strikeouts": 6.5,  "team": "Baltimore Orioles",      "hand": "R"},
    "Jordan Lyles":         {"strikeouts": 5.0,  "team": "Kansas City Royals",     "hand": "R"},
    "Brady Singer":         {"strikeouts": 6.5,  "team": "Kansas City Royals",     "hand": "R"},
    "Michael Lorenzen":     {"strikeouts": 5.5,  "team": "Kansas City Royals",     "hand": "R"},
    "Lance Lynn":           {"strikeouts": 6.0,  "team": "St. Louis Cardinals",    "hand": "R"},
    "Miles Mikolas":        {"strikeouts": 5.5,  "team": "St. Louis Cardinals",    "hand": "R"},
    "Yusei Kikuchi":        {"strikeouts": 7.5,  "team": "Toronto Blue Jays",      "hand": "L"},
    "Chris Flexen":         {"strikeouts": 5.5,  "team": "Chicago White Sox",      "hand": "R"},
    "Garrett Crochet":      {"strikeouts": 8.5,  "team": "Boston Red Sox",         "hand": "L"},
    "Brayan Bello":         {"strikeouts": 6.8,  "team": "Boston Red Sox",         "hand": "R"},
    "Shane McLanahan":      {"strikeouts": 8.0,  "team": "Tampa Bay Rays",         "hand": "L"},
    "Zach Eflin":           {"strikeouts": 6.5,  "team": "Tampa Bay Rays",         "hand": "R"},
    "Michael King":         {"strikeouts": 7.5,  "team": "San Diego Padres",       "hand": "R"},
    "Joe Musgrove":         {"strikeouts": 7.0,  "team": "San Diego Padres",       "hand": "R"},
    "Marcus Stroman":       {"strikeouts": 5.8,  "team": "Chicago Cubs",           "hand": "R"},
    "Kyle Hendricks":       {"strikeouts": 5.5,  "team": "Chicago Cubs",           "hand": "R"},
    "Jared Jones":          {"strikeouts": 7.0,  "team": "Pittsburgh Pirates",     "hand": "R"},
    "Quinn Priester":       {"strikeouts": 6.0,  "team": "Pittsburgh Pirates",     "hand": "R"},
    "Frankie Montas":       {"strikeouts": 6.5,  "team": "New York Mets",          "hand": "R"},
    "Sean Manaea":          {"strikeouts": 7.0,  "team": "New York Mets",          "hand": "L"},
    "Jose Quintana":        {"strikeouts": 6.0,  "team": "New York Mets",          "hand": "L"},
    "Taj Bradley":          {"strikeouts": 7.0,  "team": "Tampa Bay Rays",         "hand": "R"},
    "Colt Keith":           {"strikeouts": 5.5,  "team": "Detroit Tigers",         "hand": "R"},
    "Tylor Megill":         {"strikeouts": 6.5,  "team": "New York Mets",          "hand": "R"},
    "Bowden Francis":       {"strikeouts": 7.0,  "team": "Toronto Blue Jays",      "hand": "R"},
    "Chris Sale":           {"strikeouts": 8.0,  "team": "Atlanta Braves",         "hand": "L"},
    # ── Partants 2025-26 manquants ────────────────────────────────────────────
    "Shota Imanaga":        {"strikeouts": 8.2,  "team": "Chicago Cubs",           "hand": "L"},
    "Kyle Bradish":         {"strikeouts": 7.0,  "team": "Baltimore Orioles",      "hand": "R"},
    "Andrew Painter":       {"strikeouts": 8.0,  "team": "Philadelphia Phillies",  "hand": "R"},
    "Kumar Rocker":         {"strikeouts": 6.5,  "team": "Texas Rangers",          "hand": "R"},
    "Ryne Nelson":          {"strikeouts": 6.0,  "team": "Arizona Diamondbacks",   "hand": "R"},
    "Bryce Miller":         {"strikeouts": 6.5,  "team": "Seattle Mariners",       "hand": "R"},
    "Lance McCullers Jr.":  {"strikeouts": 7.0,  "team": "Houston Astros",         "hand": "R"},
    "Matthew Liberatore":   {"strikeouts": 5.5,  "team": "St. Louis Cardinals",    "hand": "L"},
    "J.T. Ginn":            {"strikeouts": 5.5,  "team": "Oakland Athletics",      "hand": "R"},
    "Robbie Ray":           {"strikeouts": 6.5,  "team": "San Francisco Giants",   "hand": "L"},
    "Christian Scott":      {"strikeouts": 6.5,  "team": "New York Mets",          "hand": "R"},
    "Max Meyer":            {"strikeouts": 7.0,  "team": "Miami Marlins",          "hand": "R"},
    "Jacob Misiorowski":    {"strikeouts": 7.0,  "team": "Milwaukee Brewers",      "hand": "R"},
    "Noah Schultz":         {"strikeouts": 6.0,  "team": "Chicago White Sox",      "hand": "L"},
    "Parker Messick":       {"strikeouts": 6.0,  "team": "Cleveland Guardians",    "hand": "L"},
    "Jake Irvin":           {"strikeouts": 5.5,  "team": "Washington Nationals",   "hand": "R"},
    "Jose Quintana":        {"strikeouts": 5.5,  "team": "Colorado Rockies",       "hand": "L"},
    "Griffin Jax":          {"strikeouts": 6.0,  "team": "Tampa Bay Rays",         "hand": "R"},
    "JR Ritchie":           {"strikeouts": 5.5,  "team": "Atlanta Braves",         "hand": "R"},
    "Dylan Cease":          {"strikeouts": 8.2,  "team": "Toronto Blue Jays",      "hand": "R"},
    "Framber Valdez":       {"strikeouts": 6.5,  "team": "Detroit Tigers",         "hand": "L"},
    "Michael King":         {"strikeouts": 7.5,  "team": "San Diego Padres",       "hand": "R"},
    "Cal Dollander":        {"strikeouts": 6.5,  "team": "Colorado Rockies",       "hand": "R"},
    "Kyle Bradish":         {"strikeouts": 7.0,  "team": "Baltimore Orioles",      "hand": "R"},
}

# ── FRAPPEURS ─────────────────────────────────────────────────────────────────
# bats: "R" droitier, "L" gaucher, "S" switch hitter
# hr: home runs par match (saison reguliere 2024-25)
MLB_BATTERS = {
    # runs_scored: runs marqués/match — dépend de la position dans l'ordre et OBP
    "Aaron Judge":           {"hits": 1.10, "total_bases": 2.50, "home_runs": 0.29, "runs_scored": 0.82, "team": "New York Yankees",       "bats": "R"},
    "Luis Arraez":           {"hits": 1.50, "total_bases": 1.85, "home_runs": 0.02, "runs_scored": 0.70, "team": "San Diego Padres",       "bats": "R"},
    "Freddie Freeman":       {"hits": 1.45, "total_bases": 2.35, "home_runs": 0.14, "runs_scored": 0.78, "team": "Los Angeles Dodgers",    "bats": "L"},
    "Ronald Acuna Jr.":      {"hits": 1.40, "total_bases": 2.40, "home_runs": 0.16, "runs_scored": 0.85, "team": "Atlanta Braves",         "bats": "R"},
    "Steven Kwan":           {"hits": 1.30, "total_bases": 1.75, "home_runs": 0.04, "runs_scored": 0.72, "team": "Cleveland Guardians",    "bats": "L"},
    "Juan Soto":             {"hits": 1.35, "total_bases": 2.30, "home_runs": 0.13, "runs_scored": 0.80, "team": "New York Mets",          "bats": "L"},
    "Mookie Betts":          {"hits": 1.35, "total_bases": 2.35, "home_runs": 0.11, "runs_scored": 0.82, "team": "Los Angeles Dodgers",    "bats": "R"},
    "Corey Seager":          {"hits": 1.35, "total_bases": 2.30, "home_runs": 0.15, "runs_scored": 0.75, "team": "Texas Rangers",          "bats": "L"},
    "Shohei Ohtani":         {"hits": 1.25, "total_bases": 2.45, "home_runs": 0.30, "runs_scored": 0.85, "team": "Los Angeles Dodgers",    "bats": "L"},
    "Bobby Witt Jr.":        {"hits": 1.30, "total_bases": 2.15, "home_runs": 0.09, "runs_scored": 0.80, "team": "Kansas City Royals",     "bats": "R"},
    "Trea Turner":           {"hits": 1.30, "total_bases": 2.05, "home_runs": 0.07, "runs_scored": 0.78, "team": "Philadelphia Phillies",  "bats": "R"},
    "Bryce Harper":          {"hits": 1.30, "total_bases": 2.35, "home_runs": 0.16, "runs_scored": 0.76, "team": "Philadelphia Phillies",  "bats": "L"},
    "Vladimir Guerrero Jr.": {"hits": 1.30, "total_bases": 2.10, "home_runs": 0.10, "runs_scored": 0.72, "team": "Toronto Blue Jays",      "bats": "R"},
    "Jose Ramirez":          {"hits": 1.30, "total_bases": 2.20, "home_runs": 0.12, "runs_scored": 0.75, "team": "Cleveland Guardians",    "bats": "S"},
    "Bo Bichette":           {"hits": 1.30, "total_bases": 2.00, "home_runs": 0.07, "runs_scored": 0.68, "team": "Toronto Blue Jays",      "bats": "R"},
    "Yordan Alvarez":        {"hits": 1.25, "total_bases": 2.50, "home_runs": 0.23, "runs_scored": 0.72, "team": "Houston Astros",         "bats": "L"},
    "Kyle Tucker":           {"hits": 1.25, "total_bases": 2.25, "home_runs": 0.14, "runs_scored": 0.70, "team": "Houston Astros",         "bats": "L"},
    "Rafael Devers":         {"hits": 1.25, "total_bases": 2.20, "home_runs": 0.15, "runs_scored": 0.68, "team": "Boston Red Sox",         "bats": "L"},
    "Julio Rodriguez":       {"hits": 1.25, "total_bases": 2.10, "home_runs": 0.09, "runs_scored": 0.70, "team": "Seattle Mariners",       "bats": "R"},
    "Nolan Arenado":         {"hits": 1.20, "total_bases": 2.00, "home_runs": 0.12, "runs_scored": 0.62, "team": "St. Louis Cardinals",    "bats": "R"},
    "Fernando Tatis Jr.":    {"hits": 1.20, "total_bases": 2.20, "home_runs": 0.15, "runs_scored": 0.72, "team": "San Diego Padres",       "bats": "R"},
    "Paul Goldschmidt":      {"hits": 1.20, "total_bases": 2.10, "home_runs": 0.11, "runs_scored": 0.65, "team": "St. Louis Cardinals",    "bats": "R"},
    "Adley Rutschman":       {"hits": 1.20, "total_bases": 1.90, "home_runs": 0.09, "runs_scored": 0.62, "team": "Baltimore Orioles",      "bats": "S"},
    "Alex Bregman":          {"hits": 1.20, "total_bases": 2.00, "home_runs": 0.11, "runs_scored": 0.65, "team": "Boston Red Sox",         "bats": "R"},
    "Francisco Lindor":      {"hits": 1.20, "total_bases": 2.05, "home_runs": 0.10, "runs_scored": 0.70, "team": "New York Mets",          "bats": "S"},
    "Cedric Mullins":        {"hits": 1.20, "total_bases": 1.85, "home_runs": 0.06, "runs_scored": 0.68, "team": "Baltimore Orioles",      "bats": "S"},
    "Xander Bogaerts":       {"hits": 1.20, "total_bases": 1.90, "home_runs": 0.08, "runs_scored": 0.62, "team": "San Diego Padres",       "bats": "R"},
    "Gunnar Henderson":      {"hits": 1.15, "total_bases": 2.10, "home_runs": 0.15, "runs_scored": 0.72, "team": "Baltimore Orioles",      "bats": "L"},
    "Mike Trout":            {"hits": 1.15, "total_bases": 2.20, "home_runs": 0.18, "runs_scored": 0.70, "team": "Los Angeles Angels",     "bats": "R"},
    "Nolan Jones":           {"hits": 1.15, "total_bases": 1.95, "home_runs": 0.13, "runs_scored": 0.68, "team": "Colorado Rockies",       "bats": "L"},
    "Marcus Semien":         {"hits": 1.15, "total_bases": 1.90, "home_runs": 0.09, "runs_scored": 0.72, "team": "Texas Rangers",          "bats": "R"},
    "Austin Riley":          {"hits": 1.15, "total_bases": 2.15, "home_runs": 0.16, "runs_scored": 0.65, "team": "Atlanta Braves",         "bats": "R"},
    "Michael Harris II":     {"hits": 1.15, "total_bases": 1.90, "home_runs": 0.08, "runs_scored": 0.65, "team": "Atlanta Braves",         "bats": "L"},
    "Jazz Chisholm Jr.":     {"hits": 1.15, "total_bases": 2.00, "home_runs": 0.13, "runs_scored": 0.70, "team": "New York Yankees",       "bats": "L"},
    "Anthony Volpe":         {"hits": 1.15, "total_bases": 1.85, "home_runs": 0.08, "runs_scored": 0.68, "team": "New York Yankees",       "bats": "R"},
    "Ben Rice":              {"hits": 1.05, "total_bases": 2.25, "home_runs": 0.40, "runs_scored": 0.65, "team": "New York Yankees",       "bats": "L"},
    "Elly De La Cruz":       {"hits": 1.15, "total_bases": 1.95, "home_runs": 0.10, "runs_scored": 0.72, "team": "Cincinnati Reds",        "bats": "S"},
    "Matt Olson":            {"hits": 1.10, "total_bases": 2.20, "home_runs": 0.18, "runs_scored": 0.65, "team": "Atlanta Braves",         "bats": "L"},
    "Pete Alonso":           {"hits": 1.10, "total_bases": 2.15, "home_runs": 0.18, "runs_scored": 0.62, "team": "New York Mets",          "bats": "R"},
    "Byron Buxton":          {"hits": 1.10, "total_bases": 2.20, "home_runs": 0.19, "runs_scored": 0.68, "team": "Minnesota Twins",        "bats": "R"},
    "Marcell Ozuna":         {"hits": 1.10, "total_bases": 2.10, "home_runs": 0.17, "runs_scored": 0.62, "team": "Atlanta Braves",         "bats": "R"},
    "Willy Adames":          {"hits": 1.10, "total_bases": 1.90, "home_runs": 0.10, "runs_scored": 0.60, "team": "San Francisco Giants",   "bats": "R"},
}

# ── LOOKUPS ───────────────────────────────────────────────────────────────────
_TEAM_PITCHERS = {}
for p, s in MLB_PITCHERS.items():
    _TEAM_PITCHERS.setdefault(s["team"], []).append(p)

_TEAM_BATTERS = {}
for p, s in MLB_BATTERS.items():
    _TEAM_BATTERS.setdefault(s["team"], []).append(p)


# ── AJUSTEMENTS ───────────────────────────────────────────────────────────────

def _pitcher_difficulty_adj(pitcher_k: float) -> tuple:
    """
    Facteur multiplicateur sur la moyenne du frappeur selon le K/depart du lanceur adverse.
    Retourne (facteur, label).
    Ex: Glasnow 9.5K → facteur 0.84 → frappeur projete 16% moins de hits.
    """
    if pitcher_k >= 9.0:
        return 0.84, "As (9+ K/dep)"
    if pitcher_k >= 8.5:
        return 0.88, "Elite (8.5+ K/dep)"
    if pitcher_k >= 8.0:
        return 0.92, "Solide (8+ K/dep)"
    if pitcher_k >= 7.0:
        return 0.96, "Correct (7+ K/dep)"
    if pitcher_k >= 6.0:
        return 1.00, "Moyen"
    return 1.05, "Contact"


def _platoon_adj(batter_hand: str, pitcher_hand: str) -> tuple:
    """
    Ajustement splits main dominante (platoon).
    Main opposee = avantage frappeur (~+8% hits).
    Meme main = desavantage (~-8% hits).
    Switch hitter = toujours cote oppose, avantage modere.
    Retourne (facteur, label).
    """
    if not batter_hand or not pitcher_hand:
        return 1.0, ""
    if batter_hand == "S":
        return 1.06, "Switch hitter (avantage platoon)"
    if batter_hand != pitcher_hand:
        return 1.08, f"Platoon avantageux ({batter_hand} vs {pitcher_hand})"
    return 0.92, f"Platoon defavorable ({batter_hand} vs {pitcher_hand})"


# ── MATH ──────────────────────────────────────────────────────────────────────
def _estimate_line(mean: float, stat_key: str) -> float:
    offset = LINE_OFFSET.get(stat_key, 0.5)
    return max(math.floor(mean * 2) / 2 - offset, 0.5)


def _std(mean: float, stat_key: str) -> float:
    floor = STD_FLOOR.get(stat_key, 0.35)
    # Pas de réduction pour les élites: la variance K reste élevée même chez les meilleurs
    # (sortie précoce, mauvais soir, opposition plus forte) → ne pas surestimer les probs
    return max(mean * floor, 0.5)


def _normal_over(mean: float, std: float, line: float) -> float:
    if std <= 0:
        return 99.0 if mean > line else 1.0
    z = (line + 0.5 - mean) / std

    def erf(x):
        sign = 1 if x >= 0 else -1
        x = abs(x)
        t = 1.0 / (1.0 + 0.3275911 * x)
        p = t * (0.254829592 + t * (-0.284496736 + t * (
            1.421413741 + t * (-1.453152027 + t * 1.061405429))))
        return sign * (1.0 - p * math.exp(-x * x))

    prob = (1.0 - erf(z / math.sqrt(2))) / 2.0
    return round(min(max(prob * 100, 1.0), 99.0), 1)


def _edge(prob: float, dk_implied: float = B365_IMPLIED) -> float:
    if dk_implied <= 0:
        return 0.0
    return round((prob - dk_implied) / dk_implied * 100, 1)


def _kelly(prob: float, dk_implied: float = B365_IMPLIED, dk_odds: float = B365_ODDS) -> float:
    b = dk_odds - 1
    if b <= 0:
        return 0.0
    k = ((b * prob / 100) - (1 - prob / 100)) / b / 4 * 100
    return round(max(k, 0.0), 1)


# ── Calibration empirique (Platt linéaire) ────────────────────────────────────
# Refit 2026-08-19 sur 760 bets strikeouts résolus. L'ancienne calibration
# (1.8 + 0.824*p) restait surconfiante de 4 à 14 pts à TOUS les niveaux:
#   prob annoncée 50-55% → WR réelle 46.7%   (n=152)
#   prob annoncée 60-65% → WR réelle 48.1%   (n=135)
#   prob annoncée 65-70% → WR réelle 56.8%   (n=74)
# Résidu mesuré sur la prob déjà calibrée: réel ≈ 13.7 + 0.654 * calibré_ancien.
# Composé avec l'ancienne transformation → réel ≈ 14.9 + 0.539 * brut.
CAL_A = 14.9
CAL_B = 0.539


def _calibrate(prob: float) -> float:
    """Corrige la surconfiance du modèle vers la fréquence réellement observée."""
    return round(max(min(CAL_A + CAL_B * prob, 99.0), 1.0), 1)


def build_k_model(adj_mean: float, pitcher_name: str = "") -> dict:
    """
    Construit LE modele K du lanceur autour de `adj_mean` (lambda_ajuste
    regressee). Tout ce qui affiche ou compare une probabilite K passe ensuite
    par ce modele: badge, ladder, filtre de surprice, edge vs cotes reelles.

    Avant, chaque consommateur rappelait _normal_over(adj_mean, std, line) avec
    ses propres arguments — et _normal_over ajoutait +0.5 a la ligne, donc le
    ladder calculait en realite P(K > k) au lieu de P(K >= k): un decalage d'un
    demi-retrait qui sous-estimait chaque barreau de ~5 points.
    """
    ip_info = None
    if pitcher_name:
        try:
            ip_info = _get_pitcher_ip_starts(pitcher_name)
        except Exception:
            ip_info = None
    ip_info = ip_info or {}
    return KD.build_k_model(adj_mean, ip_info.get("ip_values"), ip_info.get("mean_ip"))


def _k_prob_at_least(model: dict, k: int) -> float:
    """P(K >= k) calibrée, en %."""
    return _calibrate(KD.p_at_least(model, k))


def _k_prob_over(model: dict, line: float) -> float:
    """P(K > line) calibrée, en % — pour une ligne de book (Over 4.5 = K >= 5)."""
    return _calibrate(KD.p_over(model, line))


def _k_curve(model: dict) -> list:
    """
    Génère la courbe de probabilité pour K >= N (N=3 à 10).
    On n'invente PAS les cotes bet365 — elles varient par lanceur.
    L'utilisateur compare nos prob% contre ce qu'il voit sur bet365.
    """
    return [
        {
            "line":    c["line"],      # format Over X.5 pour cohérence backtester
            "k_exact": c["k_exact"],
            "prob":    _calibrate(c["prob"]),
        }
        for c in KD.ladder(model, 3, 10)
    ]


def _attach_odds_to_curve(curve: list, dk_lines: list) -> int:
    """
    Colle sur chaque barreau du ladder la meilleure cote du marche, le book qui
    l'offre, la probabilite no-vig de reference et l'EV.

    Deux grandeurs differentes, volontairement toutes les deux presentes:
      ev_pct   = (notre_prob x meilleure_cote) - 1   → esperance de la mise,
                 c'est ce qu'on affiche sur le barreau;
      edge_pct = (notre_prob - prob_marche) / prob_marche → ecart relatif de
                 probabilites, la grandeur historique sur laquelle MIN_EDGE et
                 les backtests sont calibres. Ne pas confondre les seuils.

    Retourne le nombre de barreaux effectivement cotes (0 → le dashboard
    retombe sur le calculateur manuel).
    """
    by_line = {}
    for c in dk_lines or []:
        line = c.get("line")
        if line is None:
            continue
        try:
            by_line[round(float(line), 1)] = c
        except (TypeError, ValueError):
            continue

    n = 0
    for rung in curve:
        m = by_line.get(round(float(rung["line"]), 1))
        if not m:
            continue
        try:
            odds = float(m.get("over_odds") or 0)
        except (TypeError, ValueError):
            continue
        if odds <= 1.0:
            continue
        market_prob = m.get("over_implied") or 0
        rung.update({
            "best_odds":       round(odds, 3),
            "best_book":       m.get("over_book", ""),
            "market_prob":     round(market_prob, 2),
            "baseline_source": m.get("baseline_source", ""),
            "n_books":         m.get("n_books", 0),
            "ev_pct":          odds_api.ev_pct(rung["prob"], odds),
            "edge_pct":        _edge(rung["prob"], market_prob) if market_prob else 0,
        })
        n += 1
    return n


def _k_best_line(model: dict) -> dict | None:
    """
    Retourne la ligne recommandée quand on n'a PAS les cotes bet365.

    L'ancienne version prenait floor(projection), puis descendait d'une ligne si
    la prob était < 50%. Résultat: elle visait systématiquement la ligne la plus
    facile (prob 60-70%), c.-à-d. exactement celle que le book price 1.30-1.50 —
    injouable, vu que la WR réelle à ce niveau de confiance est ~57%
    (breakeven 1.76). 539 picks générés ainsi depuis le 2026-07-07: WR 51.2%.

    Nouvelle règle: on garde la ligne dont la prob calibrée donne une cote
    équitable >= MIN_ODDS, en préférant la plus proche du plancher (donc la
    prob la plus haute encore jouable). On retourne aussi `min_odds` = la cote
    minimum à exiger chez le book, pour que rien ne soit misé en dessous.
    """
    if model.get("lambda", 0) < 4.0:
        return None
    curve = _k_curve(model)
    max_prob = 100.0 / MIN_ODDS          # prob au-delà de laquelle la cote est trop courte
    playable = [c for c in curve if 0 < c["prob"] <= max_prob]
    if not playable:
        return None
    # La plus haute prob encore sous le plafond = la ligne la plus facile jouable.
    best = max(playable, key=lambda c: c["prob"])
    fair = 100.0 / best["prob"]
    return {
        "line":      best["line"],
        "k_exact":   best["k_exact"],
        "prob":      best["prob"],
        "est_odds":  0,    # inconnu — dépend des vraies cotes bet365
        "dk_implied": 0,
        "kelly":     0,
        "edge":      0,    # calculé par l'utilisateur via le calculateur
        # Cote équitable (aucun profit) et cote minimum à exiger pour du +EV.
        "fair_odds": round(fair, 2),
        "min_odds":  round(max(fair, MIN_ODDS), 2),
    }


def _best_dk_edge(model: dict, dk_lines: list) -> dict | None:
    """
    Parmi les lignes K offertes par DraftKings, retourne celle ou NOTRE edge est
    maximal (notre prob vs prob implicite DK). Permet de ne recommander que la
    vraie valeur et d'enregistrer la cote reelle (profit tracable dans le backtester).
    Retourne {line, our_prob, dk_implied, est_odds, edge_pct, kelly, basis,
    book} ou None.

    `basis` dit si `dk_implied` est une probabilite NO-VIG (les deux faces du
    marche etaient disponibles) ou BRUTE (1/cote, vig incluse). Les deux ne sont
    pas comparables: la brute est plus haute de 2 a 5 points. Sans ce champ, le
    CLV compare une ouverture no-vig a une fermeture brute et sort
    systematiquement negatif.
    """
    best = None
    for c in dk_lines or []:
        line    = c.get("line")
        dk_impl = c.get("over_implied", 0)
        dk_odds = c.get("over_odds", 0)
        if line is None or dk_impl <= 0 or dk_odds <= 0:
            continue
        prob = _k_prob_over(model, line)
        edge = _edge(prob, dk_impl)
        if best is None or edge > best["edge_pct"]:
            src  = c.get("baseline_source", "")
            best = {
                "line":       line,
                "our_prob":   prob,
                "dk_implied": round(dk_impl, 1),
                "est_odds":   round(dk_odds, 3),
                "edge_pct":   edge,
                "kelly":      _kelly(prob, dk_impl, dk_odds),
                "basis":      "brute" if (not src or src.startswith("brute")) else "novig",
                "book":       c.get("over_book", ""),
            }
    return best


def _opp_k_season(opp_team: str, pitcher_hand: str) -> tuple:
    """
    K% saison de l'equipe adverse contre la main du lanceur.
    Retourne (k_pct, source_label). Jamais de fenetre 10 jours seule — voir
    get_team_k_rate_season().
    """
    try:
        d = _get_team_k_rate_season(opp_team, pitcher_hand or None)
    except Exception:
        d = None
    if not d or not d.get("k_pct"):
        return LEAGUE_K_FALLBACK, "defaut"
    return d["k_pct"], d.get("source", "saison")


def _k_projection(mean_k: float, opp_k_rate: float, league_k: float,
                  park_factor: float) -> dict:
    """
    Projection K ajustee.

    Regressee (celle qu'on utilise):
        blend * (K%_adverse / K%_ligue) ** K_REGRESSION_EXP * park_factor
    Brute (l'ancienne, conservee uniquement pour comparaison au dashboard):
        blend * (K%_adverse / K%_ligue)
    """
    lg = league_k if league_k and league_k > 0 else LEAGUE_K_FALLBACK
    ratio = (opp_k_rate / lg) if opp_k_rate and opp_k_rate > 0 else 1.0
    pf    = park_factor if park_factor and park_factor > 0 else 1.0

    mult_raw = ratio
    mult_reg = (ratio ** K_REGRESSION_EXP) * pf
    return {
        "adj":       round(mean_k * mult_reg, 2),
        "adj_raw":   round(mean_k * mult_raw, 2),
        "mult":      round(mult_reg, 4),
        "mult_raw":  round(mult_raw, 4),
        "league_k":  round(lg, 4),
    }


def _park_label(pf: float) -> str:
    if pf >= 1.08:
        return "Tres favorable frappeurs"
    if pf >= 1.04:
        return "Favorable frappeurs"
    if pf <= 0.92:
        return "Tres favorable lanceurs"
    if pf <= 0.96:
        return "Favorable lanceurs"
    return "Neutre"


class MLBPropsAnalyzer:

    def analyze_game(self, game: dict, props_by_market: dict = None) -> dict:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        print(f"  MLB props: {away} @ {home}")

        park_factor = PARK_FACTORS.get(home, 1.00)
        # Moyenne de ligue de la saison en cours (mise en cache par le module)
        try:
            league_k = _get_league_k_rate()
        except Exception:
            league_k = LEAGUE_K_FALLBACK

        # Lookup cotes reelles — plusieurs lignes par joueur/marché
        real_lkp = {}
        if props_by_market:
            for stat_key, market_key in _STAT_TO_MARKET.items():
                for prop in props_by_market.get(market_key, []):
                    pl = prop.get("player", "").lower()
                    real_lkp.setdefault(pl, {}).setdefault(stat_key, []).append(prop)
        use_real = bool(real_lkp)

        # ── Partants probables depuis MLB API officielle ───────────────────────
        try:
            from mlb_starters import fetch_probable_starters, get_starter_for_team, fetch_confirmed_lineups, is_in_lineup, is_on_active_roster
            _mlb_starters = fetch_probable_starters()
            _mlb_lineups  = fetch_confirmed_lineups()
        except Exception:
            _mlb_starters = {}
            _mlb_lineups  = {}
            is_on_active_roster = lambda p, t: True  # fallback: on laisse passer

        batting_team_for = {home: away, away: home}  # opp_team -> batting_team

        def _actual_starter(opp_team: str):
            """
            Identifie le vrai partant de opp_team.
            Priorité 1 — MLB Stats API (partants officiels du jour)
            Priorité 2 — Props Bet365 (inférence depuis les lignes K)
            Priorité 3 — Dict statique MLB_PITCHERS (fallback)
            """
            batting_team = batting_team_for.get(opp_team, "")

            # ── 1. MLB API officielle (source de vérité) ──────────────────────
            if _mlb_starters:
                try:
                    from mlb_starters import get_starter_for_team
                    api_name = get_starter_for_team(opp_team, batting_team, _mlb_starters)
                    if api_name:
                        api_lower = api_name.lower()
                        api_last  = api_lower.split()[-1]
                        # Match par nom dans MLB_PITCHERS (ignore équipe — trades possibles)
                        for known, known_stats in MLB_PITCHERS.items():
                            if (known.lower() == api_lower or
                                    known.lower().split()[-1] == api_last):
                                stats = dict(known_stats)
                                stats["team"] = opp_team  # forcer la bonne équipe
                                # Enrichir avec la ligne B365 si dispo
                                if use_real:
                                    for pl_name, pl_data in real_lkp.items():
                                        if ("strikeouts" in pl_data and
                                                (pl_name == api_lower or
                                                 pl_name.split()[-1] == api_last)):
                                            lines = pl_data["strikeouts"]
                                            mid = lines[len(lines)//2] if lines else {}
                                            stats["strikeouts"] = mid.get("line", stats["strikeouts"])
                                            break
                                print(f"    [MLB API] {api_name} ({opp_team}) {stats['strikeouts']} K/dep")
                                return known, stats
                        # Pas dans le dict — stats synthétiques via ligne B365
                        b365_line = LEAGUE_AVG_K_SP
                        if use_real:
                            for pl_name, pl_data in real_lkp.items():
                                if ("strikeouts" in pl_data and
                                        (pl_name == api_lower or pl_name.split()[-1] == api_last)):
                                    lines = pl_data["strikeouts"]
                                    mid = lines[len(lines)//2] if lines else {}
                                    b365_line = mid.get("line", LEAGUE_AVG_K_SP)
                                    break
                        print(f"    [MLB API] {api_name} (hors dict, {b365_line} K/dep, {opp_team})")
                        return api_name, {"strikeouts": b365_line, "team": opp_team, "hand": "R"}
                except Exception:
                    pass

            # ── 2. Inférence depuis les props Bet365 ──────────────────────────
            if use_real:
                unknown_candidates = []
                for name, data in real_lkp.items():
                    if "strikeouts" not in data:
                        continue
                    last = name.split()[-1]
                    # Lanceur connu de opp_team dans MLB_PITCHERS
                    for known, known_stats in MLB_PITCHERS.items():
                        if (known_stats.get("team", "") == opp_team and
                                (known.lower() == name or known.lower().split()[-1] == last)):
                            return known, known_stats
                    # Pas un lanceur connu de batting_team → candidat pour opp_team
                    is_batting = any(
                        ks.get("team", "") == batting_team and
                        (kn.lower() == name or kn.lower().split()[-1] == last)
                        for kn, ks in MLB_PITCHERS.items()
                    )
                    if not is_batting:
                        lines = data["strikeouts"]
                        mid = lines[len(lines)//2] if lines else {}
                        line = mid.get("line", LEAGUE_AVG_K_SP)
                        unknown_candidates.append((name, line))

                if unknown_candidates:
                    unknown_candidates.sort(key=lambda x: x[1], reverse=True)
                    best_name, best_line = unknown_candidates[0]
                    display = " ".join(w.capitalize() for w in best_name.split())
                    print(f"    [MLB Props] Partant inferé: {display} ({best_line} K/dep, {opp_team})")
                    return display, {"strikeouts": best_line, "team": opp_team, "hand": "R"}

            # ── 3. Partant inconnu — moyenne ligue (evite faux positifs) ─────────
            print(f"    [MLB] Partant {opp_team} inconnu — moyenne ligue utilisee")
            return None, None

        ev_bets = []
        seen    = set()

        # ── Partants confirmés par MLB API (filtre pour bets lanceurs) ────────
        confirmed_starter_lasts = set()
        if _mlb_starters:
            try:
                from mlb_starters import get_starter_for_team
                for tm, op in [(home, away), (away, home)]:
                    n = get_starter_for_team(tm, op, _mlb_starters)
                    if n:
                        confirmed_starter_lasts.add(n.lower().split()[-1])
            except Exception:
                pass

        # ── LANCEURS ─────────────────────────────────────────────────────────
        cfg_k = next(c for c in STAT_CONFIGS if c["key"] == "strikeouts")
        for team, opp in [(home, away), (away, home)]:
            for pitcher in _TEAM_PITCHERS.get(team, []):
                if pitcher in seen:
                    continue
                seen.add(pitcher)
                # Check 1 — Roster actif (même logique que frappeurs — exclut IL/DL)
                try:
                    if not is_on_active_roster(pitcher, team):
                        print(f"    [MLB IL] {pitcher} absent du roster actif {team} — exclu")
                        continue
                except Exception:
                    pass
                # Check 2 — Partant confirmé par MLB API
                if confirmed_starter_lasts:
                    pitcher_lower = pitcher.lower()
                    pitcher_last  = pitcher_lower.split()[-1]
                    if pitcher_last not in confirmed_starter_lasts:
                        continue
                    # Si même nom de famille, vérifier la première initiale (Cody vs A. Morris)
                    if _mlb_starters:
                        try:
                            from mlb_starters import get_starter_for_team as _gst2
                            confirmed_full = _gst2(team, opp, _mlb_starters)
                            if confirmed_full:
                                cf_last = confirmed_full.lower().split()[-1]
                                if cf_last == pitcher_last:
                                    cf_init = confirmed_full.lower().split()[0][0]
                                    p_init  = pitcher_lower.split()[0][0]
                                    if cf_init != p_init:
                                        continue  # mauvais lanceur (ex: Cody vs A. Morris)
                        except Exception:
                            pass

                # Ne pas utiliser la valeur statique du dict — trop souvent obsolète
                # Priorité: rolling stats (MLB API) > ligne DK > skip
                mean_k = None
                rolling_p = None
                dk_k_lines_tmp = []
                if HAS_MLB_ROLLING:
                    rolling_p = _mlb_pitcher_rolling(pitcher)
                    if rolling_p and rolling_p.get("games", 0) >= 2:
                        mean_k = rolling_p["strikeouts"]
                        if rolling_p.get("rolling_avg") and rolling_p.get("season_avg"):
                            context_rolling = (f"Rolling {rolling_p['games']}dep: "
                                               f"{rolling_p['rolling_avg']}K · "
                                               f"Saison: {rolling_p['season_avg']}K · "
                                               f"Blend: {mean_k}K")

                if mean_k is None:
                    # Pas de rolling stats → utiliser la ligne DK médiane comme proxy
                    dk_k_lines_tmp = real_lkp.get(pitcher.lower(), {}).get("strikeouts", [])
                    if not dk_k_lines_tmp:
                        last_tmp = pitcher.lower().split()[-1]
                        for k_, v_ in real_lkp.items():
                            if k_.split()[-1] == last_tmp and "strikeouts" in v_:
                                dk_k_lines_tmp = v_["strikeouts"]
                                break
                    if dk_k_lines_tmp:
                        mid_idx = len(dk_k_lines_tmp) // 2
                        mean_k = dk_k_lines_tmp[mid_idx]["line"]
                    else:
                        print(f"    [MLB Skip] {pitcher}: ni rolling stats ni ligne DK → skip")
                        continue

                if HAS_MLB_ROLLING and rolling_p and rolling_p.get("games", 0) >= 2:
                    print(f"    [MLB Dict] {pitcher}: rolling={mean_k:.1f}K ({rolling_p['games']} dep)")
                elif dk_k_lines_tmp:
                    print(f"    [MLB Dict] {pitcher}: DK line={mean_k:.1f}K (rolling indispo)")

                if mean_k < cfg_k["min_avg"]:
                    print(f"      → Filtré: {mean_k:.1f} < min {cfg_k['min_avg']}")
                    continue

                p_hand = MLB_PITCHERS.get(pitcher, {}).get("hand", "")
                opp_k_rate, opp_k_src = _opp_k_season(opp, p_hand)
                proj       = _k_projection(mean_k, opp_k_rate, league_k, park_factor)
                adj_mean   = proj["adj"]
                adj_raw    = proj["adj_raw"]
                # Modele unique: manches puis K | manches, centre sur adj_mean
                kmodel     = build_k_model(adj_mean, pitcher)
                kmom       = KD.moments(kmodel)
                print(f"    [MLB Ajust] {pitcher}: K% adv {opp_k_rate:.1%} ({opp_k_src}) "
                      f"/ ligue {proj['league_k']:.1%} → régressé x{proj['mult']:.3f} "
                      f"= {adj_mean:.2f}K (brut x{proj['mult_raw']:.3f} = {adj_raw:.2f}K)")

                context = []
                if "context_rolling" in dir():
                    context.append(context_rolling)
                    del context_rolling
                if opp_k_rate > proj["league_k"] + 0.015:
                    context.append(f"Adversaire K% ({opp_k_src}): {opp_k_rate:.1%} (favorable)")
                elif opp_k_rate < proj["league_k"] - 0.015:
                    context.append(f"Adversaire K% ({opp_k_src}): {opp_k_rate:.1%} (difficile)")
                context.append(f"Ajustement régressé x{proj['mult']:.3f} → {adj_mean}K "
                               f"(brut x{proj['mult_raw']:.3f} → {adj_raw}K)")
                context.append(f"Manches: {kmodel['mean_ip']} IP moy ({kmodel['source']}) · "
                               f"{kmodel['rate']:.2f} K/manche · σK {kmom['std']:.2f} "
                               f"(Poisson simple: {kmom['poisson_var'] ** 0.5:.2f})")
                park_lbl = _park_label(park_factor)
                if park_factor != 1.00:
                    context.append(f"Terrain: {park_lbl} (PF {park_factor:.2f})")

                # ── Filtre DK: marché déjà au-dessus de notre projection? ───────
                # Si DK implique prob > notre modèle sur la ligne naturelle → skip
                # (marché a pricé le lanceur correctement, pas de valeur potentielle)
                dk_lines = []
                if use_real:
                    dk_lines = real_lkp.get(pitcher.lower(), {}).get("strikeouts", [])
                    if not dk_lines:
                        last = pitcher.lower().split()[-1]
                        for k, v in real_lkp.items():
                            if k.split()[-1] == last and "strikeouts" in v:
                                dk_lines = v["strikeouts"]
                                break
                    if dk_lines:
                        # Vérifier si la ligne DK la plus proche de notre proj est over-pricée
                        target_line = max(3.5, round(adj_mean - 0.5, 1))
                        closest = min(dk_lines, key=lambda x: abs(x["line"] - target_line))
                        dk_over_impl = closest.get("over_implied", 0)
                        # Même modèle que le ladder et que l'edge (avant, cet
                        # appel-ci sautait la calibration: on comparait une prob
                        # brute à une prob implicite calibrée)
                        our_prob_at_line = _k_prob_over(kmodel, closest["line"])
                        if dk_over_impl > our_prob_at_line + 5:
                            print(f"    [MLB Skip] {pitcher}: DK impl {dk_over_impl:.1f}% > notre prob {our_prob_at_line:.1f}% sur Over {closest['line']} → marché surprice")
                            continue

                # ── Ligne recommandée + edge réel vs cotes DK ───────────────────
                curve = _k_curve(kmodel)
                n_coted = _attach_odds_to_curve(curve, dk_lines)
                curve_str = " | ".join(f"K≥{c['k_exact']}:{c['prob']:.0f}%" for c in curve if 3 <= c["k_exact"] <= 9)
                print(f"    [MLB Courbe] {pitcher}: {curve_str}")
                if n_coted:
                    ev_str = " | ".join(
                        f"K≥{c['k_exact']}:{c['ev_pct']:+.1f}%EV@{c['best_odds']:.2f}({c['best_book'][:4]})"
                        for c in curve if c.get("best_odds"))
                    print(f"    [MLB EV]    {pitcher}: {ev_str}")

                dk_best = _best_dk_edge(kmodel, dk_lines) if use_real else None
                if dk_best is not None:
                    if not (MIN_EDGE <= dk_best["edge_pct"] <= MAX_EDGE):
                        print(f"    [MLB Skip] {pitcher}: edge réel {dk_best['edge_pct']:.1f}% hors [{MIN_EDGE},{MAX_EDGE}] (pas de valeur fiable)")
                        continue
                    if dk_best["est_odds"] < MIN_ODDS:
                        print(f"    [MLB Skip] {pitcher}: cote {dk_best['est_odds']:.2f} < plancher {MIN_ODDS} (ROI négatif mesuré sous 1.85)")
                        continue
                    rec_line, our_prob = dk_best["line"], dk_best["our_prob"]
                    edge_pct, kelly_v  = dk_best["edge_pct"], dk_best["kelly"]
                    est_odds_v, dk_impl_v = dk_best["est_odds"], dk_best["dk_implied"]
                    basis_v, book_v = dk_best["basis"], dk_best["book"]
                    min_odds_v = max(round(100.0 / our_prob, 2), MIN_ODDS) if our_prob else MIN_ODDS
                    print(f"    [MLB BET]   {pitcher}: Over {rec_line} @ {est_odds_v:.2f} ({book_v}) — "
                          f"prob {our_prob:.0f}% vs marche {dk_impl_v:.0f}% [{basis_v}] → edge {edge_pct:.1f}%")
                else:
                    # Pas de cote DK → projection seule (calculateur manuel), pas comptée comme valeur
                    best = _k_best_line(kmodel)
                    if best is None:
                        print(f"    [MLB Skip] {pitcher}: proj={adj_mean:.1f}K — aucune ligne jouable au-dessus de {MIN_ODDS}")
                        continue
                    rec_line, our_prob = best["line"], best["prob"]
                    edge_pct, kelly_v, est_odds_v, dk_impl_v = 0, 0, 0, 0
                    basis_v, book_v = "", ""
                    min_odds_v = best["min_odds"]
                    print(f"    [MLB PROJ]  {pitcher}: Over {rec_line} proj {adj_mean:.1f}K — exiger >= {min_odds_v:.2f} (pas de cote DK)")

                ev_bets.append({
                    "player":        pitcher,
                    "team":          team,
                    "opponent":      opp,
                    "player_type":   "pitcher",
                    "market":        f"{cfg_k['label']} Over {rec_line}",
                    "stat_key":      "strikeouts",
                    "line":          rec_line,
                    "season_avg":    mean_k,
                    "adj_proj":      adj_mean,
                    "adj_proj_raw":  adj_raw,
                    "adj_mult":      proj["mult"],
                    "adj_mult_raw":  proj["mult_raw"],
                    "opp_k_rate":    round(opp_k_rate * 100, 1),
                    "opp_k_source":  opp_k_src,
                    "league_k_rate": round(proj["league_k"] * 100, 1),
                    "ip_mean":       kmodel["mean_ip"],
                    "k_rate_per_ip": kmodel["rate"],
                    "k_std":         kmom["std"],
                    "k_model":       kmodel["source"],
                    "park_factor":   park_factor,
                    "our_prob":      our_prob,
                    "edge_pct":      edge_pct,
                    "kelly":         kelly_v,
                    "min_odds":      min_odds_v,   # ne jamais miser sous cette cote
                    "est_odds":      est_odds_v,
                    "dk_implied":    dk_impl_v,
                    # "novig" ou "brute": voir _best_dk_edge. Le CLV doit
                    # comparer deux probabilites de la meme base.
                    "dk_implied_basis": basis_v,
                    "dk_book":       book_v,
                    "k_curve":       curve,   # courbe complète pour affichage frontend
                    # 0 barreau coté → le dashboard affiche le calculateur manuel
                    "odds_rungs":    n_coted,
                    "context":       context,
                })

        # ── LANCEURS HORS DICT ────────────────────────────────────────────────
        # Partants confirmés non présents dans MLB_PITCHERS (Schlittler, Martin, etc.)
        # Utilise la ligne DK comme projection K + mode synthétique b365
        if use_real and _mlb_starters:
            try:
                from mlb_starters import get_starter_for_team as _gst
                for team, opp in [(home, away), (away, home)]:
                    api_name = _gst(team, opp, _mlb_starters)
                    if not api_name:
                        continue
                    api_lower = api_name.lower()
                    api_last  = api_lower.split()[-1]
                    if api_name in seen or api_lower in seen:
                        continue
                    # Skip si déjà dans le dict (analysé dans la boucle précédente)
                    if any(kn.lower() == api_lower or kn.lower().split()[-1] == api_last
                           for kn in MLB_PITCHERS):
                        continue
                    # Lignes K DK disponibles pour ce partant
                    dk_lines = real_lkp.get(api_lower, {}).get("strikeouts", [])
                    if not dk_lines:
                        for pl_name, pl_data in real_lkp.items():
                            if "strikeouts" in pl_data and pl_name.split()[-1] == api_last:
                                dk_lines = pl_data["strikeouts"]
                                break

                    seen.add(api_name)
                    display = " ".join(w.capitalize() for w in api_name.split())

                    # Projection: rolling stats en priorité, puis ligne DK médiane, puis skip
                    mean_k = None
                    if HAS_MLB_ROLLING:
                        try:
                            rp_rolling = _mlb_pitcher_rolling(display)
                            if rp_rolling and rp_rolling.get("games", 0) >= 2:
                                mean_k = rp_rolling["strikeouts"]
                                dk_ref = dk_lines[len(dk_lines)//2]["line"] if dk_lines else "N/A"
                                print(f"      Rolling {display}: {mean_k} K/dep (DK ref: {dk_ref})")
                        except Exception:
                            pass
                    if mean_k is None and dk_lines:
                        mean_k = dk_lines[len(dk_lines)//2]["line"]  # ligne médiane DK comme proxy
                    if mean_k is None:
                        continue  # aucune donnée — skip

                    if mean_k < cfg_k["min_avg"]:
                        continue
                    try:
                        if not is_on_active_roster(api_name, team):
                            continue
                    except Exception:
                        pass
                    # Main du lanceur inconnue du dict → MLB API (people/{id})
                    try:
                        p_hand = _get_pitcher_hand(display) or ""
                    except Exception:
                        p_hand = ""
                    opp_k_rate, opp_k_src = _opp_k_season(opp, p_hand)
                    proj       = _k_projection(mean_k, opp_k_rate, league_k, park_factor)
                    adj_mean   = proj["adj"]
                    adj_raw    = proj["adj_raw"]
                    kmodel     = build_k_model(adj_mean, display)
                    kmom       = KD.moments(kmodel)
                    print(f"    [MLB Ajust] {display}: K% adv {opp_k_rate:.1%} ({opp_k_src}) "
                          f"/ ligue {proj['league_k']:.1%} → régressé x{proj['mult']:.3f} "
                          f"= {adj_mean:.2f}K (brut x{proj['mult_raw']:.3f} = {adj_raw:.2f}K)")
                    context    = []
                    if opp_k_rate > proj["league_k"] + 0.015:
                        context.append(f"Adversaire K% ({opp_k_src}): {opp_k_rate:.1%} (favorable)")
                    elif opp_k_rate < proj["league_k"] - 0.015:
                        context.append(f"Adversaire K% ({opp_k_src}): {opp_k_rate:.1%} (difficile)")
                    context.append(f"Ajustement régressé x{proj['mult']:.3f} → {adj_mean}K "
                                   f"(brut x{proj['mult_raw']:.3f} → {adj_raw}K)")
                    context.append(f"Manches: {kmodel['mean_ip']} IP moy ({kmodel['source']}) · "
                                   f"{kmodel['rate']:.2f} K/manche · σK {kmom['std']:.2f} "
                                   f"(Poisson simple: {kmom['poisson_var'] ** 0.5:.2f})")
                    park_lbl = _park_label(park_factor)
                    if park_factor != 1.00:
                        context.append(f"Terrain: {park_lbl} (PF {park_factor:.2f})")
                    # Ligne recommandée + edge réel vs cotes DK
                    curve = _k_curve(kmodel)
                    n_coted = _attach_odds_to_curve(curve, dk_lines)
                    dk_best = _best_dk_edge(kmodel, dk_lines)
                    if dk_best is not None:
                        if not (MIN_EDGE <= dk_best["edge_pct"] <= MAX_EDGE):
                            print(f"    [MLB Hors Dict Skip] {display}: edge réel {dk_best['edge_pct']:.1f}% hors [{MIN_EDGE},{MAX_EDGE}]")
                            continue
                        if dk_best["est_odds"] < MIN_ODDS:
                            print(f"    [MLB Hors Dict Skip] {display}: cote {dk_best['est_odds']:.2f} < plancher {MIN_ODDS}")
                            continue
                        rec_line, our_prob = dk_best["line"], dk_best["our_prob"]
                        edge_pct, kelly_v  = dk_best["edge_pct"], dk_best["kelly"]
                        est_odds_v, dk_impl_v = dk_best["est_odds"], dk_best["dk_implied"]
                        basis_v, book_v = dk_best["basis"], dk_best["book"]
                        min_odds_v = max(round(100.0 / our_prob, 2), MIN_ODDS) if our_prob else MIN_ODDS
                        print(f"    [MLB Hors Dict BET] {display}: Over {rec_line} @ {est_odds_v:.2f} — prob {our_prob:.0f}% vs DK {dk_impl_v:.0f}% → edge {edge_pct:.1f}%")
                    else:
                        best = _k_best_line(kmodel)
                        if best is None:
                            continue
                        rec_line, our_prob = best["line"], best["prob"]
                        edge_pct, kelly_v, est_odds_v, dk_impl_v = 0, 0, 0, 0
                        basis_v, book_v = "", ""
                        min_odds_v = best["min_odds"]
                        print(f"    [MLB Hors Dict PROJ] {display}: Over {rec_line} proj {adj_mean:.1f} — exiger >= {min_odds_v:.2f}")
                    ev_bets.append({
                        "player": display, "team": team, "opponent": opp,
                        "player_type": "pitcher",
                        "market": f"{cfg_k['label']} Over {rec_line}",
                        "stat_key": "strikeouts", "line": rec_line,
                        "season_avg": mean_k, "adj_proj": adj_mean,
                        "adj_proj_raw": adj_raw,
                        "adj_mult": proj["mult"], "adj_mult_raw": proj["mult_raw"],
                        "opp_k_rate": round(opp_k_rate * 100, 1),
                        "opp_k_source": opp_k_src,
                        "league_k_rate": round(proj["league_k"] * 100, 1),
                        "ip_mean": kmodel["mean_ip"], "k_rate_per_ip": kmodel["rate"],
                        "k_std": kmom["std"], "k_model": kmodel["source"],
                        "park_factor": park_factor, "our_prob": our_prob,
                        "edge_pct": edge_pct,
                        "kelly": kelly_v,
                        "min_odds": min_odds_v,
                        "est_odds": est_odds_v, "dk_implied": dk_impl_v,
                        "dk_implied_basis": basis_v, "dk_book": book_v,
                        "k_curve": curve, "odds_rungs": n_coted,
                        "context": context,
                    })
            except Exception as e:
                print(f"  [MLB Hors Dict] Erreur: {e}")

        # ── FRAPPEURS ─────────────────────────────────────────────────────────
        for team, opp in [(home, away), (away, home)]:
            # Lanceur adverse le plus fort connu
            opp_pitcher_name, opp_pitcher_stats = _actual_starter(opp)
            opp_k     = opp_pitcher_stats["strikeouts"] if opp_pitcher_stats else LEAGUE_AVG_K_SP
            opp_hand  = opp_pitcher_stats.get("hand", "") if opp_pitcher_stats else ""
            pitch_adj, pitch_lbl = _pitcher_difficulty_adj(opp_k)

            for batter in _TEAM_BATTERS.get(team, []):
                if batter in seen:
                    continue
                seen.add(batter)
                # Check 1 — Roster actif: exclut les joueurs sur IL, DL, blessés
                # C'est la source de vérité la plus fiable, indépendante du lineup
                try:
                    if not is_on_active_roster(batter, team):
                        print(f"    [MLB IL] {batter} absent du roster actif {team} — exclu")
                        continue
                except Exception:
                    pass
                # Check 2 — Lineup confirmé du jour (si disponible)
                try:
                    if _mlb_lineups and not is_in_lineup(batter, team, _mlb_lineups):
                        print(f"    [MLB Lineup] {batter} absent du lineup {team} — exclu")
                        continue
                except Exception:
                    pass
                stats       = dict(MLB_BATTERS.get(batter, {}))
                batter_hand = stats.get("bats", "")

                # Remplacer par stats rolling si disponibles (N derniers matchs)
                if HAS_MLB_ROLLING:
                    rolling_b = _mlb_batter_rolling(batter)
                    if rolling_b and rolling_b.get("games", 0) >= 3:
                        if rolling_b.get("hits") is not None:
                            stats["hits"]        = rolling_b["hits"]
                        if rolling_b.get("total_bases") is not None:
                            stats["total_bases"] = rolling_b["total_bases"]
                        if rolling_b.get("home_runs") is not None:
                            stats["home_runs"]   = rolling_b["home_runs"]

                plat_adj, plat_lbl = _platoon_adj(batter_hand, opp_hand)

                for cfg in STAT_CONFIGS:
                    if cfg["player_type"] != "batter":
                        continue
                    key  = cfg["key"]
                    mean = stats.get(key, 0.0)
                    if mean < cfg["min_avg"]:
                        continue

                    # ── Filtre convergence: forme rolling + contexte ──────────
                    if HAS_MLB_ROLLING and rolling_b and rolling_b.get("games", 0) >= 3:
                        rolling_val = rolling_b.get(key, 0)
                        if rolling_val and rolling_val < cfg["min_avg"]:
                            continue  # Forme récente sous le seuil → forme contredit le pari
                    # Convergence requise selon le type de marché
                    # hits/total_bases: 2 signaux (lanceur ET platoon) — marché compétitif
                    # HR/runs: 1 signal suffit — contexte (parc, lanceur) plus déterminant
                    required_conv = cfg.get("convergence", 1)
                    conv = 0
                    if pitch_adj >= 1.0: conv += 1
                    if plat_adj >= 1.06: conv += 1
                    if conv < required_conv:
                        continue

                    # Projection ajustee: lanceur adverse + platoon + park factor (HR surtout)
                    park_mult = park_factor if key == "home_runs" else (1.0 + (park_factor - 1.0) * 0.5)
                    adj_mean = round(mean * pitch_adj * plat_adj * park_mult, 3)
                    std      = _std(adj_mean, key)

                    context = []
                    if opp_pitcher_name:
                        context.append(f"vs {opp_pitcher_name} ({opp_k} K/dep) — {pitch_lbl}")
                    if plat_lbl:
                        context.append(plat_lbl)
                    park_lbl = _park_label(park_factor)
                    if park_factor != 1.00:
                        context.append(f"Terrain: {park_lbl} (PF {park_factor:.2f})")
                    context.append("Confirmer lineup avant de parier")

                    rp_list = []
                    if use_real:
                        rp_list = real_lkp.get(batter.lower(), {}).get(key, [])
                        if not rp_list:
                            last = batter.lower().split()[-1]
                            for k, v in real_lkp.items():
                                if k.split()[-1] == last and key in v:
                                    rp_list = v[key]
                                    break
                        if not rp_list:
                            continue
                    else:
                        rp_list = [{"line": _estimate_line(adj_mean, key),
                                    "over_odds": B365_ODDS, "over_implied": B365_IMPLIED}]

                    found_bet = False
                    for rp_entry in rp_list:
                        line    = rp_entry["line"]
                        dk_impl = rp_entry["over_implied"]
                        dk_odds = rp_entry["over_odds"]

                        prob  = _normal_over(adj_mean, std, line)
                        edge  = _edge(prob, dk_impl)
                        ratio = (prob / dk_impl) if dk_impl > 0 else 0

                        if not (MIN_EDGE <= edge <= MAX_EDGE):
                            continue
                        if ratio > MAX_DISAGREEMENT_RATIO:
                            continue
                        if dk_odds < MIN_ODDS:
                            continue
                        ev_bets.append({
                            "player":        batter,
                            "team":          team,
                            "opponent":      opp,
                            "player_type":   "batter",
                            "market":        f"{cfg['label']} Over {line}",
                            "stat_key":      key,
                            "line":          line,
                            "season_avg":    mean,
                            "adj_proj":      adj_mean,
                            "opp_k_rate":    None,
                            "opp_pitcher":   opp_pitcher_name,
                            "opp_pitcher_k": opp_k,
                            "platoon":       plat_lbl,
                            "park_factor":   park_factor,
                            "our_prob":      prob,
                            "edge_pct":      edge,
                            "kelly":         _kelly(prob, dk_impl, dk_odds),
                            "est_odds":      dk_odds,
                            "dk_implied":    round(dk_impl, 1),
                            "context":       context,
                        })

        ev_bets.sort(key=lambda x: x["edge_pct"], reverse=True)
        ev_bets = ev_bets[:MAX_BETS]

        print(f"    -> {len(ev_bets)} bets MLB +EV")
        # event_id: sans lui la capture CLV ne peut pas retrouver le match
        # dans The Odds API (c'etait la cause de 0 CLV capte sur 1267 bets).
        return {"event_id": game.get("event_id", ""),
                "home_team": home, "away_team": away, "bets": ev_bets}
