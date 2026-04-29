"""
NBA Props Analyzer v4 - Stats 2024-25 hardcodees
Blessures longues durees retirées de la liste
"""

import math

STD_FLOOR = {
    "pts":  0.22,
    "reb":  0.30,
    "ast":  0.35,
    "fg3m": 0.45,
    "pra":  0.20,  # PRA = pts+reb+ast, variance relative plus basse
}

LINE_OFFSET = {
    "pts":  1.5,
    "reb":  1.0,
    "ast":  1.0,
    "fg3m": 0.5,
    "pra":  2.0,
}

STAT_CONFIGS = [
    # pts: re-active avec facteur DEF par equipe (version sans DEF avait 34.8% WR)
    # Avec ajustement defensif (pts autorises/match), modele nettement plus precis
    {"key": "pts",  "label": "Points",      "min_avg": 20.0},  # seulement superstar / star
    {"key": "reb",  "label": "Rebonds",     "min_avg": 5.0},   # 70% WR historique
    {"key": "ast",  "label": "Passes",      "min_avg": 4.0},   # 67% WR historique
    {"key": "pra",  "label": "Pts+Reb+Ast", "min_avg": 25.0},  # PRA combine
]

MIN_EDGE   = 8.0   # Abaisse de 10 — avec facteur DEF calibre, 8% edge est rentable
MAX_EDGE   = 18.0
DK_IMPLIED = 53.49
DK_ODDS    = 1.870
MAX_BETS   = 4
# Si notre modele est >20% plus optimiste que DK, skip — le marche connait mieux
MAX_DISAGREEMENT_RATIO = 1.20

# ── FACTEURS DEFENSIFS NBA PAR EQUIPE ────────────────────────────────────────
# Rebonds accordes par match (plus = plus facile pour rebondeur adverse)
NBA_DEF_REB_ALLOWED = {
    "Oklahoma City Thunder": 41.2, "Cleveland Cavaliers": 42.5,
    "Boston Celtics": 43.0,        "Miami Heat": 43.5,
    "New York Knicks": 43.8,       "Denver Nuggets": 44.0,
    "Minnesota Timberwolves": 44.2,"Indiana Pacers": 44.5,
    "Los Angeles Lakers": 44.5,    "LA Clippers": 44.8,
    "Philadelphia 76ers": 44.8,    "Atlanta Hawks": 45.0,
    "Golden State Warriors": 45.2, "Phoenix Suns": 45.5,
    "Chicago Bulls": 45.5,         "Dallas Mavericks": 45.5,
    "Milwaukee Bucks": 45.8,       "Sacramento Kings": 46.0,
    "Houston Rockets": 46.0,       "San Antonio Spurs": 46.2,
    "Memphis Grizzlies": 46.5,     "New Orleans Pelicans": 46.5,
    "Detroit Pistons": 46.8,       "Washington Wizards": 47.0,
    "Charlotte Hornets": 47.0,     "Toronto Raptors": 47.2,
    "Portland Trail Blazers": 47.5,"Orlando Magic": 47.5,
    "Brooklyn Nets": 47.8,         "Utah Jazz": 48.5,
}
LEAGUE_AVG_DEF_REB = 44.5

# ── FACTEUR DEFENSIF POINTS ACCORDES / MATCH ─────────────────────────────────
# Source: NBA Stats 2024-25 (defensive rating / pts autorises par match)
# Plus la valeur est haute = defense poreuse = plus facile pour le scoreur adverse
NBA_DEF_PTS_ALLOWED = {
    "Oklahoma City Thunder":    103.5,
    "Cleveland Cavaliers":      104.8,
    "Minnesota Timberwolves":   105.5,
    "Boston Celtics":           106.8,
    "New York Knicks":          108.5,
    "Miami Heat":               109.2,
    "Denver Nuggets":           109.5,
    "Indiana Pacers":           111.0,
    "Memphis Grizzlies":        111.5,
    "Golden State Warriors":    112.0,
    "Los Angeles Lakers":       112.5,
    "LA Clippers":              113.0,
    "Milwaukee Bucks":          113.5,
    "Philadelphia 76ers":       114.0,
    "Dallas Mavericks":         114.0,
    "Houston Rockets":          114.5,
    "Phoenix Suns":             115.0,
    "Sacramento Kings":         115.5,
    "Atlanta Hawks":            116.0,
    "Chicago Bulls":            116.5,
    "San Antonio Spurs":        117.0,
    "Portland Trail Blazers":   117.5,
    "Detroit Pistons":          118.0,
    "New Orleans Pelicans":     118.5,
    "Washington Wizards":       119.0,
    "Charlotte Hornets":        119.5,
    "Toronto Raptors":          120.0,
    "Orlando Magic":            120.5,
    "Brooklyn Nets":            121.0,
    "Utah Jazz":                122.5,
}
LEAGUE_AVG_DEF_PTS = 113.5

