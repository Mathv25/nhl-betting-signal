"""
MLB Props Analyzer
Marches: pitcher_strikeouts (priorite #1), batter_hits, batter_total_bases

Meilleures pratiques integrees:
  1. Props lanceurs = marche le plus predictible du baseball (K rate stable)
  2. Ajustement taux K adverse (equipe qui frappe mal = avantage lanceur)
  3. Ajustement lanceur adverse sur props frappeurs (K/depart du partant oppose)
  4. Splits main dominante (platoon L/R) — impact significatif sur AVG/OBP
  5. Park factors (Coors +runs, Oracle Park -runs)
  6. Distribution normale calibree MLB (variance plus haute que NBA)
  7. Critere de Kelly fractionne (1/4) pour gestion du risque
  8. Note de confirmation de lineup (essentiel en MLB)
"""

import math

# ── MODELES STATISTIQUES ──────────────────────────────────────────────────────
STD_FLOOR = {
    "strikeouts":  0.33,
    "hits":        0.62,
    "total_bases": 0.58,
}

LINE_OFFSET = {
    "strikeouts":  1.0,
    "hits":        0.5,
    "total_bases": 0.5,
}

STAT_CONFIGS = [
    {"key": "strikeouts",  "label": "Retraits au baton", "min_avg": 5.5, "player_type": "pitcher"},
    {"key": "hits",        "label": "Coups surs",        "min_avg": 0.9, "player_type": "batter"},
    {"key": "total_bases", "label": "Buts totaux",       "min_avg": 1.5, "player_type": "batter"},
]

MIN_EDGE   = 5.0
MAX_EDGE   = 22.0
DK_IMPLIED = 52.63
DK_ODDS    = 1.909
MAX_BETS   = 6

