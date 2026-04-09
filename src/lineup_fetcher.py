"""
Lineup Fetcher v3 — NHL.com API uniquement
Remplace Daily Faceoff (bloque GitHub Actions)
Role: detection des blessures + gardien probable
PP/lignes: multiplicateur neutre (1.0) sans DF
Tres peu d'appels API — une seule requete par equipe
"""

import requests
import time

NHL_API = "https://api-web.nhle.com/v1"
SEASON  = "20252026"

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

# PP1 connus par equipe (hardcode saison 2025-26 — updated mensuellement)
# Format: liste des 5 joueurs PP1 par equipe
PP1_UNITS = {
    "MTL": ["Cole Caufield", "Nick Suzuki", "Juraj Slafkovsky", "Ivan Demidov", "Lane Hutson"],
    "TBL": ["Nikita Kucherov", "Brayden Point", "Jake Guentzel", "Victor Hedman", "Darren Raddysh"],
    "BOS": ["David Pastrnak", "Brad Marchand", "Pavel Zacha", "Charlie McAvoy", "Hampus Lindholm"],
    "FLA": ["Sam Reinhart", "Matthew Tkachuk", "Carter Verhaeghe", "Aaron Ekblad", "Gustav Forsling"],
    "TOR": ["Auston Matthews", "Mitch Marner", "William Nylander", "Morgan Rielly", "Jake McCabe"],
    "OTT": ["Tim Stutzle", "Claude Giroux", "Brady Tkachuk", "Jake Sanderson", "Thomas Chabot"],
    "BUF": ["Tage Thompson", "JJ Peterka", "Jason Zucker", "Owen Power", "Rasmus Dahlin"],
    "DET": ["Dylan Larkin", "Lucas Raymond", "Alex DeBrincat", "Moritz Seider", "Simon Edvinsson"],
    "EDM": ["Connor McDavid", "Leon Draisaitl", "Zach Hyman", "Evan Bouchard", "Darnell Nurse"],
    "CGY": ["Nazem Kadri", "Jonathan Huberdeau", "Mikael Backlund", "MacKenzie Weegar", "Rasmus Andersson"],
    "VAN": ["Elias Pettersson", "J.T. Miller", "Brock Boeser", "Filip Hronek", "Quinn Hughes"],
    "VGK": ["Jack Eichel", "Mark Stone", "Tomas Hertl", "Alex Pietrangelo", "Shea Theodore"],
    "SEA": ["Matty Beniers", "Jared McCann", "Jordan Eberle", "Vince Dunn", "Brandon Montour"],
    "LAK": ["Anze Kopitar", "Adrian Kempe", "Kevin Fiala", "Drew Doughty", "Mikey Anderson"],
    "ANA": ["Troy Terry", "Mason McTavish", "Leo Carlsson", "Cam Fowler", "Jackson LaCombe"],
    "SJS": ["Macklin Celebrini", "Will Smith", "Tyler Toffoli", "Mario Ferraro", "Jan Rutta"],
    "CAR": ["Sebastian Aho", "Andrei Svechnikov", "Seth Jarvis", "Brent Burns", "Jaccob Slavin"],
    "NYR": ["Artemi Panarin", "Vincent Trocheck", "Alexis Lafreniere", "Adam Fox", "Jacob Trouba"],
    "NYI": ["Mathew Barzal", "Bo Horvat", "Kyle Palmieri", "Noah Dobson", "Ryan Pulock"],
    "NJD": ["Jack Hughes", "Jesper Bratt", "Dawson Mercer", "Dougie Hamilton", "Jonas Siegenthaler"],
    "PHI": ["Sean Couturier", "Travis Konecny", "Owen Tippett", "Ivan Provorov", "Travis Sanheim"],
    "PIT": ["Sidney Crosby", "Evgeni Malkin", "Jake Guentzel", "Kris Letang", "Erik Karlsson"],
    "WSH": ["Alex Ovechkin", "Nicklas Backstrom", "Tom Wilson", "John Carlson", "Trevor van Riemsdyk"],
    "COL": ["Nathan MacKinnon", "Mikko Rantanen", "Valeri Nichushkin", "Cale Makar", "Devon Toews"],
    "DAL": ["Jason Robertson", "Roope Hintz", "Joe Pavelski", "Miro Heiskanen", "Thomas Harley"],
    "MIN": ["Kirill Kaprizov", "Matt Boldy", "Joel Eriksson Ek", "Jared Spurgeon", "Jonas Brodin"],
    "STL": ["Jordan Kyrou", "Robert Thomas", "Pavel Buchnevich", "Torey Krug", "Colton Parayko"],
    "WPG": ["Mark Scheifele", "Kyle Connor", "Gabriel Vilardi", "Josh Morrissey", "Neal Pionk"],
    "NSH": ["Filip Forsberg", "Ryan O'Reilly", "Gustav Nyquist", "Roman Josi", "Ryan McDonagh"],
    "CHI": ["Connor Bedard", "Taylor Hall", "Nick Foligno", "Seth Jones", "Kevin Korchinski"],
    "CBJ": ["Adam Fantilli", "Kirill Marchenko", "Sean Monahan", "Zach Werenski", "Ivan Provorov"],
    "UTA": ["Clayton Keller", "Dylan Guenther", "Nick Bjugstad", "Mikhail Sergachev", "Michael Kesselring"],
}