# Passes accordees par match (plus = plus facile pour meneur adverse)
NBA_DEF_AST_ALLOWED = {
    "Oklahoma City Thunder": 23.0, "Boston Celtics": 23.5,
    "Minnesota Timberwolves": 24.0,"Cleveland Cavaliers": 24.0,
    "New York Knicks": 24.5,       "Miami Heat": 25.0,
    "Denver Nuggets": 25.0,        "Indiana Pacers": 25.5,
    "Memphis Grizzlies": 25.8,     "Golden State Warriors": 26.0,
    "Los Angeles Lakers": 26.0,    "LA Clippers": 26.0,
    "Dallas Mavericks": 26.2,      "Houston Rockets": 26.5,
    "Milwaukee Bucks": 26.5,       "Philadelphia 76ers": 26.8,
    "Phoenix Suns": 27.0,          "Sacramento Kings": 27.0,
    "Atlanta Hawks": 27.2,         "Chicago Bulls": 27.5,
    "San Antonio Spurs": 27.5,     "Portland Trail Blazers": 27.8,
    "New Orleans Pelicans": 27.8,  "Detroit Pistons": 28.0,
    "Washington Wizards": 28.2,    "Charlotte Hornets": 28.5,
    "Toronto Raptors": 28.5,       "Orlando Magic": 28.8,
    "Brooklyn Nets": 29.0,         "Utah Jazz": 29.5,
}
LEAGUE_AVG_DEF_AST = 26.5

# Mapping stat key -> market key The Odds API
_STAT_TO_MARKET = {
    "pts":  "player_points",
    "reb":  "player_rebounds",
    "ast":  "player_assists",
    "fg3m": "player_threes",
    "pra":  "player_points_rebounds_assists",
}

# ── BLESSURES NBA CONNUES ─────────────────────────────────────────────────────
# Mettre a jour manuellement quand un joueur est blesse ou revient
NBA_KNOWN_INJURED = {
    "bradley beal",        # PHX - blessure longue duree
    "kawhi leonard",       # LAC - gestion charge
    "paul george",         # PHI - blessure
    "joel embiid",         # PHI - blessure genou
    "zion williamson",     # NOP - blessure
    "ja morant",           # MEM - suspension/blessure
    "jimmy butler",        # MIA - blessure
    "kristaps porzingis",  # BOS - blessure
    "stephen curry",       # GSW - blessure
    "klay thompson",       # DAL - blessure
    "damian lillard",      # MIL - blessure
    "brandon ingram",      # NOP - blessure
    "lonzo ball",          # CHI - blessure longue duree
    "ben simmons",         # BKN - blessure
}
# ─────────────────────────────────────────────────────────────────────────────

