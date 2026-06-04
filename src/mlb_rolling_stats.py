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
    Retourne la moyenne de retraits sur balle par départ (n derniers départs ≥ 3 manches).
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
        # Filtrer pour les départs seulement (≥ 3 manches lancées)
        starts = [
            g for g in splits
            if _innings_to_float(g["stat"].get("inningsPitched", "0")) >= 3.0
        ][-n:]

        if len(starts) < 2:
            _pitching_cache[pid] = None
            return None

        k_vals = [g["stat"].get("strikeOuts", 0) for g in starts]

        # Exclure les départs aberrants (sortie prématurée, météo, blessure)
        # Un départ est un outlier si K < mean - 1.5 * std ET K <= 2
        if len(k_vals) >= 3:
            mean = sum(k_vals) / len(k_vals)
            std  = (sum((x - mean) ** 2 for x in k_vals) / len(k_vals)) ** 0.5
            if std > 0:
                k_vals = [k for k in k_vals if not (k < mean - 1.5 * std and k <= 2)]

        if not k_vals:
            _pitching_cache[pid] = None
            return None

        result  = {
            "strikeouts": round(sum(k_vals) / len(k_vals), 2),
            "games":      len(k_vals),
        }
        _pitching_cache[pid] = result
        return result
    except Exception:
        _pitching_cache[pid] = None
        return None


def warm_up(player_names: list, player_type: str = "batter") -> None:
    """Pre-fetche les stats pour une liste de joueurs (en parallele ou sequentiel)."""
    fn = get_batter_rolling if player_type == "batter" else get_pitcher_rolling
    for name in player_names:
        try:
            fn(name)
            time.sleep(0.2)
        except Exception:
            pass
