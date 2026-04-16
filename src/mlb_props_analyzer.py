"""
MLB Props Analyzer
Marches: pitcher_strikeouts (priorite #1), batter_hits, batter_total_bases

Meilleures pratiques integrees:
  1. Props lanceurs = marche le plus predictible du baseball (K rate stable)
  2. Ajustement taux K adverse (equipe qui frappe mal = avantage lanceur)
  3. Park factors (Coors +runs, Oracle Park -runs)
  4. Distribution normale calibree MLB (variance plus haute que NBA)
  5. Critere de Kelly fractionne (1/4) pour gestion du risque
  6. Note de confirmation de lineup (essentiel en MLB)
"""

import math

# ── MODELES STATISTIQUES ──────────────────────────────────────────────────────
# STD en fraction de la moyenne — calibre sur donnees MLB historiques
STD_FLOOR = {
    "strikeouts":  0.33,  # Lanceurs: std ~33% mean (ex: 7.5K → std 2.5) — tres predictible
    "hits":        0.62,  # Frappeurs: haute variance (jeux discrets 0-4)
    "total_bases": 0.58,  # Buts totaux: variance moderee-haute
}

# Decalage de ligne estime sous la moyenne (les books protegent le vig)
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
DK_IMPLIED = 52.63   # Standard DK -110
DK_ODDS    = 1.909
MAX_BETS   = 6

_STAT_TO_MARKET = {
    "strikeouts":  "pitcher_strikeouts",
    "hits":        "batter_hits",
    "total_bases": "batter_total_bases",
}

# ── PARK FACTORS ─────────────────────────────────────────────────────────────
# >1.0 = favorable frappeurs (nuit aux lanceurs) | <1.0 = favorable lanceurs
# Impact sur les Ks lanceurs: inverse leger (park favorable = moins de Ks)
PARK_FACTORS = {
    "Colorado Rockies":       1.15,  # Coors Field — alt. 5280pi
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
    "San Francisco Giants":   0.90,  # Oracle Park — meilleur parc lanceurs MLB
}

# ── TAUX DE RETRAITS EQUIPES ADVERSES ────────────────────────────────────────
# Plus le taux est eleve, plus le lanceur a de facilite a accumuler des Ks
# Source: approximations saison 2024-25
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
    "Houston Astros":         0.185,  # Astros = lineup le plus difficile a retirer
}
LEAGUE_AVG_K = 0.215

