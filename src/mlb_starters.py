"""
MLB Probable Starters — MLB Stats API officielle (gratuite, aucune clé requise)
Endpoint: https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=YYYY-MM-DD&hydrate=probablePitcher

Retourne un dict: {(home_team, away_team): {"home": "Nom Lanceur", "away": "Nom Lanceur"}}
Les noms sont normalisés pour matcher MLB_PITCHERS.
"""

import requests
from datetime import datetime
import pytz
import re

MLB_API = "https://statsapi.mlb.com/api/v1/schedule"

# Mapping MLB API team name → nom utilisé dans MLB_PITCHERS / Odds API
TEAM_NAME_MAP = {
    "Arizona Diamondbacks":    "Arizona Diamondbacks",
    "Atlanta Braves":          "Atlanta Braves",
    "Baltimore Orioles":       "Baltimore Orioles",
    "Boston Red Sox":          "Boston Red Sox",
    "Chicago Cubs":            "Chicago Cubs",
    "Chicago White Sox":       "Chicago White Sox",
    "Cincinnati Reds":         "Cincinnati Reds",
    "Cleveland Guardians":     "Cleveland Guardians",
    "Colorado Rockies":        "Colorado Rockies",
    "Detroit Tigers":          "Detroit Tigers",
    "Houston Astros":          "Houston Astros",
    "Kansas City Royals":      "Kansas City Royals",
    "Los Angeles Angels":      "Los Angeles Angels",
    "Los Angeles Dodgers":     "Los Angeles Dodgers",
    "Miami Marlins":           "Miami Marlins",
    "Milwaukee Brewers":       "Milwaukee Brewers",
    "Minnesota Twins":         "Minnesota Twins",
    "New York Mets":           "New York Mets",
    "New York Yankees":        "New York Yankees",
    "Athletics":               "Oakland Athletics",
    "Oakland Athletics":       "Oakland Athletics",
    "Philadelphia Phillies":   "Philadelphia Phillies",
    "Pittsburgh Pirates":      "Pittsburgh Pirates",
    "San Diego Padres":        "San Diego Padres",
    "San Francisco Giants":    "San Francisco Giants",
    "Seattle Mariners":        "Seattle Mariners",
    "St. Louis Cardinals":     "St. Louis Cardinals",
    "Tampa Bay Rays":          "Tampa Bay Rays",
    "Texas Rangers":           "Texas Rangers",
    "Toronto Blue Jays":       "Toronto Blue Jays",
    "Washington Nationals":    "Washington Nationals",
}


_cache = {}  # date_str -> starters dict


def fetch_probable_starters(date_str: str = None) -> dict:
    """
    Retourne {(home_team, away_team): {"home": str|None, "away": str|None}}
    pour tous les matchs MLB de la date donnée (format YYYY-MM-DD).
    Si date_str est None, utilise aujourd'hui (heure ET).
    """
    if date_str is None:
        tz = pytz.timezone("America/Toronto")
        date_str = datetime.now(tz).strftime("%Y-%m-%d")

    if date_str in _cache:
        return _cache[date_str]

    try:
        r = requests.get(MLB_API, params={
            "sportId": 1,
            "date": date_str,
            "hydrate": "probablePitcher",
        }, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [MLB Starters] Erreur API: {e}")
        return {}

    result = {}
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            teams = game.get("teams", {})
            home_info = teams.get("home", {})
            away_info = teams.get("away", {})

            home_team = TEAM_NAME_MAP.get(
                home_info.get("team", {}).get("name", ""), None
            )
            away_team = TEAM_NAME_MAP.get(
                away_info.get("team", {}).get("name", ""), None
            )
            if not home_team or not away_team:
                continue

            home_p = home_info.get("probablePitcher", {})
            away_p = away_info.get("probablePitcher", {})

            home_name = home_p.get("fullName") if home_p else None
            away_name = away_p.get("fullName") if away_p else None

            result[(home_team, away_team)] = {
                "home": home_name,
                "away": away_name,
            }
            # Index aussi par (away, home) pour recherche dans les deux sens
            result[(away_team, home_team)] = {
                "home": away_name,   # du point de vue inversé
                "away": home_name,
            }

    print(f"  [MLB Starters] {len(result)//2} matchs, partants chargés depuis MLB API")
    _cache[date_str] = result
    return result


def get_starter_for_team(team: str, opponent: str, starters: dict):
    """
    Retourne le nom du partant de `team` dans le match team vs opponent.
    Cherche dans les deux ordres (home/away).
    """
    # Essai (team=home, opponent=away)
    entry = starters.get((team, opponent))
    if entry:
        return entry.get("home")

    # Essai (team=away, opponent=home)
    entry = starters.get((opponent, team))
    if entry:
        return entry.get("away")

    return None


_lineup_cache = {}  # date_str -> {team_name: set of player last names}
_lineup_fetch_count = {}  # date_str -> nb de fois fetchee (pour invalider cache si lineups en cours)


def fetch_confirmed_lineups(date_str: str = None, force_refresh: bool = False) -> dict:
    """
    Retourne {team_name: set(last_names)} pour tous les matchs MLB du jour.
    Utilise hydrate=lineups de l'API officielle MLB.
    Si le lineup n'est pas encore posté, retourne un set vide pour cette equipe.
    """
    if date_str is None:
        tz = pytz.timezone("America/Toronto")
        date_str = datetime.now(tz).strftime("%Y-%m-%d")

    if date_str in _lineup_cache and not force_refresh:
        return _lineup_cache[date_str]

    result = {}
    try:
        r = requests.get(MLB_API, params={
            "sportId": 1,
            "date": date_str,
            "hydrate": "lineups",
        }, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [MLB Lineups] Erreur API: {e}")
        _lineup_cache[date_str] = result
        return result

    total_lineups = 0
    for date_entry in data.get("dates", []):
        for game in date_entry.get("games", []):
            teams = game.get("teams", {})
            home_name = TEAM_NAME_MAP.get(teams.get("home", {}).get("team", {}).get("name", ""))
            away_name = TEAM_NAME_MAP.get(teams.get("away", {}).get("team", {}).get("name", ""))
            lineups = game.get("lineups", {})
            home_players = lineups.get("homePlayers", [])
            away_players = lineups.get("awayPlayers", [])
            if home_name and home_players:
                result[home_name] = {p.get("fullName", "").split()[-1].lower() for p in home_players}
                total_lineups += 1
            if away_name and away_players:
                result[away_name] = {p.get("fullName", "").split()[-1].lower() for p in away_players}
                total_lineups += 1

    print(f"  [MLB Lineups] {total_lineups} lineups confirmes")
    _lineup_cache[date_str] = result
    return result


def is_in_lineup(player_name: str, team: str, lineups: dict) -> bool:
    """
    Retourne True si le joueur est dans le lineup confirme de son equipe.
    Retourne True aussi si le lineup n'est pas encore disponible (evite faux negatifs).
    """
    team_lineup = lineups.get(team)
    if not team_lineup:
        return True  # lineup pas encore posté — on inclut par défaut
    last = player_name.split()[-1].lower()
    return last in team_lineup


if __name__ == "__main__":
    starters = fetch_probable_starters()
    for matchup, pitchers in starters.items():
        if matchup[0] < matchup[1]:  # évite les doublons
            print(f"  {matchup[1]} @ {matchup[0]}: "
                  f"away={pitchers['away'] or 'TBD'} / home={pitchers['home'] or 'TBD'}")