_STAT_TO_MARKET = {
    "strikeouts":  "pitcher_strikeouts",
    "hits":        "batter_hits",
    "total_bases": "batter_total_bases",
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
LEAGUE_AVG_K     = 0.215
LEAGUE_AVG_K_SP  = 7.5   # K/depart moyen lanceur partant MLB


# ── LANCEURS PARTANTS ─────────────────────────────────────────────────────────
# hand: "R" droitier, "L" gaucher
MLB_PITCHERS = {
    # Elite
    "Tyler Glasnow":        {"strikeouts": 9.5,  "team": "Los Angeles Dodgers",    "hand": "R"},
    "Spencer Strider":      {"strikeouts": 9.0,  "team": "Atlanta Braves",         "hand": "R"},
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
    "Zac Gallen":           {"strikeouts": 7.0,  "team": "Arizona Diamondbacks",   "hand": "R"},
    "Mitch Keller":         {"strikeouts": 7.0,  "team": "Pittsburgh Pirates",     "hand": "R"},
    "Sandy Alcantara":      {"strikeouts": 6.8,  "team": "Miami Marlins",          "hand": "R"},
    "Justin Steele":        {"strikeouts": 6.8,  "team": "Chicago Cubs",           "hand": "L"},
    "Seth Lugo":            {"strikeouts": 6.5,  "team": "Kansas City Royals",     "hand": "R"},
    "Ranger Suarez":        {"strikeouts": 6.5,  "team": "Philadelphia Phillies",  "hand": "L"},
    "Framber Valdez":       {"strikeouts": 6.5,  "team": "Houston Astros",         "hand": "L"},
    "Logan Webb":           {"strikeouts": 6.0,  "team": "San Francisco Giants",   "hand": "R"},
}

# ── FRAPPEURS ─────────────────────────────────────────────────────────────────
# bats: "R" droitier, "L" gaucher, "S" switch hitter
MLB_BATTERS = {
    "Luis Arraez":           {"hits": 1.50, "total_bases": 1.85, "team": "San Diego Padres",        "bats": "R"},
    "Freddie Freeman":       {"hits": 1.45, "total_bases": 2.35, "team": "Los Angeles Dodgers",     "bats": "L"},
    "Ronald Acuna Jr.":      {"hits": 1.40, "total_bases": 2.40, "team": "Atlanta Braves",          "bats": "R"},
    "Steven Kwan":           {"hits": 1.30, "total_bases": 1.75, "team": "Cleveland Guardians",     "bats": "L"},
    "Juan Soto":             {"hits": 1.35, "total_bases": 2.30, "team": "New York Yankees",        "bats": "L"},
    "Mookie Betts":          {"hits": 1.35, "total_bases": 2.35, "team": "Los Angeles Dodgers",     "bats": "R"},
    "Corey Seager":          {"hits": 1.35, "total_bases": 2.30, "team": "Texas Rangers",           "bats": "L"},
    "Shohei Ohtani":         {"hits": 1.25, "total_bases": 2.45, "team": "Los Angeles Dodgers",     "bats": "L"},
    "Bobby Witt Jr.":        {"hits": 1.30, "total_bases": 2.15, "team": "Kansas City Royals",      "bats": "R"},
    "Trea Turner":           {"hits": 1.30, "total_bases": 2.05, "team": "Philadelphia Phillies",   "bats": "R"},
    "Bryce Harper":          {"hits": 1.30, "total_bases": 2.35, "team": "Philadelphia Phillies",   "bats": "L"},
    "Vladimir Guerrero Jr.": {"hits": 1.30, "total_bases": 2.10, "team": "Toronto Blue Jays",       "bats": "R"},
    "Jose Ramirez":          {"hits": 1.30, "total_bases": 2.20, "team": "Cleveland Guardians",     "bats": "S"},
    "Bo Bichette":           {"hits": 1.30, "total_bases": 2.00, "team": "Toronto Blue Jays",       "bats": "R"},
    "Yordan Alvarez":        {"hits": 1.25, "total_bases": 2.50, "team": "Houston Astros",          "bats": "L"},
    "Kyle Tucker":           {"hits": 1.25, "total_bases": 2.25, "team": "Houston Astros",          "bats": "L"},
    "Rafael Devers":         {"hits": 1.25, "total_bases": 2.20, "team": "Boston Red Sox",          "bats": "L"},
    "Julio Rodriguez":       {"hits": 1.25, "total_bases": 2.10, "team": "Seattle Mariners",        "bats": "R"},
    "Nolan Arenado":         {"hits": 1.20, "total_bases": 2.00, "team": "St. Louis Cardinals",     "bats": "R"},
    "Fernando Tatis Jr.":    {"hits": 1.20, "total_bases": 2.20, "team": "San Diego Padres",        "bats": "R"},
    "Paul Goldschmidt":      {"hits": 1.20, "total_bases": 2.10, "team": "St. Louis Cardinals",     "bats": "R"},
    "Adley Rutschman":       {"hits": 1.20, "total_bases": 1.90, "team": "Baltimore Orioles",       "bats": "S"},
    "Alex Bregman":          {"hits": 1.20, "total_bases": 2.00, "team": "Boston Red Sox",          "bats": "R"},
    "Francisco Lindor":      {"hits": 1.20, "total_bases": 2.05, "team": "New York Mets",           "bats": "S"},
    "Cedric Mullins":        {"hits": 1.20, "total_bases": 1.85, "team": "Baltimore Orioles",       "bats": "S"},
    "Xander Bogaerts":       {"hits": 1.20, "total_bases": 1.90, "team": "San Diego Padres",        "bats": "R"},
    "Gunnar Henderson":      {"hits": 1.15, "total_bases": 2.10, "team": "Baltimore Orioles",       "bats": "L"},
    "Mike Trout":            {"hits": 1.15, "total_bases": 2.20, "team": "Los Angeles Angels",      "bats": "R"},
    "Nolan Jones":           {"hits": 1.15, "total_bases": 1.95, "team": "Colorado Rockies",        "bats": "L"},
    "Marcus Semien":         {"hits": 1.15, "total_bases": 1.90, "team": "Texas Rangers",           "bats": "R"},
    "Austin Riley":          {"hits": 1.15, "total_bases": 2.15, "team": "Atlanta Braves",          "bats": "R"},
    "Michael Harris II":     {"hits": 1.15, "total_bases": 1.90, "team": "Atlanta Braves",          "bats": "L"},
    "Jazz Chisholm Jr.":     {"hits": 1.15, "total_bases": 2.00, "team": "New York Yankees",        "bats": "L"},
    "Anthony Volpe":         {"hits": 1.15, "total_bases": 1.85, "team": "New York Yankees",        "bats": "R"},
    "Elly De La Cruz":       {"hits": 1.15, "total_bases": 1.95, "team": "Cincinnati Reds",         "bats": "S"},
    "Matt Olson":            {"hits": 1.10, "total_bases": 2.20, "team": "Atlanta Braves",          "bats": "L"},
    "Pete Alonso":           {"hits": 1.10, "total_bases": 2.15, "team": "New York Mets",           "bats": "R"},
    "Byron Buxton":          {"hits": 1.10, "total_bases": 2.20, "team": "Minnesota Twins",         "bats": "R"},
    "Marcell Ozuna":         {"hits": 1.10, "total_bases": 2.10, "team": "Atlanta Braves",          "bats": "R"},
    "Willy Adames":          {"hits": 1.10, "total_bases": 1.90, "team": "San Francisco Giants",    "bats": "R"},
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
    return max(mean * STD_FLOOR.get(stat_key, 0.35), 0.5)


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

        # Lookup cotes reelles DK
        real_lkp = {}
        if props_by_market:
            for stat_key, market_key in _STAT_TO_MARKET.items():
                for prop in props_by_market.get(market_key, []):
                    pl = prop.get("player", "").lower()
                    real_lkp.setdefault(pl, {})[stat_key] = prop
        use_real = bool(real_lkp)

        # Meilleur lanceur partant connu par equipe (pour props frappeurs)
        def _best_pitcher(team: str):
            pitchers = _TEAM_PITCHERS.get(team, [])
            if not pitchers:
                return None, None
            best = max(pitchers, key=lambda p: MLB_PITCHERS[p]["strikeouts"])
            return best, MLB_PITCHERS[best]

        ev_bets = []
        seen    = set()

        # ── LANCEURS ─────────────────────────────────────────────────────────
        cfg_k = next(c for c in STAT_CONFIGS if c["key"] == "strikeouts")
        for team, opp in [(home, away), (away, home)]:
            for pitcher in _TEAM_PITCHERS.get(team, []):
                if pitcher in seen:
                    continue
                seen.add(pitcher)
                stats  = MLB_PITCHERS.get(pitcher, {})
                mean_k = stats.get("strikeouts", 0.0)
                if mean_k < cfg_k["min_avg"]:
                    continue

                opp_k_rate = TEAM_K_RATES.get(opp, LEAGUE_AVG_K)
                adj_factor = opp_k_rate / LEAGUE_AVG_K
                adj_mean   = round(mean_k * adj_factor, 2)
                std        = _std(adj_mean, "strikeouts")

                context = []
                if opp_k_rate > LEAGUE_AVG_K + 0.015:
                    context.append(f"Adversaire K%: {opp_k_rate:.1%} (favorable)")
                elif opp_k_rate < LEAGUE_AVG_K - 0.015:
                    context.append(f"Adversaire K%: {opp_k_rate:.1%} (difficile)")
                park_lbl = _park_label(park_factor)
                if park_factor != 1.00:
                    context.append(f"Terrain: {park_lbl} (PF {park_factor:.2f})")

                if use_real:
                    rp = real_lkp.get(pitcher.lower(), {}).get("strikeouts")
                    if not rp:
                        last = pitcher.lower().split()[-1]
                        for k, v in real_lkp.items():
                            if k.split()[-1] == last and "strikeouts" in v:
                                rp = v["strikeouts"]
                                break
                    if not rp:
                        continue
                    line    = rp["line"]
                    dk_impl = rp["over_implied"]
                    dk_odds = rp["over_odds"]
                else:
                    line    = _estimate_line(adj_mean, "strikeouts")
                    dk_impl = DK_IMPLIED
                    dk_odds = DK_ODDS

                prob = _normal_over(adj_mean, std, line)
                edge = _edge(prob, dk_impl)

                if not (MIN_EDGE <= edge <= MAX_EDGE):
                    continue

                ev_bets.append({
                    "player":        pitcher,
                    "team":          team,
                    "opponent":      opp,
                    "player_type":   "pitcher",
                    "market":        f"{cfg_k['label']} Over {line}",
                    "stat_key":      "strikeouts",
                    "line":          line,
                    "season_avg":    mean_k,
                    "adj_proj":      adj_mean,
                    "opp_k_rate":    round(opp_k_rate * 100, 1),
                    "park_factor":   park_factor,
                    "our_prob":      prob,
                    "edge_pct":      edge,
                    "kelly":         _kelly(prob, dk_impl, dk_odds),
                    "est_odds":      dk_odds,
                    "dk_implied":    round(dk_impl, 1),
                    "context":       context,
                })

        # ── FRAPPEURS ─────────────────────────────────────────────────────────
        for team, opp in [(home, away), (away, home)]:
            # Lanceur adverse le plus fort connu
            opp_pitcher_name, opp_pitcher_stats = _best_pitcher(opp)
            opp_k     = opp_pitcher_stats["strikeouts"] if opp_pitcher_stats else LEAGUE_AVG_K_SP
            opp_hand  = opp_pitcher_stats.get("hand", "") if opp_pitcher_stats else ""
            pitch_adj, pitch_lbl = _pitcher_difficulty_adj(opp_k)

            for batter in _TEAM_BATTERS.get(team, []):
                if batter in seen:
                    continue
                seen.add(batter)
                stats      = MLB_BATTERS.get(batter, {})
                batter_hand = stats.get("bats", "")

                plat_adj, plat_lbl = _platoon_adj(batter_hand, opp_hand)

                for cfg in STAT_CONFIGS:
                    if cfg["player_type"] != "batter":
                        continue
                    key  = cfg["key"]
                    mean = stats.get(key, 0.0)
                    if mean < cfg["min_avg"]:
                        continue

                    # Projection ajustee: lanceur adverse + platoon
                    adj_mean = round(mean * pitch_adj * plat_adj, 3)
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

                    if use_real:
                        rp = real_lkp.get(batter.lower(), {}).get(key)
                        if not rp:
                            last = batter.lower().split()[-1]
                            for k, v in real_lkp.items():
                                if k.split()[-1] == last and key in v:
                                    rp = v[key]
                                    break
                        if not rp:
                            continue
                        line    = rp["line"]
                        dk_impl = rp["over_implied"]
                        dk_odds = rp["over_odds"]
                    else:
                        line    = _estimate_line(adj_mean, key)
                        dk_impl = DK_IMPLIED
                        dk_odds = DK_ODDS

                    prob = _normal_over(adj_mean, std, line)
                    edge = _edge(prob, dk_impl)

                    if not (MIN_EDGE <= edge <= MAX_EDGE):
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
        return {"home_team": home, "away_team": away, "bets": ev_bets}
