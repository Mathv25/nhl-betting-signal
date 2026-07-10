"""
MLB Rolling Stats Fetcher
Utilise l'API officielle MLB (statsapi.mlb.com) — gratuite, aucune auth.
Retourne les moyennes sur les N derniers matchs plutôt que la saison entière.
"""
import requests, time

MLB_API   = "https://statsapi.mlb.com/api/v1"
HEADERS   = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
TIMEOUT   = 10
N_BATTING = 15   # Derniers matchs frappeurs
N_PITCHING = 6  # Derniers départs lanceurs

_player_id_cache: dict = {}   # name_lower -> int | None
_batting_cache:   dict = {}   # player_id  -> dict | None
_pitching_cache:  dict = {}   # player_id  -> dict | None


def _search_player_id(name: str) -> object:
    key = name.lower().strip()
    if key in _player_id_cache:
        return _player_id_cache[key]
    try:
        r = requests.get(
            f"{MLB_API}/people/search",
            params={"names": name, "sportId": 1},
            headers=HEADERS, timeout=TIMEOUT
        )
        if r.status_code == 200:
            people = r.json().get("people", [])
            if people:
                pid = people[0]["id"]
                _player_id_cache[key] = pid
                return pid
    except Exception:
        pass
    _player_id_cache[key] = None
    return None


def get_batter_rolling(name: str, n: int = N_BATTING) -> object:
    """
    Retourne les moyennes par match sur les n dernières parties.
    {'hits': float, 'total_bases': float, 'home_runs': float, 'games': int}
    Retourne None si données insuffisantes ou API inaccessible.
    """
    pid = _search_player_id(name)
    if pid is None:
        return None
    if pid in _batting_cache:
        return _batting_cache[pid]

    try:
        r = requests.get(
            f"{MLB_API}/people/{pid}/stats",
            params={"stats": "gameLog", "group": "hitting", "season": "2026"},
            headers=HEADERS, timeout=TIMEOUT
        )
        if r.status_code != 200:
            _batting_cache[pid] = None
            return None

        splits = r.json().get("stats", [{}])[0].get("splits", [])
        # Prendre les n derniers matchs
        recent = splits[-n:] if len(splits) >= n else splits
        if len(recent) < 3:
            _batting_cache[pid] = None
            return None

        hits = sum(g["stat"].get("hits", 0) for g in recent)
        tb   = sum(g["stat"].get("totalBases", 0) for g in recent)
        hr   = sum(g["stat"].get("homeRuns", 0) for g in recent)
        ng   = len(recent)

        result = {
            "hits":        round(hits / ng, 3),
            "total_bases": round(tb / ng, 3),
            "home_runs":   round(hr / ng, 3),
            "games":       ng,
        }
        _batting_cache[pid] = result
        return result
    except Exception:
        _batting_cache[pid] = None
        return None


def _innings_to_float(ip: str) -> float:
    """Convertit '6.1' (6 manches 1 retrait) en float pour filtrage."""
    try:
        parts = str(ip).split(".")
        full  = int(parts[0])
        third = int(parts[1]) if len(parts) > 1 else 0
        return full + third / 3
    except Exception:
        return 0.0


def get_pitcher_rolling(name: str, n: int = N_PITCHING) -> object:
    """
    Retourne la projection pondérée de K par départ.
    Logique:
    1. Filtre outliers agressif: K < mean - 1.0*std ET K <= 3
    2. Moyenne pondérée: départs récents pèsent plus (poids croissants)
    3. Blend 70% rolling / 30% saison pour stabiliser les petits échantillons
    {'strikeouts': float, 'games': int}
    """
    pid = _search_player_id(name)
    if pid is None:
        return None
    if pid in _pitching_cache:
        return _pitching_cache[pid]

    try:
        r = requests.get(
            f"{MLB_API}/people/{pid}/stats",
            params={"stats": "gameLog", "group": "pitching", "season": "2026"},
            headers=HEADERS, timeout=TIMEOUT
        )
        if r.status_code != 200:
            _pitching_cache[pid] = None
            return None

        splits = r.json().get("stats", [{}])[0].get("splits", [])
        all_starts = [
            g for g in splits
            if _innings_to_float(g["stat"].get("inningsPitched", "0")) >= 3.0
        ]

        if len(all_starts) < 2:
            _pitching_cache[pid] = None
            return None

        # Moyenne saison complète (référence stable)
        all_k = [g["stat"].get("strikeOuts", 0) for g in all_starts]
        season_avg = sum(all_k) / len(all_k)

        # Derniers N départs pour le rolling
        starts = all_starts[-n:]
        k_vals = [g["stat"].get("strikeOuts", 0) for g in starts]

        # Filtre outliers: K < mean - 1.0*std ET K <= 3
        # Plus agressif que l'ancien (1.5*std et K<=2)
        if len(k_vals) >= 3:
            mean = sum(k_vals) / len(k_vals)
            std  = (sum((x - mean) ** 2 for x in k_vals) / len(k_vals)) ** 0.5
            if std > 0:
                k_vals_filtered = [k for k in k_vals if not (k < mean - 1.0 * std and k <= 3)]
                if k_vals_filtered:  # ne pas vider la liste
                    k_vals = k_vals_filtered

        if not k_vals:
            _pitching_cache[pid] = None
            return None

        # Moyenne pondérée: les départs les plus récents pèsent plus
        # Poids: 1, 1.5, 2, 2.5, 3, 3.5 (du plus ancien au plus récent)
        n_k = len(k_vals)
        weights = [1.0 + 0.5 * i for i in range(n_k)]
        weighted_sum   = sum(k * w for k, w in zip(k_vals, weights))
        weighted_total = sum(weights)
        rolling_avg    = weighted_sum / weighted_total

        # Blend 70% rolling pondéré / 30% saison
        blended = round(0.70 * rolling_avg + 0.30 * season_avg, 2)

        result = {
            "strikeouts":   blended,
            "rolling_avg":  round(rolling_avg, 2),
            "season_avg":   round(season_avg, 2),
            "games":        len(k_vals),
        }
        _pitching_cache[pid] = result
        return result
    except Exception:
        _pitching_cache[pid] = None
        return None