# ── LANCEURS PARTANTS — Moyenne K par depart qualifie (2025) ─────────────────
# A mettre a jour en debut de chaque saison
MLB_PITCHERS = {
    # Elite (8.5+ K/depart)
    "Tyler Glasnow":        {"strikeouts": 9.5,  "team": "Los Angeles Dodgers"},
    "Spencer Strider":      {"strikeouts": 9.0,  "team": "Atlanta Braves"},
    "Tarik Skubal":         {"strikeouts": 8.8,  "team": "Detroit Tigers"},
    "Blake Snell":          {"strikeouts": 8.7,  "team": "San Francisco Giants"},
    "Freddy Peralta":       {"strikeouts": 8.5,  "team": "Milwaukee Brewers"},
    "Gerrit Cole":          {"strikeouts": 8.5,  "team": "New York Yankees"},
    "Zack Wheeler":         {"strikeouts": 8.5,  "team": "Philadelphia Phillies"},
    "Aaron Nola":           {"strikeouts": 8.5,  "team": "Philadelphia Phillies"},
    "Cole Ragans":          {"strikeouts": 8.5,  "team": "Kansas City Royals"},
    # Tier 2 (7.5–8.4)
    "Yoshinobu Yamamoto":   {"strikeouts": 8.2,  "team": "Los Angeles Dodgers"},
    "Dylan Cease":          {"strikeouts": 8.2,  "team": "San Diego Padres"},
    "Kevin Gausman":        {"strikeouts": 8.0,  "team": "Toronto Blue Jays"},
    "Chris Sale":           {"strikeouts": 8.0,  "team": "Atlanta Braves"},
    "MacKenzie Gore":       {"strikeouts": 8.0,  "team": "Washington Nationals"},
    "Carlos Rodon":         {"strikeouts": 8.0,  "team": "New York Yankees"},
    "Max Fried":            {"strikeouts": 7.8,  "team": "New York Yankees"},
    "Logan Gilbert":        {"strikeouts": 7.8,  "team": "Seattle Mariners"},
    "Joe Ryan":             {"strikeouts": 7.8,  "team": "Minnesota Twins"},
    "Sonny Gray":           {"strikeouts": 7.8,  "team": "St. Louis Cardinals"},
    "Luis Castillo":        {"strikeouts": 7.5,  "team": "Seattle Mariners"},
    "Corbin Burnes":        {"strikeouts": 7.5,  "team": "Baltimore Orioles"},
    "Pablo Lopez":          {"strikeouts": 7.5,  "team": "Minnesota Twins"},
    "Tanner Houck":         {"strikeouts": 7.5,  "team": "Boston Red Sox"},
    "Reid Detmers":         {"strikeouts": 7.5,  "team": "Los Angeles Angels"},
    "Patrick Sandoval":     {"strikeouts": 7.5,  "team": "Los Angeles Angels"},
    "Brandon Woodruff":     {"strikeouts": 7.5,  "team": "Milwaukee Brewers"},
    "Shohei Ohtani":        {"strikeouts": 9.2,  "team": "Los Angeles Dodgers"},  # aussi frappeur
    "Edward Cabrera":       {"strikeouts": 7.5,  "team": "Miami Marlins"},
    # Tier 3 (6.5–7.4)
    "George Kirby":         {"strikeouts": 7.2,  "team": "Seattle Mariners"},
    "Nestor Cortes":        {"strikeouts": 7.2,  "team": "New York Yankees"},
    "Hunter Brown":         {"strikeouts": 7.2,  "team": "Houston Astros"},
    "Jesus Luzardo":        {"strikeouts": 7.2,  "team": "Miami Marlins"},
    "Shane Bieber":         {"strikeouts": 7.0,  "team": "Cleveland Guardians"},
    "Zac Gallen":           {"strikeouts": 7.0,  "team": "Arizona Diamondbacks"},
    "Mitch Keller":         {"strikeouts": 7.0,  "team": "Pittsburgh Pirates"},
    "Sandy Alcantara":      {"strikeouts": 6.8,  "team": "Miami Marlins"},
    "Justin Steele":        {"strikeouts": 6.8,  "team": "Chicago Cubs"},
    "Seth Lugo":            {"strikeouts": 6.5,  "team": "Kansas City Royals"},
    "Ranger Suarez":        {"strikeouts": 6.5,  "team": "Philadelphia Phillies"},
    "Framber Valdez":       {"strikeouts": 6.5,  "team": "Houston Astros"},
    "Logan Webb":           {"strikeouts": 6.0,  "team": "San Francisco Giants"},
}

