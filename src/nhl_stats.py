"""
NHL Stats Fetcher - API officielle NHL.com
Récupère les stats joueurs, gardiens, équipes, alignements, gardien partant.
Endpoint: https://api-web.nhle.com/v1
"""

import requests
from typing import Optional
from functools import lru_cache
import math

NHL_API = "https://api-web.nhle.com/v1"

SEASON = "20252026"
GAME_TYPE = "2"

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

ABBR_TO_NAME = {v: k for k, v in TEAM_ABBR.items()}


def _get(url: str, params: dict = None) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  NHL API: {url} -> {e}")
        return None


class TeamStats:
    def __init__(self):
        self._cache = {}

    def get(self, team_name: str) -> dict:
        abbr = TEAM_ABBR.get(team_name, "")
        if abbr in self._cache:
            return self._cache[abbr]

        data = _get(f"{NHL_API}/club-stats/{abbr}/now")
        if not data:
            return self._defaults()

        skaters = data.get("skaters", [])
        goalies = data.get("goalies", [])
        gp = max(data.get("gamesPlayed", 1), 1)

        standings = _get(f"{NHL_API}/standings/now")
        gf_pg = 3.1
        ga_pg = 3.1

        if standings:
            for s in standings.get("standings", []):
                if s.get("teamAbbrev", {}).get("default") == abbr:
                    gf = s.get("goalFor", 0)
                    ga = s.get("goalAgainst", 0)
                    sgp = max(s.get("gamesPlayed", 1), 1)
                    gf_pg = round(gf / sgp, 3)
                    ga_pg = round(ga / sgp, 3)
                    break

        team_record = data.get("teamRecord", {})
        pp_raw = team_record.get("powerPlayPct", 0.20)
        pk_raw = team_record.get("penaltyKillPct", 0.80)
        pp_pct = pp_raw * 100 if pp_raw < 1 else pp_raw
        pk_pct = pk_raw * 100 if pk_raw < 1 else pk_raw

        total_sf = sum(sk.get("shots", 0) for sk in skaters)
        shots_pg = round(total_sf / gp, 1) if gp > 0 else 30.0
        starter_sv_pct = self._starter_save_pct(goalies)

        result = {
            "abbr": abbr, "gf_pg": gf_pg, "ga_pg": ga_pg,
            "pp_pct": pp_pct, "pk_pct": pk_pct,
            "shots_pg": shots_pg, "shots_ag": 30.0,
            "starter_sv_pct": starter_sv_pct, "gp": gp,
        }
        self._cache[abbr] = result
        return result

    def _starter_save_pct(self, goalies: list) -> float:
        if not goalies:
            return 0.910
        starter = max(goalies, key=lambda g: g.get("gamesPlayed", 0))
        sv = starter.get("savePct", 0.910)
        return sv if sv > 0 else 0.910

    def _defaults(self) -> dict:
        return {
            "abbr": "", "gf_pg": 3.1, "ga_pg": 3.1,
            "pp_pct": 20.0, "pk_pct": 80.0,
            "shots_pg": 30.0, "shots_ag": 30.0,
            "starter_sv_pct": 0.910, "gp": 82,
        }


class PlayerStats:
    def __init__(self):
        self._cache = {}
        self._roster_cache = {}

    def get_skater(self, player_name: str, team_name: str, n_games: int = 10) -> dict:
        key = f"{player_name}_{team_name}"
        if key in self._cache:
            return self._cache[key]
        player_id = self._find_player_id(player_name, team_name)
        if not player_id:
            return self._skater_defaults()
        data = _get(f"{NHL_API}/player/{player_id}/game-log/{SEASON}/{GAME_TYPE}")
        if not data:
            return self._skater_defaults()
        logs = data.get("gameLog", [])[:n_games]
        if not logs:
            return self._skater_defaults()
        weights = [math.exp(-0.1 * i) for i in range(len(logs))]
        total_w = sum(weights)
        def wavg(field):
            return sum(logs[i].get(field, 0) * weights[i] for i in range(len(logs))) / total_w
        result = {
            "player_id": player_id,
            "shots_pg": round(wavg("shots"), 2),
            "goals_pg": round(wavg("goals"), 3),
            "assists_pg": round(wavg("assists"), 3),
            "points_pg": round(wavg("points"), 3),
            "toi_pg": round(wavg("toi"), 2),
            "hits_pg": round(wavg("hits"), 2),
            "blocks_pg": round(wavg("blockedShots"), 2),
            "pp_points_pg": round(wavg("powerPlayPoints"), 3),
            "n_games": len(logs),
            "shots_std": self._std([g.get("shots", 0) for g in logs]),
            "points_std": self._std([g.get("points", 0) for g in logs]),
        }
        self._cache[key] = result
        return result

    def get_goalie(self, player_name: str, team_name: str, n_games: int = 10) -> dict:
        key = f"goalie_{player_name}_{team_name}"
        if key in self._cache:
            return self._cache[key]
        player_id = self._find_player_id(player_name, team_name)
        if not player_id:
            return self._goalie_defaults()
        data = _get(f"{NHL_API}/player/{player_id}/game-log/{SEASON}/{GAME_TYPE}")
        if not data:
            return self._goalie_defaults()
        logs = data.get("gameLog", [])[:n_games]
        if not logs:
            return self._goalie_defaults()
        weights = [math.exp(-0.1 * i) for i in range(len(logs))]
        total_w = sum(weights)
        def wavg(field):
            return sum(logs[i].get(field, 0) * weights[i] for i in range(len(logs))) / total_w
        saves_list = [g.get("saves", 0) for g in logs]
        result = {
            "player_id": player_id,
            "saves_pg": round(wavg("saves"), 2),
            "shots_against_pg": round(wavg("shotsAgainst"), 2),
            "sv_pct": round(wavg("savePct"), 4) if wavg("savePct") > 0 else 0.910,
            "gaa": round(wavg("goalsAgainst"), 3),
            "saves_std": self._std(saves_list),
            "n_games": len(logs),
        }
        self._cache[key] = result
        return result

    def _find_player_id(self, name: str, team_name: str) -> Optional[int]:
        abbr = TEAM_ABBR.get(team_name, "")
        if not abbr:
            return None
        if abbr not in self._roster_cache:
            data = _get(f"{NHL_API}/roster/{abbr}/current")
            if data:
                self._roster_cache[abbr] = data
            else:
                return None
        roster = self._roster_cache[abbr]
        name_lower = name.lower().strip()
        for group in ["forwards", "defensemen", "goalies"]:
            for p in roster.get(group, []):
                fn = p.get("firstName", {}).get("default", "")
                ln = p.get("lastName", {}).get("default", "")
                full = f"{fn} {ln}".strip().lower()
                if full == name_lower or ln.lower() == name_lower:
                    return p.get("id")
        return None

    @staticmethod
    def _std(values: list) -> float:
        if len(values) < 2:
            return 1.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        return round(math.sqrt(variance), 3)

    @staticmethod
    def _skater_defaults() -> dict:
        return {
            "player_id": None, "shots_pg": 2.5, "goals_pg": 0.25,
            "assists_pg": 0.35, "points_pg": 0.60, "toi_pg": 1080,
            "hits_pg": 1.5, "blocks_pg": 0.8, "pp_points_pg": 0.15,
            "shots_std": 1.2, "points_std": 0.7, "n_games": 0,
        }

    @staticmethod
    def _goalie_defaults() -> dict:
        return {
            "player_id": None, "saves_pg": 26.0, "shots_against_pg": 28.5,
            "sv_pct": 0.910, "gaa": 2.85, "saves_std": 4.5, "n_games": 0,
        }