TEAM_ID_MAP = {
    "Arizona Diamondbacks": 109, "Athletics": 133, "Atlanta Braves": 144,
    "Baltimore Orioles": 110, "Boston Red Sox": 111, "Chicago Cubs": 112,
    "Chicago White Sox": 145, "Cincinnati Reds": 113, "Cleveland Guardians": 114,
    "Colorado Rockies": 115, "Detroit Tigers": 116, "Houston Astros": 117,
    "Kansas City Royals": 118, "Los Angeles Angels": 108, "Los Angeles Dodgers": 119,
    "Miami Marlins": 146, "Milwaukee Brewers": 158, "Minnesota Twins": 142,
    "New York Mets": 121, "New York Yankees": 147, "Philadelphia Phillies": 143,
    "Pittsburgh Pirates": 134, "San Diego Padres": 135, "San Francisco Giants": 137,
    "Seattle Mariners": 136, "St. Louis Cardinals": 138, "Tampa Bay Rays": 139,
    "Texas Rangers": 140, "Toronto Blue Jays": 141, "Washington Nationals": 120,
    "Oakland Athletics": 133,
}
LEAGUE_AVG_K = 0.215

_team_k_cache: dict = {}   # team_name -> float


def get_team_k_rate(team_name: str, n_games: int = 10) -> float:
    """
    Retourne le taux de retraits sur balle (K%) de l'équipe adverse
    sur ses n_games dernières parties via MLB Stats API.
    Combine 70% récent + 30% saison pour lisser les échantillons courts.
    Fallback sur LEAGUE_AVG_K si API inaccessible.
    """
    key = f"{team_name}_{n_games}"
    if key in _team_k_cache:
        return _team_k_cache[key]

    team_id = TEAM_ID_MAP.get(team_name)
    if team_id is None:
        # Recherche partielle
        tl = team_name.lower()
        for name, tid in TEAM_ID_MAP.items():
            if name.lower().split()[-1] == tl.split()[-1]:
                team_id = tid
                break

    if team_id is None:
        _team_k_cache[key] = LEAGUE_AVG_K
        return LEAGUE_AVG_K

    try:
        r = requests.get(
            f"{MLB_API}/teams/{team_id}/stats",
            params={"stats": "gameLog", "group": "hitting", "season": "2026"},
            headers=HEADERS, timeout=TIMEOUT
        )
        if r.status_code != 200:
            _team_k_cache[key] = LEAGUE_AVG_K
            return LEAGUE_AVG_K

        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            _team_k_cache[key] = LEAGUE_AVG_K
            return LEAGUE_AVG_K

        # K% récent (n derniers matchs)
        recent = splits[-n_games:]
        r_pa = sum(g["stat"].get("plateAppearances", 0) for g in recent)
        r_k  = sum(g["stat"].get("strikeOuts", 0) for g in recent)
        k_recent = r_k / r_pa if r_pa > 0 else LEAGUE_AVG_K

        # K% saison complète
        s_pa = sum(g["stat"].get("plateAppearances", 0) for g in splits)
        s_k  = sum(g["stat"].get("strikeOuts", 0) for g in splits)
        k_season = s_k / s_pa if s_pa > 0 else LEAGUE_AVG_K

        # Blend: 70% récent, 30% saison — réduit le bruit des petits échantillons
        blended = round(0.70 * k_recent + 0.30 * k_season, 4)
        _team_k_cache[key] = blended
        return blended

    except Exception:
        _team_k_cache[key] = LEAGUE_AVG_K
        return LEAGUE_AVG_K


def warm_up(player_names: list, player_type: str = "batter") -> None:
    """Pre-fetche les stats pour une liste de joueurs (en parallele ou sequentiel)."""
    fn = get_batter_rolling if player_type == "batter" else get_pitcher_rolling
    for name in player_names:
        try:
            fn(name)
            time.sleep(0.2)
        except Exception:
            pass
