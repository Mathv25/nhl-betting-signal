"""
Lineup Checker — Validation alignements NHL.com
Verifie les joueurs actifs par equipe via roster API
"""

import requests
import time

NHL_API = "https://api-web.nhle.com/v1"

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


def _get(url):
    time.sleep(0.3)
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  ⚠️  NHL lineup API: {e}")
        return None


class LineupChecker:

    def __init__(self):
        self._roster_cache = {}   # abbr -> raw roster dict (partage avec props_an et lf_fetcher)
        self._active_cache = {}   # abbr -> set of active player names (lowercase)

    def validate_players(self, games: list) -> list:
        """
        Pour chaque match, fetch le roster des deux equipes.
        Retire les joueurs IR/LTIR des props.
        Retourne les games avec prop lists filtrees.
        """
        teams = set()
        for g in games:
            teams.add(g.get("home_team", ""))
            teams.add(g.get("away_team", ""))

        for team in sorted(teams):
            if not team:
                continue
            abbr = TEAM_ABBR.get(team, "")
            if not abbr:
                continue
            if abbr in self._roster_cache:
                continue

            data = _get(f"{NHL_API}/roster/{abbr}/current")
            if not data:
                print(f"  ⚠️  Impossible de valider l'alignement — toutes les props conservées")
                continue

            self._roster_cache[abbr] = data

            # Construire le set des joueurs actifs
            active = set()
            for group in ["forwards", "defensemen", "goalies"]:
                for p in data.get(group, []):
                    status = p.get("injuryStatus", "")
                    if status in ("IR", "LTIR"):
                        continue
                    fn   = p.get("firstName", {}).get("default", "")
                    ln   = p.get("lastName",  {}).get("default", "")
                    name = f"{fn} {ln}".strip().lower()
                    if name:
                        active.add(name)

            self._active_cache[abbr] = active
            print(f"  ✅ Alignement {abbr}: {len(active)} joueurs actifs")

        return games

    def get_active_players(self, team_name: str) -> set:
        abbr = TEAM_ABBR.get(team_name, "")
        return self._active_cache.get(abbr, set())

    def is_active(self, player_name: str, team_name: str) -> bool:
        return player_name.lower().strip() in self.get_active_players(team_name)