class LineupValidator:
    def __init__(self):
        self._roster_cache = {}
        self._starter_cache = {}

    def get_active_players(self, team_name: str) -> set:
        abbr = TEAM_ABBR.get(team_name, "")
        if not abbr or abbr in self._roster_cache:
            return self._roster_cache.get(abbr, set())
        data = _get(f"{NHL_API}/roster/{abbr}/current")
        if not data:
            return set()
        active = set()
        for group in ["forwards", "defensemen", "goalies"]:
            for p in data.get(group, []):
                if p.get("injuryStatus") in ("IR", "LTIR", "Day-to-Day", "Injured"):
                    continue
                fn = p.get("firstName", {}).get("default", "")
                ln = p.get("lastName", {}).get("default", "")
                full = f"{fn} {ln}".strip().lower()
                if full:
                    active.add(full)
        self._roster_cache[abbr] = active
        print(f"  Alignement {abbr}: {len(active)} joueurs actifs")
        return active

    def get_probable_starter(self, team_name: str) -> Optional[str]:
        from datetime import datetime
        import pytz
        abbr = TEAM_ABBR.get(team_name, "")
        if abbr in self._starter_cache:
            return self._starter_cache[abbr]
        today = datetime.now(pytz.timezone("America/Toronto")).strftime("%Y-%m-%d")
        schedule = _get(f"{NHL_API}/schedule/{today}")
        if schedule:
            for day in schedule.get("gameWeek", []):
                for game in day.get("games", []):
                    for side in ["homeTeam", "awayTeam"]:
                        t = game.get(side, {})
                        if t.get("abbrev") == abbr:
                            starter = game.get(f"{side[:-4]}StartingGoalie", {})
                            if starter:
                                fn = starter.get("firstName", {}).get("default", "")
                                ln = starter.get("lastName", {}).get("default", "")
                                name = f"{fn} {ln}".strip()
                                if name:
                                    self._starter_cache[abbr] = name
                                    return name
        roster = _get(f"{NHL_API}/roster/{abbr}/current")
        if roster:
            goalies = roster.get("goalies", [])
            if goalies:
                starter = max(goalies, key=lambda g: g.get("gamesPlayed", 0) if isinstance(g.get("gamesPlayed"), int) else 0)
                fn = starter.get("firstName", {}).get("default", "")
                ln = starter.get("lastName", {}).get("default", "")
                name = f"{fn} {ln}".strip()
                if name:
                    self._starter_cache[abbr] = name
                    return name
        return None

    def is_back_to_back(self, team_name: str, game_date: str) -> bool:
        from datetime import datetime, timedelta
        abbr = TEAM_ABBR.get(team_name, "")
        if not abbr:
            return False
        try:
            dt = datetime.strptime(game_date, "%Y-%m-%d")
            yesterday = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception:
            return False
        data = _get(f"{NHL_API}/schedule/{yesterday}")
        if not data:
            return False
        for day in data.get("gameWeek", []):
            for game in day.get("games", []):
                for side in ["homeTeam", "awayTeam"]:
                    if game.get(side, {}).get("abbrev") == abbr:
                        print(f"  Back-to-back: {abbr}")
                        return True
        return False