# Stats 2024-25 saison reguliere — seulement joueurs actifs et en sante
NBA_PLAYER_STATS = {
    # Boston Celtics
    "Jayson Tatum":            {"pts": 26.9, "reb": 8.1, "ast": 5.2, "fg3m": 3.1},
    "Jaylen Brown":            {"pts": 23.7, "reb": 5.6, "ast": 3.6, "fg3m": 2.8},
    "Payton Pritchard":        {"pts": 15.6, "reb": 3.2, "ast": 3.9, "fg3m": 3.2},
    "Jrue Holiday":            {"pts": 12.8, "reb": 5.3, "ast": 4.4, "fg3m": 1.8},
    "Al Horford":              {"pts": 9.5,  "reb": 6.5, "ast": 2.5, "fg3m": 1.8},
    # New York Knicks
    "Jalen Brunson":           {"pts": 25.1, "reb": 3.3, "ast": 6.7, "fg3m": 2.9},
    "Karl-Anthony Towns":      {"pts": 24.2, "reb": 13.9, "ast": 3.1, "fg3m": 2.8},
    "Mikal Bridges":           {"pts": 13.8, "reb": 4.2, "ast": 3.2, "fg3m": 2.1},
    "OG Anunoby":              {"pts": 14.9, "reb": 4.5, "ast": 1.7, "fg3m": 2.3},
    "Josh Hart":               {"pts": 12.1, "reb": 8.5, "ast": 4.5, "fg3m": 1.1},
    # Milwaukee Bucks
    "Giannis Antetokounmpo":   {"pts": 30.4, "reb": 11.9, "ast": 6.5, "fg3m": 0.9},
    "Brook Lopez":             {"pts": 13.9, "reb": 5.3,  "ast": 1.4, "fg3m": 2.2},
    "Bobby Portis":            {"pts": 11.2, "reb": 7.4,  "ast": 1.2, "fg3m": 1.1},
    "Khris Middleton":         {"pts": 12.0, "reb": 4.2,  "ast": 3.5, "fg3m": 1.8},
    # Cleveland Cavaliers
    "Donovan Mitchell":        {"pts": 26.0, "reb": 5.0, "ast": 5.5, "fg3m": 3.1},
    "Darius Garland":          {"pts": 20.6, "reb": 3.3, "ast": 6.7, "fg3m": 2.5},
    "Evan Mobley":             {"pts": 18.1, "reb": 9.4, "ast": 2.9, "fg3m": 1.1},
    "Jarrett Allen":           {"pts": 13.7, "reb": 10.7, "ast": 1.5, "fg3m": 0.0},
    "Max Strus":               {"pts": 11.4, "reb": 4.6,  "ast": 2.5, "fg3m": 2.5},
    # Indiana Pacers
    "Tyrese Haliburton":       {"pts": 20.1, "reb": 4.2, "ast": 10.9, "fg3m": 2.7},
    "Pascal Siakam":           {"pts": 23.9, "reb": 7.5,  "ast": 3.8, "fg3m": 1.3},
    "Myles Turner":            {"pts": 15.5, "reb": 6.9,  "ast": 1.6, "fg3m": 2.1},
    "Bennedict Mathurin":      {"pts": 17.3, "reb": 4.9,  "ast": 2.1, "fg3m": 2.2},
    "Andrew Nembhard":         {"pts": 12.0, "reb": 3.9,  "ast": 5.3, "fg3m": 1.7},
    # Orlando Magic
    "Paolo Banchero":          {"pts": 24.6, "reb": 8.0, "ast": 5.6, "fg3m": 1.9},
    "Franz Wagner":            {"pts": 23.3, "reb": 5.3, "ast": 3.8, "fg3m": 1.9},
    "Jalen Suggs":             {"pts": 14.0, "reb": 4.3, "ast": 5.3, "fg3m": 2.2},
    "Cole Anthony":            {"pts": 13.5, "reb": 4.0, "ast": 4.5, "fg3m": 2.1},
    # Miami Heat
    "Bam Adebayo":             {"pts": 22.0, "reb": 10.9, "ast": 4.1, "fg3m": 0.4},
    "Tyler Herro":             {"pts": 24.5, "reb": 5.2,  "ast": 5.3, "fg3m": 3.2},
    "Terry Rozier":            {"pts": 14.4, "reb": 3.7,  "ast": 4.4, "fg3m": 2.4},
    "Duncan Robinson":         {"pts": 13.7, "reb": 3.5,  "ast": 2.1, "fg3m": 3.3},
    # Philadelphia 76ers
    "Tyrese Maxey":            {"pts": 26.4, "reb": 3.9, "ast": 6.6, "fg3m": 3.0},
    "Kelly Oubre Jr.":         {"pts": 15.1, "reb": 5.0, "ast": 1.8, "fg3m": 2.1},
    "Tobias Harris":           {"pts": 14.5, "reb": 6.2, "ast": 2.5, "fg3m": 1.5},
    # Chicago Bulls
    "Zach LaVine":             {"pts": 22.5, "reb": 5.0, "ast": 4.5, "fg3m": 3.0},
    "Nikola Vucevic":          {"pts": 21.0, "reb": 10.9, "ast": 3.2, "fg3m": 1.6},
    "Coby White":              {"pts": 19.1, "reb": 3.9,  "ast": 4.5, "fg3m": 3.4},
    # Atlanta Hawks
    "Trae Young":              {"pts": 23.6, "reb": 3.0,  "ast": 11.5, "fg3m": 2.5},
    "Dejounte Murray":         {"pts": 22.5, "reb": 5.5,  "ast": 6.2,  "fg3m": 1.6},
    "Clint Capela":            {"pts": 12.0, "reb": 11.9, "ast": 1.0,  "fg3m": 0.0},
    "De'Andre Hunter":         {"pts": 16.0, "reb": 4.0,  "ast": 2.2,  "fg3m": 2.4},
    # Toronto Raptors
    "Scottie Barnes":          {"pts": 20.0, "reb": 8.2, "ast": 5.6, "fg3m": 1.3},
    "RJ Barrett":              {"pts": 22.4, "reb": 5.6, "ast": 3.4, "fg3m": 2.5},
    "Immanuel Quickley":       {"pts": 17.4, "reb": 4.8, "ast": 6.8, "fg3m": 2.6},
    "Jakob Poeltl":            {"pts": 12.5, "reb": 9.8, "ast": 3.2, "fg3m": 0.0},
    "Gradey Dick":             {"pts": 11.0, "reb": 3.5, "ast": 1.5, "fg3m": 2.2},
    # Charlotte Hornets
    "LaMelo Ball":             {"pts": 27.5, "reb": 5.9, "ast": 8.6, "fg3m": 3.3},
    "Brandon Miller":          {"pts": 17.3, "reb": 4.7, "ast": 1.8, "fg3m": 2.7},
    "Miles Bridges":           {"pts": 21.5, "reb": 6.9, "ast": 3.1, "fg3m": 2.0},
    "Mark Williams":           {"pts": 10.5, "reb": 9.5, "ast": 1.2, "fg3m": 0.0},
    # Oklahoma City Thunder
    "Shai Gilgeous-Alexander": {"pts": 32.7, "reb": 5.5, "ast": 6.4, "fg3m": 1.9},
    "Jalen Williams":          {"pts": 22.5, "reb": 4.5, "ast": 5.9, "fg3m": 1.9},
    "Chet Holmgren":           {"pts": 19.0, "reb": 7.9, "ast": 2.1, "fg3m": 2.2},
    "Luguentz Dort":           {"pts": 14.6, "reb": 4.7, "ast": 1.8, "fg3m": 2.5},
    "Isaiah Hartenstein":      {"pts": 10.5, "reb": 9.5, "ast": 3.2, "fg3m": 0.0},
    # Denver Nuggets
    "Nikola Jokic":            {"pts": 29.6, "reb": 12.7, "ast": 10.2, "fg3m": 0.8},
    "Jamal Murray":            {"pts": 18.8, "reb": 4.4,  "ast": 6.5,  "fg3m": 2.5},
    "Michael Porter Jr.":      {"pts": 17.3, "reb": 6.4,  "ast": 1.5,  "fg3m": 2.9},
    "Aaron Gordon":            {"pts": 13.8, "reb": 6.7,  "ast": 3.2,  "fg3m": 1.2},
    "Russell Westbrook":       {"pts": 11.0, "reb": 5.5,  "ast": 6.5,  "fg3m": 0.8},
    # Minnesota Timberwolves
    "Anthony Edwards":         {"pts": 27.1, "reb": 5.4, "ast": 5.2, "fg3m": 3.2},
    "Rudy Gobert":             {"pts": 13.8, "reb": 12.8, "ast": 1.7, "fg3m": 0.0},
    "Mike Conley":             {"pts": 9.6,  "reb": 2.9,  "ast": 5.9, "fg3m": 2.0},
    "Jaden McDaniels":         {"pts": 14.6, "reb": 4.9,  "ast": 1.6, "fg3m": 2.0},
    "Naz Reid":                {"pts": 13.7, "reb": 5.7,  "ast": 1.6, "fg3m": 1.8},
    # Golden State Warriors
    "Andrew Wiggins":          {"pts": 17.1, "reb": 4.6, "ast": 2.2, "fg3m": 2.4},
    "Jonathan Kuminga":        {"pts": 16.1, "reb": 4.5, "ast": 2.1, "fg3m": 1.0},
    "Draymond Green":          {"pts": 9.0,  "reb": 7.3, "ast": 6.4, "fg3m": 0.3},
    "Moses Moody":             {"pts": 12.0, "reb": 3.5, "ast": 1.8, "fg3m": 2.3},
    # Los Angeles Lakers
    "LeBron James":            {"pts": 23.7, "reb": 8.3, "ast": 9.0, "fg3m": 1.7},
    "Anthony Davis":           {"pts": 25.7, "reb": 12.5, "ast": 3.5, "fg3m": 0.6},
    "Austin Reaves":           {"pts": 15.9, "reb": 4.2,  "ast": 5.0, "fg3m": 2.5},
    "D'Angelo Russell":        {"pts": 13.4, "reb": 2.9,  "ast": 5.6, "fg3m": 2.3},
    "Rui Hachimura":           {"pts": 12.9, "reb": 4.0,  "ast": 1.3, "fg3m": 1.4},
    # LA Clippers
    "James Harden":            {"pts": 20.7, "reb": 5.3, "ast": 8.5, "fg3m": 3.2},
    "Norman Powell":           {"pts": 23.8, "reb": 3.6, "ast": 2.0, "fg3m": 3.1},
    "Ivica Zubac":             {"pts": 11.4, "reb": 10.4, "ast": 2.0, "fg3m": 0.0},
    "Derrick Jones Jr.":       {"pts": 10.5, "reb": 4.5,  "ast": 1.8, "fg3m": 1.2},
    # Phoenix Suns
    "Kevin Durant":            {"pts": 27.1, "reb": 6.3, "ast": 4.0, "fg3m": 1.8},
    "Devin Booker":            {"pts": 25.2, "reb": 4.5, "ast": 6.9, "fg3m": 3.0},
    "Jusuf Nurkic":            {"pts": 10.8, "reb": 10.5, "ast": 3.5, "fg3m": 0.2},
    "Grayson Allen":           {"pts": 12.5, "reb": 3.2,  "ast": 2.0, "fg3m": 3.0},
    # Dallas Mavericks
    "Luka Doncic":             {"pts": 28.7, "reb": 8.7, "ast": 7.8, "fg3m": 3.5},
    "Kyrie Irving":            {"pts": 24.7, "reb": 5.1, "ast": 5.2, "fg3m": 2.9},
    "Tim Hardaway Jr.":        {"pts": 14.5, "reb": 3.3, "ast": 2.1, "fg3m": 3.0},
    "PJ Washington":           {"pts": 14.2, "reb": 6.4, "ast": 2.4, "fg3m": 2.3},
    # Houston Rockets
    "Alperen Sengun":          {"pts": 21.1, "reb": 9.3, "ast": 5.0, "fg3m": 0.5},
    "Jalen Green":             {"pts": 22.9, "reb": 4.6, "ast": 4.1, "fg3m": 3.0},
    "Fred VanVleet":           {"pts": 12.9, "reb": 3.5, "ast": 6.2, "fg3m": 2.1},
    "Dillon Brooks":           {"pts": 13.8, "reb": 3.5, "ast": 2.1, "fg3m": 2.4},
    "Jabari Smith Jr.":        {"pts": 13.8, "reb": 7.3, "ast": 1.4, "fg3m": 1.9},
    # San Antonio Spurs
    "Victor Wembanyama":       {"pts": 24.3, "reb": 10.6, "ast": 3.9, "fg3m": 2.2},
    "Devin Vassell":           {"pts": 19.5, "reb": 3.9,  "ast": 3.5, "fg3m": 2.8},
    "Keldon Johnson":          {"pts": 14.1, "reb": 4.9,  "ast": 2.4, "fg3m": 1.9},
    "Jeremy Sochan":           {"pts": 12.1, "reb": 5.8,  "ast": 3.3, "fg3m": 0.8},
    # New Orleans Pelicans
    "CJ McCollum":             {"pts": 17.9, "reb": 3.7, "ast": 4.6, "fg3m": 2.8},
    "Herbert Jones":           {"pts": 10.5, "reb": 4.5, "ast": 2.5, "fg3m": 1.0},
    "Jonas Valanciunas":       {"pts": 14.5, "reb": 11.0, "ast": 2.0, "fg3m": 0.5},
    "Trey Murphy III":         {"pts": 18.5, "reb": 4.5,  "ast": 2.0, "fg3m": 2.8},
    # Memphis Grizzlies
    "Jaren Jackson Jr.":       {"pts": 22.6, "reb": 6.2, "ast": 2.0, "fg3m": 2.3},
    "Desmond Bane":            {"pts": 19.9, "reb": 4.3, "ast": 4.0, "fg3m": 3.3},
    "Marcus Smart":            {"pts": 11.5, "reb": 4.0, "ast": 5.5, "fg3m": 1.8},
    "GG Jackson":              {"pts": 14.0, "reb": 4.5, "ast": 1.8, "fg3m": 1.5},
    # Sacramento Kings
    "De'Aaron Fox":            {"pts": 26.3, "reb": 4.9, "ast": 6.2, "fg3m": 1.6},
    "Domantas Sabonis":        {"pts": 20.1, "reb": 14.0, "ast": 7.9, "fg3m": 0.3},
    "Keegan Murray":           {"pts": 15.2, "reb": 4.4,  "ast": 1.6, "fg3m": 2.6},
    "Harrison Barnes":         {"pts": 12.8, "reb": 5.5,  "ast": 1.8, "fg3m": 2.0},
    # Utah Jazz
    "Lauri Markkanen":         {"pts": 23.6, "reb": 8.5, "ast": 2.6, "fg3m": 2.7},
    "Jordan Clarkson":         {"pts": 18.0, "reb": 3.3, "ast": 3.9, "fg3m": 2.7},
    "Collin Sexton":           {"pts": 16.5, "reb": 2.9, "ast": 3.8, "fg3m": 1.8},
    "Walker Kessler":          {"pts": 11.0, "reb": 11.5, "ast": 1.5, "fg3m": 0.0},
    "John Collins":            {"pts": 13.5, "reb": 7.5,  "ast": 1.8, "fg3m": 1.2},
    # Portland Trail Blazers
    "Anfernee Simons":         {"pts": 21.9, "reb": 3.9, "ast": 4.5, "fg3m": 3.4},
    "Jerami Grant":            {"pts": 18.9, "reb": 4.7, "ast": 2.8, "fg3m": 2.1},
    "Deandre Ayton":           {"pts": 16.9, "reb": 10.6, "ast": 1.9, "fg3m": 0.3},
    "Shaedon Sharpe":          {"pts": 18.5, "reb": 3.8,  "ast": 2.2, "fg3m": 2.5},
    # Brooklyn Nets
    "Cam Thomas":              {"pts": 23.5, "reb": 4.2, "ast": 4.1, "fg3m": 2.4},
    "Nic Claxton":             {"pts": 11.9, "reb": 8.4, "ast": 2.3, "fg3m": 0.0},
    "Dennis Schroder":         {"pts": 13.5, "reb": 3.5, "ast": 5.5, "fg3m": 2.0},
    # Washington Wizards
    "Kyle Kuzma":              {"pts": 18.5, "reb": 7.5, "ast": 3.5, "fg3m": 2.0},
    "Bilal Coulibaly":         {"pts": 14.0, "reb": 5.0, "ast": 3.0, "fg3m": 1.8},
    "Deni Avdija":             {"pts": 16.5, "reb": 7.0, "ast": 4.0, "fg3m": 1.5},
    "Jordan Poole":            {"pts": 18.5, "reb": 3.0, "ast": 4.5, "fg3m": 2.8},
    # Detroit Pistons
    "Cade Cunningham":         {"pts": 25.5, "reb": 5.5, "ast": 9.0, "fg3m": 2.5},
    "Jalen Duren":             {"pts": 13.5, "reb": 12.5, "ast": 2.0, "fg3m": 0.0},
    "Ausar Thompson":          {"pts": 14.5, "reb": 6.5,  "ast": 3.0, "fg3m": 1.5},
    "Malik Beasley":           {"pts": 13.0, "reb": 3.5,  "ast": 1.5, "fg3m": 3.2},
}

