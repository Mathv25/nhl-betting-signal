"""
Lineup Fetcher — Daily Faceoff scraper
Recupere les line combos, PP units, et statuts blessures
pour ajuster les projections shots/points
"""

import requests
import time
import re
from typing import Optional

BASE_URL = "https://www.dailyfaceoff.com/teams/{slug}/line-combinations"

# Multiplicateurs de role pour les projections
ROLE_MULTIPLIERS = {
    "line1_pp1": 1.35,   # Top line + PP1 = impact maximal
    "line1_pp2": 1.20,   # Top line + PP2
    "line1_noPP": 1.10,  # Top line, pas de PP time
    "line2_pp1": 1.25,   # 2e ligne + PP1
    "line2_pp2": 1.12,   # 2e ligne + PP2
    "line2_noPP": 1.00,  # 2e ligne, baseline
    "line3_pp1": 1.15,   # 3e ligne + PP1 (rare)
    "line3_pp2": 1.05,   # 3e ligne + PP2
    "line3_noPP": 0.88,  # 3e ligne, peu de shots
    "line4_pp1": 1.10,   # 4e ligne + PP1 (tres rare)
    "line4_pp2": 1.00,   # 4e ligne + PP2
    "line4_noPP": 0.72,  # 4e ligne, minimum de shots
    "defense_pp1": 1.20, # Defenseur PP1 (QB du PP)
    "defense_pp2": 1.05, # Defenseur PP2
    "defense_noPP": 0.85,# Defenseur sans PP time
}

