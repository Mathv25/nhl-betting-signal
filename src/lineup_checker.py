"""
Vérifie les alignements et blessures NHL via NHL.com API officielle.
Évite les props sur des joueurs absents (scratches, blessés, IR).
"""

import requests
from typing import Optional


NHL_API = "https://api-web.nhle.com/v1"


class LineupChecker:
    def __init__(self):
        self._injury_cache = {}
        self._lineup_cache = {}

    def validate_players(self, games: list) -> list:
        """
        Pour chaque match, récupère les alignements et marque
        les props sur joueurs absents comme invalides.
        """
        for game in games:
            home = game["home_team"]
            away = game["away_team"]

            home_lineup = self._get_lineup(home)
            away_lineup = self._get_lineup(away)

            active_players = home_lineup | away_lineup

            props = game["markets"].get("player_props", [])
            valid_props = []
            removed = []

            for prop in props:
                player_name = prop.get("player", "")
                if self._is_player_active(player_name, active_players):
                    valid_props.append(prop)
                else:
                    removed.append(player_name)
                    print(f"  ❌ Prop retirée: {player_name} (absent/blessé/scratch)")

            game["markets"]["player_props"] = valid_props
            game["removed_props"] = removed

            if removed:
                print(f"  → {len(removed)} prop(s) supprimée(s) pour {home} vs {away}")

        return games

    def _get_lineup(self, team_name: str) -> set:
        """
        Récupère les joueurs actifs d'une équipe via l'API NHL officielle.
        Retourne un set de noms de joueurs confirmés actifs.
        """
        if team_name in self._lineup_cache:
            return self._lineup_cache[team_name]

        team_abbr = self._name_to_abbr(team_name)
        if not team_abbr:
            return set()

        try:
            # Roster actif de l'équipe
            url = f"{NHL_API}/roster/{team_abbr}/current"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            active = set()
            for group in ["forwards", "defensemen", "goalies"]:
                for player in data.get(group, []):
                    fname = player.get("firstName", {}).get("default", "")
                    lname = player.get("lastName", {}).get("default", "")
                    full = f"{fname} {lname}".strip()
                    if full:
                        active.add(full.lower())

            # Retire les joueurs sur la liste des blessés
            injured = self._get_injured(team_abbr)
            active -= injured

            self._lineup_cache[team_name] = active
            print(f"  ✅ Alignement {team_abbr}: {len(active)} joueurs actifs")
            return active

        except Exception as e:
            print(f"  ⚠️  Impossible de récupérer l'alignement de {team_name}: {e}")
            return set()

    def _get_injured(self, team_abbr: str) -> set:
        """Récupère les joueurs blessés/IR via NHL API."""
        if team_abbr in self._injury_cache:
            return self._injury_cache[team_abbr]
        try:
            url = f"{NHL_API}/roster/{team_abbr}/current"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            injured = set()
            # L'API NHL indique le statut injury dans le roster
            for group in ["forwards", "defensemen", "goalies"]:
                for player in data.get(group, []):
                    if player.get("injuryStatus") in ["IR", "LTIR", "Day-to-Day", "Injured"]:
                        fname = player.get("firstName", {}).get("default", "")
                        lname = player.get("lastName", {}).get("default", "")
                        injured.add(f"{fname} {lname}".strip().lower())
            self._injury_cache[team_abbr] = injured
            return injured
        except Exception:
            return set()

    def _is_player_active(self, player_name: str, active_players: set) -> bool:
        """Vérifie si un joueur est dans l'alignement actif."""
        if not player_name or not active_players:
            return True  # On garde si on ne peut pas valider
        return player_name.lower() in active_players

    def _name_to_abbr(self, full_name: str) -> Optional[str]:
        """Convertit le nom complet d'une équipe en abréviation NHL."""
        mapping = {
            "Anaheim Ducks": "ANA", "Boston Bruins": "BOS", "Buffalo Sabres": "BUF",
            "Calgary Flames": "CGY", "Carolina Hurricanes": "CAR", "Chicago Blackhawks": "CHI",
            "Colorado Avalanche": "COL", "Columbus Blue Jackets": "CBJ", "Dallas Stars": "DAL",
            "Detroit Red Wings": "DET", "Edmonton Oilers": "EDM", "Florida Panthers": "FLA",
            "Los Angeles Kings": "LAK", "Minnesota Wild": "MIN", "Montreal Canadiens": "MTL",
            "Nashville Predators": "NSH", "New Jersey Devils": "NJD", "New York Islanders": "NYI",
            "New York Rangers": "NYR", "Ottawa Senators": "OTT", "Philadelphia Flyers": "PHI",
            "Pittsburgh Penguins": "PIT", "San Jose Sharks": "SJS", "Seattle Kraken": "SEA",
            "St. Louis Blues": "STL", "Tampa Bay Lightning": "TBL", "Toronto Maple Leafs": "TOR",
            "Vancouver Canucks": "VAN", "Vegas Golden Knights": "VGK", "Washington Capitals": "WSH",
            "Winnipeg Jets": "WPG",
        }
        return mapping.get(full_name)