# Rosters par equipe — seulement joueurs actifs et en sante
NBA_ROSTERS = {
    "Boston Celtics":          ["Jayson Tatum", "Jaylen Brown", "Payton Pritchard", "Jrue Holiday", "Al Horford"],
    "New York Knicks":         ["Jalen Brunson", "Karl-Anthony Towns", "Mikal Bridges", "OG Anunoby", "Josh Hart"],
    "Milwaukee Bucks":         ["Giannis Antetokounmpo", "Brook Lopez", "Bobby Portis", "Khris Middleton"],
    "Cleveland Cavaliers":     ["Donovan Mitchell", "Darius Garland", "Evan Mobley", "Jarrett Allen", "Max Strus"],
    "Indiana Pacers":          ["Tyrese Haliburton", "Pascal Siakam", "Myles Turner", "Bennedict Mathurin", "Andrew Nembhard"],
    "Orlando Magic":           ["Paolo Banchero", "Franz Wagner", "Jalen Suggs", "Cole Anthony"],
    "Miami Heat":              ["Bam Adebayo", "Tyler Herro", "Terry Rozier", "Duncan Robinson"],
    "Philadelphia 76ers":      ["Tyrese Maxey", "Kelly Oubre Jr.", "Tobias Harris"],
    "Chicago Bulls":           ["Zach LaVine", "Nikola Vucevic", "Coby White"],
    "Atlanta Hawks":           ["Trae Young", "Dejounte Murray", "Clint Capela", "De'Andre Hunter"],
    "Toronto Raptors":         ["Scottie Barnes", "RJ Barrett", "Immanuel Quickley", "Jakob Poeltl", "Gradey Dick"],
    "Charlotte Hornets":       ["LaMelo Ball", "Brandon Miller", "Miles Bridges", "Mark Williams"],
    "Brooklyn Nets":           ["Cam Thomas", "Nic Claxton", "Dennis Schroder"],
    "Washington Wizards":      ["Kyle Kuzma", "Bilal Coulibaly", "Deni Avdija", "Jordan Poole"],
    "Detroit Pistons":         ["Cade Cunningham", "Jalen Duren", "Ausar Thompson", "Malik Beasley"],
    "Oklahoma City Thunder":   ["Shai Gilgeous-Alexander", "Jalen Williams", "Chet Holmgren", "Luguentz Dort", "Isaiah Hartenstein"],
    "Denver Nuggets":          ["Nikola Jokic", "Jamal Murray", "Michael Porter Jr.", "Aaron Gordon", "Russell Westbrook"],
    "Minnesota Timberwolves":  ["Anthony Edwards", "Rudy Gobert", "Mike Conley", "Jaden McDaniels", "Naz Reid"],
    "Golden State Warriors":   ["Andrew Wiggins", "Jonathan Kuminga", "Draymond Green", "Moses Moody"],
    "Los Angeles Lakers":      ["LeBron James", "Anthony Davis", "Austin Reaves", "D'Angelo Russell", "Rui Hachimura"],
    "LA Clippers":             ["James Harden", "Norman Powell", "Ivica Zubac", "Derrick Jones Jr."],
    "Phoenix Suns":            ["Kevin Durant", "Devin Booker", "Jusuf Nurkic", "Grayson Allen"],
    "Sacramento Kings":        ["De'Aaron Fox", "Domantas Sabonis", "Keegan Murray", "Harrison Barnes"],
    "Portland Trail Blazers":  ["Anfernee Simons", "Jerami Grant", "Deandre Ayton", "Shaedon Sharpe"],
    "Utah Jazz":               ["Lauri Markkanen", "Jordan Clarkson", "Collin Sexton", "Walker Kessler", "John Collins"],
    "Dallas Mavericks":        ["Luka Doncic", "Kyrie Irving", "Tim Hardaway Jr.", "PJ Washington"],
    "Houston Rockets":         ["Alperen Sengun", "Jalen Green", "Fred VanVleet", "Dillon Brooks", "Jabari Smith Jr."],
    "San Antonio Spurs":       ["Victor Wembanyama", "Devin Vassell", "Keldon Johnson", "Jeremy Sochan"],
    "New Orleans Pelicans":    ["CJ McCollum", "Herbert Jones", "Jonas Valanciunas", "Trey Murphy III"],
    "Memphis Grizzlies":       ["Jaren Jackson Jr.", "Desmond Bane", "Marcus Smart", "GG Jackson"],
}


