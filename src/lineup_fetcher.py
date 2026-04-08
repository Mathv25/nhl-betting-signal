"""
Lineup Fetcher — Daily Faceoff via requests avec fallback NHL API
Recupere PP1/PP2/lignes pour ajuster les projections
"""

import requests
import time
import re
from typing import Optional

BASE_URL = "https://www.dailyfaceoff.com/teams/{slug}/line-combinations"

ROLE_MULTIPLIERS = {
    "line1_pp1": 1.35, "line1_pp2": 1.20, "line1_noPP": 1.10,
    "line2_pp1": 1.25, "line2_pp2": 1.12, "line2_noPP": 1.00,
    "line3_pp1": 1.15, "line3_pp2": 1.05, "line3_noPP": 0.88,
    "line4_pp1": 1.10, "line4_pp2": 1.00, "line4_noPP": 0.72,
    "defense_pp1": 1.20, "defense_pp2": 1.05, "defense_noPP": 0.90,
}

TEAM_SLUGS = {
    "Anaheim Ducks":"anaheim-ducks","Boston Bruins":"boston-bruins",
    "Buffalo Sabres":"buffalo-sabres","Calgary Flames":"calgary-flames",
    "Carolina Hurricanes":"carolina-hurricanes","Chicago Blackhawks":"chicago-blackhawks",
    "Colorado Avalanche":"colorado-avalanche","Columbus Blue Jackets":"columbus-blue-jackets",
    "Dallas Stars":"dallas-stars","Detroit Red Wings":"detroit-red-wings",
    "Edmonton Oilers":"edmonton-oilers","Florida Panthers":"florida-panthers",
    "Los Angeles Kings":"los-angeles-kings","Minnesota Wild":"minnesota-wild",
    "Montreal Canadiens":"montreal-canadiens","Montréal Canadiens":"montreal-canadiens",
    "Nashville Predators":"nashville-predators","New Jersey Devils":"new-jersey-devils",
    "New York Islanders":"new-york-islanders","New York Rangers":"new-york-rangers",
    "Ottawa Senators":"ottawa-senators","Philadelphia Flyers":"philadelphia-flyers",
    "Pittsburgh Penguins":"pittsburgh-penguins","San Jose Sharks":"san-jose-sharks",
    "Seattle Kraken":"seattle-kraken","St. Louis Blues":"st-louis-blues",
    "St Louis Blues":"st-louis-blues","Tampa Bay Lightning":"tampa-bay-lightning",
    "Toronto Maple Leafs":"toronto-maple-leafs","Utah Mammoth":"utah-mammoth",
    "Vancouver Canucks":"vancouver-canucks","Vegas Golden Knights":"vegas-golden-knights",
    "Washington Capitals":"washington-capitals","Winnipeg Jets":"winnipeg-jets",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

INJURY_STATUSES = {"ir", "out", "dtd", "gtd"}


def _normalize(name: str) -> str:
    return name.lower().strip()


class LineupFetcher:

    def __init__(self):
        self._cache = {}

    def get_lineup(self, team_name: str) -> dict:
        if team_name in self._cache:
            return self._cache[team_name]

        slug = TEAM_SLUGS.get(team_name, "")
        if not slug:
            return {}

        data = self._fetch_dailyfaceoff(slug, team_name)

        if not data or not data.get("player_roles"):
            # Fallback: lineup par defaut (multiplicateur 1.0 pour tous)
            print(f"  ⚠️  Lineup DF {team_name}: scraping bloque, fallback mode")
            data = {"player_roles": {}, "injuries": {}, "goalie": "", "pp1": [], "pp2": [], "forwards": [], "defense": []}

        self._cache[team_name] = data
        n_fwd = len(data.get("forwards", []))
        n_pp1 = len(data.get("pp1", []))
        print(f"  ✅ Lineup DF {team_name}: {n_fwd} fwd · PP1: {n_pp1} joueurs")
        return data

    def get_player_role(self, player_name: str, team: str) -> dict:
        lineup = self.get_lineup(team)
        roles = lineup.get("player_roles", {})
        key = _normalize(player_name)
        return roles.get(key, {"multiplier": 1.0, "pp": 0, "line": 2, "is_defense": False})

    def is_injured(self, player_name: str, team: str) -> bool:
        lineup = self.get_lineup(team)
        injuries = lineup.get("injuries", {})
        return injuries.get(_normalize(player_name), "") in {"ir", "out"}

    def _fetch_dailyfaceoff(self, slug: str, team_name: str) -> dict:
        url = BASE_URL.format(slug=slug)
        time.sleep(1.5)
        try:
            session = requests.Session()
            # Premier appel pour obtenir les cookies
            session.get("https://www.dailyfaceoff.com/", headers=HEADERS, timeout=10)
            time.sleep(0.5)
            r = session.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                return {}
            html = r.text
            if len(html) < 5000 or "players/news" not in html:
                return {}
            return self._parse(html)
        except Exception as e:
            print(f"  ⚠️  DF {team_name}: {e}")
            return {}

    def _parse(self, html: str) -> dict:
        section_titles = [
            "Forwards", "Defensive Pairings",
            "1st Powerplay Unit", "2nd Powerplay Unit",
            "1st Penalty Kill Unit", "2nd Penalty Kill Unit",
            "Goalies", "Injuries",
        ]

        player_re = re.compile(
            r'href="/players/news/[^"/]+/\d+">([^<]{3,40})</a>',
            re.IGNORECASE
        )

        sections = {t: [] for t in section_titles}

        # Trouve la position de chaque section dans le HTML
        positions = []
        for title in section_titles:
            for pat in [f">{title}<", f'"{title}"', f" {title}<"]:
                idx = html.find(pat)
                if idx >= 0:
                    positions.append((idx, title))
                    break

        positions.sort()

        if not positions:
            return {}

        # Extrait les joueurs par section
        for i, (pos, title) in enumerate(positions):
            end = positions[i+1][0] if i+1 < len(positions) else pos + 8000
            segment = html[pos:end]
            names = []
            for name in player_re.findall(segment):
                name = name.strip()
                if (len(name) >= 3 and name not in section_titles
                        and "Faceoff" not in name and "Copyright" not in name
                        and name not in names):
                    names.append(name)
            sections[title] = names

        # Construction des structures
        forwards = []
        for i, name in enumerate(sections["Forwards"]):
            line_num = (i // 3) + 1
            pos_map  = ["LW", "C", "RW"]
            forwards.append({"name": name, "line": line_num, "pos": pos_map[i % 3]})

        defense = []
        for i, name in enumerate(sections["Defensive Pairings"]):
            defense.append({"name": name, "pair": (i // 2) + 1, "pos": "LD" if i%2==0 else "RD"})

        pp1     = sections["1st Powerplay Unit"]
        pp2     = sections["2nd Powerplay Unit"]
        goalies = sections["Goalies"]
        goalie  = goalies[0] if goalies else ""

        # Injuries
        injuries = {}
        for name in sections["Injuries"]:
            key = _normalize(name)
            idx = html.find(name)
            if idx >= 0:
                ctx = html[max(0, idx-200):idx+100].lower()
                for status in INJURY_STATUSES:
                    if f">{status}<" in ctx or f'"{status}"' in ctx:
                        injuries[key] = status
                        break
                if key not in injuries:
                    injuries[key] = "out"

        # Player roles
        pp1_set = {_normalize(n) for n in pp1}
        pp2_set = {_normalize(n) for n in pp2}
        player_roles = {}

        for p in forwards:
            key = _normalize(p["name"])
            pp  = 1 if key in pp1_set else (2 if key in pp2_set else 0)
            player_roles[key] = {
                "name": p["name"], "line": p["line"], "pp": pp,
                "pos": p["pos"], "is_defense": False,
                "multiplier": self._mult(p["line"], pp, False),
            }

        for p in defense:
            key = _normalize(p["name"])
            pp  = 1 if key in pp1_set else (2 if key in pp2_set else 0)
            player_roles[key] = {
                "name": p["name"], "line": p["pair"], "pp": pp,
                "pos": p["pos"], "is_defense": True,
                "multiplier": self._mult(p["pair"], pp, True),
            }

        return {
            "forwards": forwards, "defense": defense,
            "pp1": pp1, "pp2": pp2,
            "injuries": injuries, "goalie": goalie,
            "player_roles": player_roles,
        }

    def _mult(self, line: int, pp: int, is_defense: bool) -> float:
        line = min(line, 4)
        if is_defense:
            if pp == 1: return ROLE_MULTIPLIERS["defense_pp1"]
            if pp == 2: return ROLE_MULTIPLIERS["defense_pp2"]
            return ROLE_MULTIPLIERS["defense_noPP"]
        suffix = f"_pp{pp}" if pp in (1, 2) else "_noPP"
        return ROLE_MULTIPLIERS.get(f"line{line}{suffix}", 1.0)
