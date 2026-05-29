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
_active_roster_cache = {}  # team_name -> set of (last_lower, full_lower)

# Mapping nom équipe → team ID MLB Stats API
TEAM_ID_MAP = {
    "Arizona Diamondbacks":  109,
    "Atlanta Braves":        144,
    "Baltimore Orioles":     110,
    "Boston Red Sox":        111,
    "Chicago Cubs":          112,
    "Chicago White Sox":     145,
    "Cincinnati Reds":       113,
    "Cleveland Guardians":   114,
    "Colorado Rockies":      115,
    "Detroit Tigers":        116,
    "Houston Astros":        117,
    "Kansas City Royals":    118,
    "Los Angeles Angels":    108,
    "Los Angeles Dodgers":   119,
    "Miami Marlins":         146,
    "Milwaukee Brewers":     158,
    "Minnesota Twins":       142,
    "New York Mets":         121,
    "New York Yankees":      147,
    "Oakland Athletics":     133,
    "Philadelphia Phillies": 143,
    "Pittsburgh Pirates":    134,
    "San Diego Padres":      135,
    "San Francisco Giants":  137,
    "Seattle Mariners":      136,
    "St. Louis Cardinals":   138,
    "Tampa Bay Rays":        139,
    "Texas Rangers":         140,
    "Toronto Blue Jays":     141,
    "Washington Nationals":  120,
}


def fetch_active_roster(team_name: str) -> set:
    """
    Retourne un set de {last_lower, full_lower} des joueurs sur le roster ACTIF de l'équipe.
    Les joueurs sur IL ne sont pas dans le roster actif.
    Cache par équipe (valide pour la durée de l'exécution).
    """
    if team_name in _active_roster_cache:
        return _active_roster_cache[team_name]

    team_id = TEAM_ID_MAP.get(team_name)
    if not team_id:
        return set()

    try:
        r = requests.get(
            f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster/active",
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        roster = data.get("roster", [])
        names = set()
        for p in roster:
            full = p.get("person", {}).get("fullName", "")
            if full:
                names.add(full.lower())
                names.add(full.split()[-1].lower())
        print(f"  [MLB Roster] {team_name}: {len(roster)} joueurs actifs")
        _active_roster_cache[team_name] = names
        return names
    except Exception as e:
        print(f"  [MLB Roster] Erreur {team_name}: {e}")
        _active_roster_cache[team_name] = set()
        return set()


def is_on_active_roster(player_name: str, team_name: str) -> bool:
    """
    Retourne True si le joueur est sur le roster actif de son équipe.
    Retourne True aussi si l'équipe n'est pas connue (évite les faux négatifs).
    """
    roster = fetch_active_roster(team_name)
    if not roster:
        return True  # équipe inconnue — on laisse passer
    last = player_name.split()[-1].lower()
    full = player_name.lower()
    return last in roster or full in roster


def fetch_inactive_players(date_str: str = None) -> set:
    """
    Rétrocompat — retourne toujours un set vide.
    Le vrai check se fait via is_on_active_roster() maintenant.
    """
    return set()


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