# Mapping nom equipe -> slug Daily Faceoff
TEAM_SLUGS = {
    "Anaheim Ducks":        "anaheim-ducks",
    "Boston Bruins":        "boston-bruins",
    "Buffalo Sabres":       "buffalo-sabres",
    "Calgary Flames":       "calgary-flames",
    "Carolina Hurricanes":  "carolina-hurricanes",
    "Chicago Blackhawks":   "chicago-blackhawks",
    "Colorado Avalanche":   "colorado-avalanche",
    "Columbus Blue Jackets":"columbus-blue-jackets",
    "Dallas Stars":         "dallas-stars",
    "Detroit Red Wings":    "detroit-red-wings",
    "Edmonton Oilers":      "edmonton-oilers",
    "Florida Panthers":     "florida-panthers",
    "Los Angeles Kings":    "los-angeles-kings",
    "Minnesota Wild":       "minnesota-wild",
    "Montreal Canadiens":   "montreal-canadiens",
    "Montréal Canadiens":   "montreal-canadiens",
    "Nashville Predators":  "nashville-predators",
    "New Jersey Devils":    "new-jersey-devils",
    "New York Islanders":   "new-york-islanders",
    "New York Rangers":     "new-york-rangers",
    "Ottawa Senators":      "ottawa-senators",
    "Philadelphia Flyers":  "philadelphia-flyers",
    "Pittsburgh Penguins":  "pittsburgh-penguins",
    "San Jose Sharks":      "san-jose-sharks",
    "Seattle Kraken":       "seattle-kraken",
    "St. Louis Blues":      "st-louis-blues",
    "St Louis Blues":       "st-louis-blues",
    "Tampa Bay Lightning":  "tampa-bay-lightning",
    "Toronto Maple Leafs":  "toronto-maple-leafs",
    "Utah Mammoth":         "utah-mammoth",
    "Vancouver Canucks":    "vancouver-canucks",
    "Vegas Golden Knights": "vegas-golden-knights",
    "Washington Capitals":  "washington-capitals",
    "Winnipeg Jets":        "winnipeg-jets",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

INJURY_STATUSES = {"ir", "out", "dtd", "gtd"}


def _normalize_name(name: str) -> str:
    """Normalise le nom pour comparaison (lowercase, sans accents de base)."""
    return name.lower().strip()


class LineupFetcher:

    def __init__(self):
        self._cache = {}  # team_name -> lineup_data

    def get_lineup(self, team_name: str) -> dict:
        """
        Retourne le lineup complet d'une equipe depuis Daily Faceoff.

        Structure retournee:
        {
            "forwards": [
                {"name": "Cole Caufield", "line": 1, "pos": "LW"},
                ...
            ],
            "defense": [
                {"name": "Lane Hutson", "pair": 1, "pos": "LD"},
                ...
            ],
            "pp1": ["Cole Caufield", "Nick Suzuki", ...],
            "pp2": ["Alex Newhook", ...],
            "injuries": {"Patrik Laine": "ir", ...},
            "goalie": "Jakub Dobes",
            "player_roles": {
                "cole caufield": {
                    "line": 1, "pp": 1, "is_defense": False,
                    "multiplier": 1.35
                },
                ...
            }
        }
        """
        if team_name in self._cache:
            return self._cache[team_name]

        slug = TEAM_SLUGS.get(team_name, "")
        if not slug:
            print(f"  LineupFetcher: slug introuvable pour {team_name}")
            return {}

        url = BASE_URL.format(slug=slug)
        time.sleep(1.0)

        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            html = r.text
        except Exception as e:
            print(f"  LineupFetcher: erreur {team_name} — {e}")
            return {}

        data = self._parse_lineup(html)
        self._cache[team_name] = data
        print(f"  ✅ Lineup DF {team_name}: {len(data.get('forwards', []))} fwd · PP1: {len(data.get('pp1', []))} joueurs")
        return data

    def get_player_role(self, player_name: str, team_name: str) -> dict:
        """
        Retourne le role d'un joueur avec son multiplicateur.
        Defaut si lineup indisponible.
        """
        lineup = self.get_lineup(team_name)
        if not lineup:
            return {"line": 2, "pp": 0, "is_defense": False, "multiplier": 1.0}

        roles = lineup.get("player_roles", {})
        key   = _normalize_name(player_name)
        return roles.get(key, {"line": 2, "pp": 0, "is_defense": False, "multiplier": 1.0})

    def is_injured(self, player_name: str, team_name: str) -> bool:
        """True si le joueur est sur IR ou OUT."""
        lineup = self.get_lineup(team_name)
        if not lineup:
            return False
        injuries = lineup.get("injuries", {})
        key = _normalize_name(player_name)
        status = injuries.get(key, "")
        return status in {"ir", "out"}

    def _parse_lineup(self, html: str) -> dict:
        """
        Parse le HTML de Daily Faceoff pour extraire lines, PP, blessures.
        Le site utilise du texte plat avec les noms des joueurs dans des liens <a>.
        """
        # Extrait tous les blocs de section et leurs joueurs
        # Structure: "Forwards", "1st Powerplay Unit", "2nd Powerplay Unit", etc.

        forwards  = []
        defense   = []
        pp1       = []
        pp2       = []
        injuries  = {}
        goalie    = ""

        # --- Extraction des noms de joueurs par section ---
        # On cherche les patterns de sections dans le HTML

        sections = self._extract_sections(html)

        # Forwards (4 lignes de 3)
        fwd_names = sections.get("Forwards", [])
        for i, name in enumerate(fwd_names):
            line_num = (i // 3) + 1
            pos_idx  = i % 3
            pos = ["LW", "C", "RW"][pos_idx]
            forwards.append({"name": name, "line": line_num, "pos": pos})

        # Defense (3 paires de 2)
        def_names = sections.get("Defensive Pairings", [])
        for i, name in enumerate(def_names):
            pair_num = (i // 2) + 1
            pos = "LD" if i % 2 == 0 else "RD"
            defense.append({"name": name, "pair": pair_num, "pos": pos})

        # PP units
        pp1 = sections.get("1st Powerplay Unit", [])
        pp2 = sections.get("2nd Powerplay Unit", [])

        # Goalies
        goalies = sections.get("Goalies", [])
        if goalies:
            goalie = goalies[0]

        # Blessures
        inj_raw = sections.get("Injuries", [])
        inj_statuses = self._extract_injury_statuses(html, inj_raw)
        for name, status in inj_statuses.items():
            injuries[_normalize_name(name)] = status

        # --- Construction du dict player_roles ---
        player_roles = {}

        pp1_set = {_normalize_name(n) for n in pp1}
        pp2_set = {_normalize_name(n) for n in pp2}

        for p in forwards:
            key  = _normalize_name(p["name"])
            line = p["line"]
            pp   = 1 if key in pp1_set else (2 if key in pp2_set else 0)
            mult = self._get_multiplier(line, pp, is_defense=False)
            player_roles[key] = {
                "name":       p["name"],
                "line":       line,
                "pp":         pp,
                "pos":        p["pos"],
                "is_defense": False,
                "multiplier": mult,
            }

        for p in defense:
            key  = _normalize_name(p["name"])
            pair = p["pair"]
            pp   = 1 if key in pp1_set else (2 if key in pp2_set else 0)
            mult = self._get_multiplier(pair, pp, is_defense=True)
            player_roles[key] = {
                "name":       p["name"],
                "line":       pair,
                "pp":         pp,
                "pos":        p["pos"],
                "is_defense": True,
                "multiplier": mult,
            }

        return {
            "forwards":     forwards,
            "defense":      defense,
            "pp1":          pp1,
            "pp2":          pp2,
            "injuries":     injuries,
            "goalie":       goalie,
            "player_roles": player_roles,
        }

    def _extract_sections(self, html: str) -> dict:
        """
        Extrait les noms de joueurs par section depuis le HTML Daily Faceoff.
        """
        sections = {}
        current_section = None

        # On cherche les titres de sections et les liens joueurs
        # Pattern titre: texte standalone suivi de joueurs
        section_titles = [
            "Forwards",
            "Defensive Pairings",
            "1st Powerplay Unit",
            "2nd Powerplay Unit",
            "1st Penalty Kill Unit",
            "2nd Penalty Kill Unit",
            "Goalies",
            "Injuries",
        ]

        # Extrait les liens joueurs depuis le HTML
        # Format: href="/players/news/player-name/ID">Display Name</a>
        player_pattern = re.compile(
            r'href="/players/news/[^"]+/\d+"[^>]*>\s*([^<]+?)\s*</a>',
            re.IGNORECASE
        )

        # Extrait les sections depuis le HTML via les titres
        for title in section_titles:
            # Cherche le titre dans le HTML
            escaped = re.escape(title)
            # Match le titre comme texte standalone
            title_match = re.search(
                r'(?<=>)\s*' + escaped + r'\s*(?=<)',
                html
            )
            if title_match:
                sections[title] = []

        # Parse le HTML ligne par ligne pour assigner les joueurs aux sections
        lines = html.split('\n')
        current = None

        for line in lines:
            # Detecte changement de section
            for title in section_titles:
                if f">{title}<" in line or f">{title} <" in line:
                    current = title
                    if current not in sections:
                        sections[current] = []
                    break

            # Extrait joueur si on est dans une section
            if current:
                for match in player_pattern.finditer(line):
                    name = match.group(1).strip()
                    # Filtre les noms trop courts ou qui sont des titres
                    if len(name) > 3 and name not in section_titles:
                        if current not in sections:
                            sections[current] = []
                        # Evite les doublons dans la meme section
                        if name not in sections[current]:
                            sections[current].append(name)

        return sections

    def _extract_injury_statuses(self, html: str, injury_names: list) -> dict:
        """
        Extrait le statut de blessure pour chaque joueur blesse.
        Les statuts (ir, out, dtd, gtd) apparaissent comme classes CSS ou texte.
        """
        result = {}

        # Pattern: statut (ir/out/dtd/gtd) proche du nom du joueur
        for name in injury_names:
            # Cherche le statut dans le contexte du joueur dans le HTML
            escaped = re.escape(name)
            # Cherche le bloc contenant le nom et un statut
            context_pattern = re.compile(
                r'(' + '|'.join(INJURY_STATUSES) + r').*?' + escaped +
                r'|' + escaped + r'.*?(' + '|'.join(INJURY_STATUSES) + r')',
                re.IGNORECASE | re.DOTALL
            )
            # Cherche aussi juste le tag de statut dans le HTML pres du joueur
            idx = html.find(name)
            if idx > 0:
                # Regarde dans un contexte de 500 chars autour du nom
                ctx = html[max(0, idx-200):idx+200].lower()
                for status in INJURY_STATUSES:
                    if f">{status}<" in ctx or f'"{status}"' in ctx or f" {status} " in ctx:
                        result[name] = status
                        break
                if name not in result:
                    result[name] = "out"  # defaut si dans la section injuries

        return result

    def _get_multiplier(self, line: int, pp: int, is_defense: bool) -> float:
        """Retourne le multiplicateur selon le role."""
        line_capped = min(line, 4)

        if is_defense:
            if pp == 1:   return ROLE_MULTIPLIERS["defense_pp1"]
            if pp == 2:   return ROLE_MULTIPLIERS["defense_pp2"]
            return ROLE_MULTIPLIERS["defense_noPP"]

        pp_suffix = f"_pp{pp}" if pp in (1, 2) else "_noPP"
        key = f"line{line_capped}{pp_suffix}"
        return ROLE_MULTIPLIERS.get(key, 1.0)

    def build_role_summary(self, team_name: str) -> str:
        """Genere un resume lisible du lineup pour affichage."""
        lineup = self.get_lineup(team_name)
        if not lineup:
            return ""

        lines = []
        pp1 = lineup.get("pp1", [])
        pp2 = lineup.get("pp2", [])
        goalie = lineup.get("goalie", "")

        if goalie:
            lines.append(f"Gardien: {goalie}")

        # Lignes forwards
        forwards = lineup.get("forwards", [])
        for i in range(0, min(len(forwards), 12), 3):
            trio = forwards[i:i+3]
            line_num = trio[0]["line"] if trio else i//3+1
            names = " · ".join(p["name"] for p in trio)
            pp_tags = ""
            for p in trio:
                key = _normalize_name(p["name"])
                if p["name"] in pp1:
                    pp_tags += " [PP1]"
                elif p["name"] in pp2:
                    pp_tags += " [PP2]"
            lines.append(f"L{line_num}: {names}{pp_tags}")

        return " | ".join(lines)
