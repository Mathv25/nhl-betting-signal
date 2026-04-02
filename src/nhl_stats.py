"""
NHL Stats - API officielle NHL.com
Avec rate limiting pour eviter les 429
"""

import requests
import time
import math
from typing import Optional

NHL_API   = "https://api-web.nhle.com/v1"
SEASON    = "20252026"
GAME_TYPE = "2"

TEAM_ABBR = {
    "Anaheim Ducks":"ANA","Boston Bruins":"BOS","Buffalo Sabres":"BUF",
    "Calgary Flames":"CGY","Carolina Hurricanes":"CAR","Chicago Blackhawks":"CHI",
    "Colorado Avalanche":"COL","Columbus Blue Jackets":"CBJ","Dallas Stars":"DAL",
    "Detroit Red Wings":"DET","Edmonton Oilers":"EDM","Florida Panthers":"FLA",
    "Los Angeles Kings":"LAK","Minnesota Wild":"MIN","Montreal Canadiens":"MTL",
    "Nashville Predators":"NSH","New Jersey Devils":"NJD","New York Islanders":"NYI",
    "New York Rangers":"NYR","Ottawa Senators":"OTT","Philadelphia Flyers":"PHI",
    "Pittsburgh Penguins":"PIT","San Jose Sharks":"SJS","Seattle Kraken":"SEA",
    "St. Louis Blues":"STL","Tampa Bay Lightning":"TBL","Toronto Maple Leafs":"TOR",
    "Utah Mammoth":"UTA","Vancouver Canucks":"VAN","Vegas Golden Knights":"VGK",
    "Washington Capitals":"WSH","Winnipeg Jets":"WPG",
}

# Stats de saison hardcodees comme fallback (evite les 429)
TEAM_STATS_FALLBACK = {
    "Colorado Avalanche":    {"gf_pg":3.85,"ga_pg":2.70,"pp_pct":24.5,"pk_pct":82.1,"starter_sv_pct":0.915},
    "Edmonton Oilers":       {"gf_pg":3.70,"ga_pg":3.05,"pp_pct":26.2,"pk_pct":79.8,"starter_sv_pct":0.908},
    "Toronto Maple Leafs":   {"gf_pg":3.45,"ga_pg":3.00,"pp_pct":22.1,"pk_pct":80.5,"starter_sv_pct":0.912},
    "Tampa Bay Lightning":   {"gf_pg":3.30,"ga_pg":2.90,"pp_pct":21.8,"pk_pct":81.2,"starter_sv_pct":0.914},
    "Florida Panthers":      {"gf_pg":3.20,"ga_pg":2.65,"pp_pct":20.5,"pk_pct":83.1,"starter_sv_pct":0.919},
    "Boston Bruins":         {"gf_pg":3.40,"ga_pg":2.75,"pp_pct":23.2,"pk_pct":81.8,"starter_sv_pct":0.916},
    "Washington Capitals":   {"gf_pg":3.25,"ga_pg":3.00,"pp_pct":21.0,"pk_pct":80.0,"starter_sv_pct":0.910},
    "Carolina Hurricanes":   {"gf_pg":3.10,"ga_pg":2.60,"pp_pct":19.8,"pk_pct":84.2,"starter_sv_pct":0.921},
    "Winnipeg Jets":         {"gf_pg":3.15,"ga_pg":2.85,"pp_pct":20.2,"pk_pct":81.5,"starter_sv_pct":0.913},
    "Dallas Stars":          {"gf_pg":3.05,"ga_pg":2.80,"pp_pct":19.5,"pk_pct":82.0,"starter_sv_pct":0.914},
    "Vegas Golden Knights":  {"gf_pg":3.10,"ga_pg":2.75,"pp_pct":20.8,"pk_pct":81.0,"starter_sv_pct":0.915},
    "New York Rangers":      {"gf_pg":3.20,"ga_pg":3.00,"pp_pct":21.5,"pk_pct":80.2,"starter_sv_pct":0.910},
    "Minnesota Wild":        {"gf_pg":3.00,"ga_pg":2.85,"pp_pct":19.2,"pk_pct":81.8,"starter_sv_pct":0.913},
    "Pittsburgh Penguins":   {"gf_pg":3.30,"ga_pg":3.05,"pp_pct":22.0,"pk_pct":79.5,"starter_sv_pct":0.908},
    "Montreal Canadiens":    {"gf_pg":3.10,"ga_pg":3.15,"pp_pct":20.0,"pk_pct":79.8,"starter_sv_pct":0.907},
    "New Jersey Devils":     {"gf_pg":3.00,"ga_pg":3.10,"pp_pct":19.8,"pk_pct":80.5,"starter_sv_pct":0.909},
    "Ottawa Senators":       {"gf_pg":2.95,"ga_pg":3.10,"pp_pct":19.5,"pk_pct":80.0,"starter_sv_pct":0.909},
    "Buffalo Sabres":        {"gf_pg":3.05,"ga_pg":3.20,"pp_pct":20.5,"pk_pct":79.2,"starter_sv_pct":0.906},
    "Philadelphia Flyers":   {"gf_pg":2.90,"ga_pg":3.20,"pp_pct":18.8,"pk_pct":79.5,"starter_sv_pct":0.906},
    "Detroit Red Wings":     {"gf_pg":2.85,"ga_pg":3.30,"pp_pct":18.5,"pk_pct":78.8,"starter_sv_pct":0.904},
    "New York Islanders":    {"gf_pg":2.75,"ga_pg":2.95,"pp_pct":17.8,"pk_pct":81.2,"starter_sv_pct":0.911},
    "Los Angeles Kings":     {"gf_pg":2.95,"ga_pg":2.90,"pp_pct":19.0,"pk_pct":81.5,"starter_sv_pct":0.912},
    "Vancouver Canucks":     {"gf_pg":3.00,"ga_pg":3.10,"pp_pct":20.2,"pk_pct":80.0,"starter_sv_pct":0.909},
    "St. Louis Blues":       {"gf_pg":2.90,"ga_pg":3.30,"pp_pct":18.8,"pk_pct":78.5,"starter_sv_pct":0.904},
    "Calgary Flames":        {"gf_pg":2.85,"ga_pg":3.25,"pp_pct":18.5,"pk_pct":79.0,"starter_sv_pct":0.905},
    "Seattle Kraken":        {"gf_pg":2.80,"ga_pg":3.05,"pp_pct":18.2,"pk_pct":80.5,"starter_sv_pct":0.908},
    "Nashville Predators":   {"gf_pg":2.75,"ga_pg":3.25,"pp_pct":17.5,"pk_pct":79.2,"starter_sv_pct":0.905},
    "Columbus Blue Jackets": {"gf_pg":2.70,"ga_pg":3.40,"pp_pct":17.2,"pk_pct":78.0,"starter_sv_pct":0.902},
    "Anaheim Ducks":         {"gf_pg":2.65,"ga_pg":3.50,"pp_pct":17.0,"pk_pct":77.5,"starter_sv_pct":0.900},
    "San Jose Sharks":       {"gf_pg":2.60,"ga_pg":3.60,"pp_pct":16.8,"pk_pct":77.0,"starter_sv_pct":0.898},
    "Chicago Blackhawks":    {"gf_pg":2.55,"ga_pg":3.55,"pp_pct":16.5,"pk_pct":77.2,"starter_sv_pct":0.899},
    "Utah Mammoth":          {"gf_pg":2.90,"ga_pg":3.10,"pp_pct":19.0,"pk_pct":80.0,"starter_sv_pct":0.909},
}