# ── FRAPPEURS — Moyennes par partie (2025) ────────────────────────────────────
MLB_BATTERS = {
    "Luis Arraez":           {"hits": 1.50, "total_bases": 1.85, "team": "San Diego Padres"},
    "Freddie Freeman":       {"hits": 1.45, "total_bases": 2.35, "team": "Los Angeles Dodgers"},
    "Ronald Acuna Jr.":      {"hits": 1.40, "total_bases": 2.40, "team": "Atlanta Braves"},
    "Steven Kwan":           {"hits": 1.30, "total_bases": 1.75, "team": "Cleveland Guardians"},
    "Juan Soto":             {"hits": 1.35, "total_bases": 2.30, "team": "New York Yankees"},
    "Mookie Betts":          {"hits": 1.35, "total_bases": 2.35, "team": "Los Angeles Dodgers"},
    "Corey Seager":          {"hits": 1.35, "total_bases": 2.30, "team": "Texas Rangers"},
    "Shohei Ohtani":         {"hits": 1.25, "total_bases": 2.45, "team": "Los Angeles Dodgers"},
    "Bobby Witt Jr.":        {"hits": 1.30, "total_bases": 2.15, "team": "Kansas City Royals"},
    "Trea Turner":           {"hits": 1.30, "total_bases": 2.05, "team": "Philadelphia Phillies"},
    "Bryce Harper":          {"hits": 1.30, "total_bases": 2.35, "team": "Philadelphia Phillies"},
    "Vladimir Guerrero Jr.": {"hits": 1.30, "total_bases": 2.10, "team": "Toronto Blue Jays"},
    "Jose Ramirez":          {"hits": 1.30, "total_bases": 2.20, "team": "Cleveland Guardians"},
    "Bo Bichette":           {"hits": 1.30, "total_bases": 2.00, "team": "Toronto Blue Jays"},
    "Yordan Alvarez":        {"hits": 1.25, "total_bases": 2.50, "team": "Houston Astros"},
    "Kyle Tucker":           {"hits": 1.25, "total_bases": 2.25, "team": "Houston Astros"},
    "Rafael Devers":         {"hits": 1.25, "total_bases": 2.20, "team": "Boston Red Sox"},
    "Julio Rodriguez":       {"hits": 1.25, "total_bases": 2.10, "team": "Seattle Mariners"},
    "Nolan Arenado":         {"hits": 1.20, "total_bases": 2.00, "team": "St. Louis Cardinals"},
    "Fernando Tatis Jr.":    {"hits": 1.20, "total_bases": 2.20, "team": "San Diego Padres"},
    "Paul Goldschmidt":      {"hits": 1.20, "total_bases": 2.10, "team": "St. Louis Cardinals"},
    "Adley Rutschman":       {"hits": 1.20, "total_bases": 1.90, "team": "Baltimore Orioles"},
    "Alex Bregman":          {"hits": 1.20, "total_bases": 2.00, "team": "Boston Red Sox"},
    "Francisco Lindor":      {"hits": 1.20, "total_bases": 2.05, "team": "New York Mets"},
    "Cedric Mullins":        {"hits": 1.20, "total_bases": 1.85, "team": "Baltimore Orioles"},
    "Xander Bogaerts":       {"hits": 1.20, "total_bases": 1.90, "team": "San Diego Padres"},
    "Gunnar Henderson":      {"hits": 1.15, "total_bases": 2.10, "team": "Baltimore Orioles"},
    "Mike Trout":            {"hits": 1.15, "total_bases": 2.20, "team": "Los Angeles Angels"},
    "Nolan Jones":           {"hits": 1.15, "total_bases": 1.95, "team": "Colorado Rockies"},
    "Marcus Semien":         {"hits": 1.15, "total_bases": 1.90, "team": "Texas Rangers"},
    "Austin Riley":          {"hits": 1.15, "total_bases": 2.15, "team": "Atlanta Braves"},
    "Michael Harris II":     {"hits": 1.15, "total_bases": 1.90, "team": "Atlanta Braves"},
    "Jazz Chisholm Jr.":     {"hits": 1.15, "total_bases": 2.00, "team": "New York Yankees"},
    "Anthony Volpe":         {"hits": 1.15, "total_bases": 1.85, "team": "New York Yankees"},
    "Elly De La Cruz":       {"hits": 1.15, "total_bases": 1.95, "team": "Cincinnati Reds"},
    "Matt Olson":            {"hits": 1.10, "total_bases": 2.20, "team": "Atlanta Braves"},
    "Pete Alonso":           {"hits": 1.10, "total_bases": 2.15, "team": "New York Mets"},
    "Byron Buxton":          {"hits": 1.10, "total_bases": 2.20, "team": "Minnesota Twins"},
    "Marcell Ozuna":         {"hits": 1.10, "total_bases": 2.10, "team": "Atlanta Braves"},
    "Willy Adames":          {"hits": 1.10, "total_bases": 1.90, "team": "San Francisco Giants"},
}

# Lookup equipe → lanceurs / frappeurs
_TEAM_PITCHERS = {}
for p, s in MLB_PITCHERS.items():
    _TEAM_PITCHERS.setdefault(s["team"], []).append(p)

_TEAM_BATTERS = {}
for p, s in MLB_BATTERS.items():
    _TEAM_BATTERS.setdefault(s["team"], []).append(p)


# ── MATH ──────────────────────────────────────────────────────────────────────
def _estimate_line(mean: float, stat_key: str) -> float:
    offset = LINE_OFFSET.get(stat_key, 0.5)
    return max(math.floor(mean * 2) / 2 - offset, 0.5)