def _estimate_line(mean: float, stat_key: str) -> float:
    offset = LINE_OFFSET.get(stat_key, 1.0)
    return max(math.floor(mean * 2) / 2 - offset, 0.5)


def _std(mean: float, stat_key: str) -> float:
    return max(mean * STD_FLOOR.get(stat_key, 0.28), 1.0)


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


def _edge(prob: float, dk_implied: float = DK_IMPLIED) -> float:
    if dk_implied <= 0:
        return 0.0
    return round((prob - dk_implied) / dk_implied * 100, 1)


def _kelly(prob: float, dk_implied: float = DK_IMPLIED, dk_odds: float = DK_ODDS) -> float:
    b = dk_odds - 1
    if b <= 0:
        return 0.0
    k = ((b * prob / 100) - (1 - prob / 100)) / b / 4 * 100
    return round(max(k, 0.0), 1)


class NBAPropsAnalyzer:

    def analyze_game(self, game: dict, props_by_market: dict = None) -> dict:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        print(f"  NBA props: {away} @ {home}")

        # Construire un lookup {player_lower: {stat_key: prop_data}}
        # depuis les vraies cotes DraftKings si disponibles
        real_lkp = {}
        if props_by_market:
            for stat_key, market_key in _STAT_TO_MARKET.items():
                for prop in props_by_market.get(market_key, []):
                    pl = prop.get("player", "").lower()
                    if pl not in real_lkp:
                        real_lkp[pl] = {}
                    real_lkp[pl][stat_key] = prop
        use_real = bool(real_lkp)

        ev_bets = []
        seen    = set()

        for team, opp in [(home, away), (away, home)]:
            players = NBA_ROSTERS.get(team, [])
            for player_name in players:
                if player_name in seen:
                    continue
                # Filtre blessures
                if player_name.lower() in NBA_KNOWN_INJURED:
                    continue
                seen.add(player_name)

                stats = NBA_PLAYER_STATS.get(player_name)
                if not stats:
                    continue

                # Calcul PRA dynamique
                stats = dict(stats)
                stats["pra"] = round(stats.get("pts", 0) + stats.get("reb", 0) + stats.get("ast", 0), 1)

                for cfg in STAT_CONFIGS:
                    key     = cfg["key"]
                    label   = cfg["label"]
                    min_avg = cfg["min_avg"]

                    mean = stats.get(key, 0.0)
                    if mean < min_avg:
                        continue

                    # Facteur adversaire selon le marche
                    # Points: ajustement selon pts autorises par l'adversaire (DEF rating)
                    # Rebounds: certaines equipes accordent beaucoup plus de rebonds
                    # Assists: certaines equipes permettent beaucoup plus de passes decisives
                    if key == "pts":
                        def_val = NBA_DEF_PTS_ALLOWED.get(opp, LEAGUE_AVG_DEF_PTS)
                        def_factor = def_val / LEAGUE_AVG_DEF_PTS
                        # Cap: ne pas aller au-dela de 12% d'ajustement (defense extremement bonne/mauvaise)
                        def_factor = max(0.90, min(1.12, def_factor))
                        adj_mean = round(mean * def_factor, 1)
                    elif key == "reb":
                        def_val = NBA_DEF_REB_ALLOWED.get(opp, LEAGUE_AVG_DEF_REB)
                        def_factor = def_val / LEAGUE_AVG_DEF_REB
                        adj_mean = round(mean * def_factor, 1)
                    elif key == "ast":
                        def_val = NBA_DEF_AST_ALLOWED.get(opp, LEAGUE_AVG_DEF_AST)
                        def_factor = def_val / LEAGUE_AVG_DEF_AST
                        adj_mean = round(mean * def_factor, 1)
                    elif key == "pra":
                        # PRA: pts stables, reb et ast ajustes par defense adverse
                        reb_f = NBA_DEF_REB_ALLOWED.get(opp, LEAGUE_AVG_DEF_REB) / LEAGUE_AVG_DEF_REB
                        ast_f = NBA_DEF_AST_ALLOWED.get(opp, LEAGUE_AVG_DEF_AST) / LEAGUE_AVG_DEF_AST
                        adj_pts = stats.get("pts", 0)
                        adj_reb = stats.get("reb", 0) * reb_f
                        adj_ast = stats.get("ast", 0) * ast_f
                        adj_mean = round(adj_pts + adj_reb + adj_ast, 1)
                    else:
                        adj_mean = mean

                    std = _std(adj_mean, key)

                    # Utilise la vraie ligne/cote DK si disponible
                    if use_real:
                        rp = real_lkp.get(player_name.lower(), {}).get(key)
                        if not rp:
                            last = player_name.lower().split()[-1]
                            for k, v in real_lkp.items():
                                if k.split()[-1] == last and key in v:
                                    rp = v[key]
                                    break
                        if not rp:
                            continue

                        line     = rp["line"]
                        dk_impl  = rp["over_implied"]
                        dk_odds  = rp["over_odds"]
                        prob     = _normal_over(adj_mean, std, line)
                        e        = _edge(prob, dk_impl)
                        ratio    = (prob / dk_impl) if dk_impl > 0 else 0
                        if ratio > MAX_DISAGREEMENT_RATIO:
                            continue
                    else:
                        line     = _estimate_line(adj_mean, key)
                        dk_impl  = DK_IMPLIED
                        dk_odds  = DK_ODDS
                        prob     = _normal_over(adj_mean, std, line)
                        e        = _edge(prob, dk_impl)

                    if not (MIN_EDGE <= e <= MAX_EDGE):
                        continue

                    ev_bets.append({
                        "player":     player_name,
                        "team":       team,
                        "opponent":   opp,
                        "market":     f"{label} Over {line}",
                        "stat_key":   key,
                        "line":       line,
                        "avg10":      mean,
                        "avg5":       mean,
                        "adj_proj":   adj_mean,
                        "our_prob":   prob,
                        "edge_pct":   e,
                        "kelly":      _kelly(prob, dk_impl, dk_odds),
                        "est_odds":   dk_odds,
                        "dk_implied": round(dk_impl, 1),
                        "def_rank":   15,
                        "context":    [],
                    })

        ev_bets.sort(key=lambda x: x["edge_pct"], reverse=True)
        ev_bets = ev_bets[:MAX_BETS]

        print(f"    -> {len(ev_bets)} bets NBA +EV")
        return {"home_team": home, "away_team": away, "bets": ev_bets}