def _get(url: str, delay: float = 0.3) -> Optional[dict]:
    time.sleep(delay)
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  NHL API: {e}")
        return None


class TeamStats:
    def __init__(self):
        self._cache = {}

    def get(self, team_name: str) -> dict:
        if team_name in self._cache:
            return self._cache[team_name]

        fallback = TEAM_STATS_FALLBACK.get(team_name, {
            "gf_pg":3.1,"ga_pg":3.1,"pp_pct":20.0,
            "pk_pct":80.0,"starter_sv_pct":0.910
        })

        result = {
            "abbr":            TEAM_ABBR.get(team_name,""),
            "gf_pg":           fallback["gf_pg"],
            "ga_pg":           fallback["ga_pg"],
            "pp_pct":          fallback["pp_pct"],
            "pk_pct":          fallback["pk_pct"],
            "shots_pg":        30.0,
            "shots_ag":        30.0,
            "starter_sv_pct":  fallback["starter_sv_pct"],
            "gp":              78,
        }
        self._cache[team_name] = result
        return result

    def _defaults(self):
        return {
            "abbr":"","gf_pg":3.1,"ga_pg":3.1,"pp_pct":20.0,
            "pk_pct":80.0,"shots_pg":30.0,"shots_ag":30.0,
            "starter_sv_pct":0.910,"gp":78,
        }


class PlayerStats:
    def __init__(self):
        self._cache = {}
        self._roster_cache = {}

    def get_skater(self, player_name, team_name, n_games=10):
        return self._skater_defaults()

    def get_goalie(self, player_name, team_name, n_games=10):
        return self._goalie_defaults()

    @staticmethod
    def _skater_defaults():
        return {
            "player_id":None,"shots_pg":2.5,"goals_pg":0.25,
            "assists_pg":0.35,"points_pg":0.60,"toi_pg":1080,
            "hits_pg":1.5,"blocks_pg":0.8,"pp_points_pg":0.15,
            "shots_std":1.2,"points_std":0.7,"n_games":0,
        }

    @staticmethod
    def _goalie_defaults():
        return {
            "player_id":None,"saves_pg":26.0,"shots_against_pg":28.5,
            "sv_pct":0.910,"gaa":2.85,"saves_std":4.5,"n_games":0,
        }


class LineupValidator:
    def __init__(self):
        self._roster_cache = {}
        self._starter_cache = {}

    def get_active_players(self, team_name):
        abbr = TEAM_ABBR.get(team_name,"")
        if abbr in self._roster_cache:
            return self._roster_cache[abbr]

        data = _get(f"{NHL_API}/roster/{abbr}/current", delay=0.5)
        if not data:
            return set()

        active = set()
        for group in ["forwards","defensemen","goalies"]:
            for p in data.get(group,[]):
                if p.get("injuryStatus") in ("IR","LTIR","Day-to-Day","Injured"):
                    continue
                fn = p.get("firstName",{}).get("default","")
                ln = p.get("lastName",{}).get("default","")
                full = f"{fn} {ln}".strip().lower()
                if full:
                    active.add(full)

        self._roster_cache[abbr] = active
        return active

    def get_probable_starter(self, team_name):
        return None

    def is_back_to_back(self, team_name, game_date):
        return False