def _std(mean: float, stat_key: str) -> float:
    return max(mean * STD_FLOOR.get(stat_key, 0.35), 0.5)


def _normal_over(mean: float, std: float, line: float) -> float:
    """Probabilite d'aller over la ligne via distribution normale."""
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

        # Lookup des vraies cotes DK par marche et joueur
        real_lkp = {}
        if props_by_market:
            for stat_key, market_key in _STAT_TO_MARKET.items():
                for prop in props_by_market.get(market_key, []):
                    pl = prop.get("player", "").lower()
                    real_lkp.setdefault(pl, {})[stat_key] = prop
        use_real = bool(real_lkp)

        ev_bets = []
        seen    = set()

        # ── LANCEURS ────────────────────────────────────────────────────────
        cfg_k = next(c for c in STAT_CONFIGS if c["key"] == "strikeouts")
        for team, opp in [(home, away), (away, home)]:
            for pitcher in _TEAM_PITCHERS.get(team, []):
                if pitcher in seen:
                    continue
                seen.add(pitcher)
                stats = MLB_PITCHERS.get(pitcher, {})
                mean_k = stats.get("strikeouts", 0.0)
                if mean_k < cfg_k["min_avg"]:
                    continue

                # Ajustement taux K adverse
                opp_k_rate = TEAM_K_RATES.get(opp, LEAGUE_AVG_K)
                adj_factor = opp_k_rate / LEAGUE_AVG_K
                adj_mean   = round(mean_k * adj_factor, 2)

                std = _std(adj_mean, "strikeouts")

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
                    "player":      pitcher,
                    "team":        team,
                    "opponent":    opp,
                    "player_type": "pitcher",
                    "market":      f"{cfg_k['label']} Over {line}",
                    "stat_key":    "strikeouts",
                    "line":        line,
                    "season_avg":  mean_k,
                    "adj_proj":    adj_mean,
                    "opp_k_rate":  round(opp_k_rate * 100, 1),
                    "park_factor": park_factor,
                    "our_prob":    prob,
                    "edge_pct":    edge,
                    "kelly":       _kelly(prob, dk_impl, dk_odds),
                    "est_odds":    dk_odds,
                    "dk_implied":  round(dk_impl, 1),
                    "context":     context,
                })

        # ── FRAPPEURS ────────────────────────────────────────────────────────
        for team, opp in [(home, away), (away, home)]:
            for batter in _TEAM_BATTERS.get(team, []):
                if batter in seen:
                    continue
                seen.add(batter)
                stats = MLB_BATTERS.get(batter, {})

                for cfg in STAT_CONFIGS:
                    if cfg["player_type"] != "batter":
                        continue
                    key   = cfg["key"]
                    mean  = stats.get(key, 0.0)
                    if mean < cfg["min_avg"]:
                        continue

                    std = _std(mean, key)

                    context = []
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
                        line    = _estimate_line(mean, key)
                        dk_impl = DK_IMPLIED
                        dk_odds = DK_ODDS

                    prob = _normal_over(mean, std, line)
                    edge = _edge(prob, dk_impl)

                    if not (MIN_EDGE <= edge <= MAX_EDGE):
                        continue

                    ev_bets.append({
                        "player":      batter,
                        "team":        team,
                        "opponent":    opp,
                        "player_type": "batter",
                        "market":      f"{cfg['label']} Over {line}",
                        "stat_key":    key,
                        "line":        line,
                        "season_avg":  mean,
                        "adj_proj":    mean,
                        "opp_k_rate":  None,
                        "park_factor": park_factor,
                        "our_prob":    prob,
                        "edge_pct":    edge,
                        "kelly":       _kelly(prob, dk_impl, dk_odds),
                        "est_odds":    dk_odds,
                        "dk_implied":  round(dk_impl, 1),
                        "context":     context,
                    })

        ev_bets.sort(key=lambda x: x["edge_pct"], reverse=True)
        ev_bets = ev_bets[:MAX_BETS]

        print(f"    -> {len(ev_bets)} bets MLB +EV")
        return {"home_team": home, "away_team": away, "bets": ev_bets}
