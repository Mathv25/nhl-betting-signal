"""
NBA Rolling Stats Fetcher
Utilise stats.nba.com via urllib (requests est bloqué par NBA).
IDs hardcodés pour éviter le rate-limit sur l'endpoint de recherche.
Retourne les moyennes sur les 10 derniers matchs playoffs / saison.
"""
import json, time, urllib.request, urllib.parse

TIMEOUT    = 12
N_GAMES    = 10
NBA_SEASON = "2025-26"

# IDs officiels stats.nba.com (PERSON_ID)
NBA_PLAYER_IDS = {
    # Boston Celtics
    "Jayson Tatum":            1628369,
    "Jaylen Brown":            1627759,
    "Payton Pritchard":        1630202,
    "Jrue Holiday":            203200,
    "Al Horford":              201143,
    # New York Knicks
    "Jalen Brunson":           1628973,
    "Karl-Anthony Towns":      1626157,
    "Mikal Bridges":           1628969,
    "OG Anunoby":              1628384,
    "Josh Hart":               1628404,
    # Milwaukee Bucks
    "Giannis Antetokounmpo":   203507,
    "Brook Lopez":             201572,
    "Bobby Portis":            1626171,
    "Khris Middleton":         203114,
    # Cleveland Cavaliers
    "Donovan Mitchell":        1628378,
    "Darius Garland":          1629636,
    "Evan Mobley":             1630596,
    "Jarrett Allen":           1628386,
    "Max Strus":               1629622,
    # Indiana Pacers
    "Tyrese Haliburton":       1630169,
    "Pascal Siakam":           1627783,
    "Myles Turner":            1626167,
    "Bennedict Mathurin":      1631108,
    "Andrew Nembhard":         1630572,
    # Orlando Magic
    "Paolo Banchero":          1631094,
    "Franz Wagner":            1630532,
    "Jalen Suggs":             1630591,
    "Cole Anthony":            1630175,
    # Miami Heat
    "Bam Adebayo":             1628389,
    "Tyler Herro":             1629639,
    "Terry Rozier":            1626179,
    "Duncan Robinson":         1629130,
    # Philadelphia 76ers
    "Tyrese Maxey":            1630178,
    "Kelly Oubre Jr.":         1626162,
    "Tobias Harris":           202699,
    # Oklahoma City Thunder
    "Shai Gilgeous-Alexander": 1628983,
    "Jalen Williams":          1631114,
    "Chet Holmgren":           1631096,
    "Luguentz Dort":           1629652,
    "Isaiah Hartenstein":      1629744,
    # Denver Nuggets
    "Nikola Jokic":            203999,
    "Jamal Murray":            1627750,
    "Michael Porter Jr.":      1629008,
    "Aaron Gordon":            203932,
    # Minnesota Timberwolves
    "Anthony Edwards":         1630162,
    "Rudy Gobert":             203497,
    "Jaden McDaniels":         1630183,
    "Naz Reid":                1629675,
    # Los Angeles Lakers
    "LeBron James":            2544,
    "Anthony Davis":           203076,
    "Austin Reaves":           1630559,
    "D'Angelo Russell":        1626156,
    # LA Clippers
    "James Harden":            201935,
    "Norman Powell":           1626181,
    "Ivica Zubac":             1627826,
    # Dallas Mavericks
    "Luka Doncic":             1629029,
    "Kyrie Irving":            202681,
    "PJ Washington":           1629023,
    # Houston Rockets
    "Alperen Sengun":          1630578,
    "Jalen Green":             1630224,
    "Fred VanVleet":           1627832,
    # San Antonio Spurs
    "Victor Wembanyama":       1641705,
    "Devin Vassell":           1630170,
    # Golden State Warriors
    "Andrew Wiggins":          203952,
    "Jonathan Kuminga":        1630228,
    "Draymond Green":          203110,
    # Phoenix Suns
    "Kevin Durant":            201142,
    "Devin Booker":            1626164,
    # Sacramento Kings
    "De'Aaron Fox":            1628368,
    "Domantas Sabonis":        1627734,
    # Charlotte Hornets
    "LaMelo Ball":             1630163,
    "Brandon Miller":          1641706,
}

_rolling_cache = {}   # player_id -> dict | None

_NBA_HEADERS = {
    "User-Agent":         "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":             "application/json, text/plain, */*",
    "Accept-Language":    "en-US,en;q=0.5",
    "Accept-Encoding":    "identity",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token":  "true",
    "Referer":            "https://www.nba.com/",
    "Origin":             "https://www.nba.com",
    "Connection":         "keep-alive",
}


def _get_json(url: str, params: dict = None) -> dict:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_NBA_HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _current_season_type() -> str:
    import datetime
    m = datetime.datetime.now().month
    return "Playoffs" if m in (4, 5, 6) else "Regular Season"


def get_player_rolling(name: str, n: int = N_GAMES):
    """
    Retourne {'pts', 'reb', 'ast', 'pra', 'games', 'season_type'} ou None.
    Essaie playoffs d'abord, puis saison régulière en fallback.
    """
    pid = NBA_PLAYER_IDS.get(name)
    if pid is None:
        return None
    if pid in _rolling_cache:
        return _rolling_cache[pid]

    for season_type in [_current_season_type(), "Regular Season"]:
        try:
            data = _get_json(
                "https://stats.nba.com/stats/playergamelogs",
                {
                    "PlayerID":   pid,
                    "Season":     NBA_SEASON,
                    "SeasonType": season_type,
                    "LastNGames": n,
                }
            )
            cols = data["resultSets"][0]["headers"]
            rows = data["resultSets"][0]["rowSet"]

            if not rows:
                continue

            pts_i = cols.index("PTS")
            reb_i = cols.index("REB")
            ast_i = cols.index("AST")
            min_i = cols.index("MIN")

            # Exclure DNP
            played = [r for r in rows if (r[min_i] or 0) > 0][-n:]
            if len(played) < 3:
                continue

            ng  = len(played)
            pts = sum(r[pts_i] or 0 for r in played) / ng
            reb = sum(r[reb_i] or 0 for r in played) / ng
            ast = sum(r[ast_i] or 0 for r in played) / ng

            result = {
                "pts":         round(pts, 1),
                "reb":         round(reb, 1),
                "ast":         round(ast, 1),
                "pra":         round(pts + reb + ast, 1),
                "games":       ng,
                "season_type": season_type,
            }
            _rolling_cache[pid] = result
            return result
        except Exception:
            continue

    _rolling_cache[pid] = None
    return None


def warm_up(player_names: list) -> None:
    for name in player_names:
        try:
            get_player_rolling(name)
            time.sleep(0.4)
        except Exception:
            pass