def _get(url):
    time.sleep(0.4)
    try:
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  NHL API: {e}")
        return None


class LineupFetcher:

    def __init__(self):
        self._cache        = {}
        self._roster_cache = {}

    def get_lineup(self, team_name: str) -> dict:
        if team_name in self._cache:
            return self._cache[team_name]

        data = self._build_lineup(team_name)
        self._cache[team_name] = data

        n_fwd = len(data.get("forwards", []))
        n_inj = len(data.get("injuries", {}))
        print(f"  ✅ Lineup NHL API {team_name}: {n_fwd} fwd actifs · {n_inj} blessures")
        return data

    def get_player_role(self, player_name: str, team: str) -> dict:
        lineup = self.get_lineup(team)
        roles  = lineup.get("player_roles", {})
        key    = player_name.lower().strip()
        return roles.get(key, {"multiplier": 1.0, "pp": 0, "line": 2, "is_defense": False})

    def is_injured(self, player_name: str, team: str) -> bool:
        lineup   = self.get_lineup(team)
        injuries = lineup.get("injuries", {})
        return injuries.get(player_name.lower().strip(), "") in {"ir", "out"}

    def _build_lineup(self, team_name: str) -> dict:
        abbr = TEAM_ABBR.get(team_name, "")
        if not abbr:
            return self._empty()

        roster = self._get_roster(abbr)
        if not roster:
            return self._empty()

        injuries  = {}
        forwards  = []
        defensemen = []
        goalies_active = []

        for group in ["forwards", "defensemen", "goalies"]:
            for p in roster.get(group, []):
                status = p.get("injuryStatus", "")
                fn = p.get("firstName", {}).get("default", "")
                ln = p.get("lastName",  {}).get("default", "")
                name     = fn + " " + ln
                name_key = name.lower().strip()
                pid      = p.get("id")
                pos      = p.get("positionCode", "F")

                if status in ("IR", "LTIR"):
                    injuries[name_key] = "ir"
                    continue
                elif status in ("Day-to-Day", "Injured", "Out"):
                    injuries[name_key] = "out"

                if group == "forwards":
                    forwards.append({"name": name, "id": pid, "pos": pos, "line": 2})
                elif group == "defensemen":
                    defensemen.append({"name": name, "id": pid, "pos": "D", "pair": 2})
                elif group == "goalies":
                    goalies_active.append({"name": name, "id": pid, "gp": p.get("gamesPlayed", 0)})

        # Gardien le plus actif
        goalie = ""
        if goalies_active:
            best = max(goalies_active, key=lambda g: g.get("gp", 0)
                       if isinstance(g.get("gp"), int) else 0)
            goalie = best["name"]

        # PP1 depuis hardcode
        pp1 = PP1_UNITS.get(abbr, [])
        pp1_set = {n.lower() for n in pp1}

        # Player roles — multiplicateurs base
        # Pas de data lignes sans DF, on utilise 1.0 neutre sauf PP1 connus
        player_roles = {}
        for p in forwards:
            key = p["name"].lower().strip()
            pp  = 1 if key in pp1_set else 0
            # PP1 boost = +0.20, sinon neutre 1.0
            mult = 1.20 if pp == 1 else 1.0
            player_roles[key] = {
                "name": p["name"], "line": 2, "pp": pp,
                "pos": p["pos"], "is_defense": False,
                "multiplier": mult,
            }
        for p in defensemen:
            key = p["name"].lower().strip()
            pp  = 1 if key in pp1_set else 0
            mult = 1.15 if pp == 1 else 0.90
            player_roles[key] = {
                "name": p["name"], "line": 2, "pp": pp,
                "pos": p["pos"], "is_defense": True,
                "multiplier": mult,
            }

        return {
            "forwards":     forwards,
            "defense":      defensemen,
            "pp1":          pp1,
            "pp2":          [],
            "injuries":     injuries,
            "goalie":       goalie,
            "player_roles": player_roles,
            "source":       "nhl_api",
        }

    def _get_roster(self, abbr: str) -> dict:
        if abbr in self._roster_cache:
            return self._roster_cache[abbr]
        data = _get(f"{NHL_API}/roster/{abbr}/current")
        if data:
            self._roster_cache[abbr] = data
        return data or {}

    def _empty(self) -> dict:
        return {
            "forwards": [], "defense": [], "pp1": [], "pp2": [],
            "injuries": {}, "goalie": "", "player_roles": {}, "source": "empty",
        }
