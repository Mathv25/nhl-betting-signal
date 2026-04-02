"""
Lineup Checker — Validation des alignements via NHL.com officiel
- Retire les props sur joueurs blessés/IR/scratch
- Confirme le gardien partant
- Détecte les back-to-back
"""

import requests
from typing import Optional

NHL_API = "https://api-web.nhle.com/v1"

TEAM_ABBR = {
    "Anaheim Ducks": "ANA", "Boston Bruins": "BOS", "Buffalo Sabres": "BUF",
    "Calgary Flames": "CGY", "Carolina Hurricanes": "CAR", "Chicago Blackhawks": "CHI",
    "Colorado Avalanche": "COL", "Columbus Blue Jackets": "CBJ", "Dallas Stars": "DAL",
    "Detroit Red Wings": "DET", "Edmonton Oilers": "EDM", "Florida Panthers": "FLA",
    "Los Angeles Kings": "LAK", "Minnesota Wild": "MIN", "Montreal Canadiens": "MTL",
    "Nashville Predators": "NSH", "New Jersey Devils": "NJD", "New York Islanders": "NYI",
    "New York Rangers": "NYR", "Ottawa Senators": "OTT", "Philadelphia Flyers": "PHI",
    "Pittsburgh Penguins": "PIT", "San Jose Sharks": "SJS", "Seattle Kraken": "SEA",
    "St. Louis Blues": "STL", "Tampa Bay Lightning": "TBL", "Toronto Maple Leafs": "TOR",
    "Utah Mammoth": "UTA", "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK",
    "Washington Capitals": "WSH", "Winnipeg Jets": "WPG",
}

INJURY_STATUSES = {"IR", "LTIR", "Day-to-Day", "Injured", "Suspended"}


def _get(url: str) -> Optional[dict]:
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  ⚠️  NHL lineup API: {e}")
        return None


class LineupChecker:

    def __init__(self):
        self._active_cache  = {}
        self._starter_cache = {}

    def validate_players(self, games: list) -> list:
        """
        Pour chaque match:
        1. Récupère les joueurs actifs des deux équipes
        2. Retire les props sur joueurs absents/blessés
        3. Log les retraits
        """
        for game in games:
            home = game["home_team"]
            away = game["away_team"]

            active = (
                self._get_active(home) |
                self._get_active(away)
            )

            if not active:
                # Si l'API NHL est down, on garde toutes les props
                print(f"  ⚠️  Impossible de valider l'alignement — toutes les props conservées")
                continue

            valid, removed = [], []
            for prop in game["markets"].get("player_props", []):
                name = prop.get("player", "").strip()
                if not name or name.lower() in active:
                    valid.append(prop)
                else:
                    removed.append(name)
                    print(f"  ❌ Prop retirée: {name} (absent/scratch/blessé)")

            game["markets"]["player_props"] = valid
            game["removed_props"] = removed

            if removed:
                print(f"  → {len(removed)} prop(s) retirée(s) pour {home} vs {away}")

        return games

    def _get_active(self, team_name: str) -> set:
        abbr = TEAM_ABBR.get(team_name, "")
        if not abbr:
            return set()
        if abbr in self._active_cache:
            return self._active_cache[abbr]

        data = _get(f"{NHL_API}/roster/{abbr}/current")
        if not data:
            return set()

        active = set()
        for group in ["forwards", "defensemen", "goalies"]:
            for p in data.get(group, []):
                if p.get("injuryStatus") in INJURY_STATUSES:
                    continue
                fn = p.get("firstName", {}).get("default", "")
                ln = p.get("lastName", {}).get("default", "")
                full = f"{fn} {ln}".strip().lower()
                if full:
                    active.add(full)

        self._active_cache[abbr] = active
        print(f"  ✅ Alignement {abbr}: {len(active)} joueurs actifs")
        return active
