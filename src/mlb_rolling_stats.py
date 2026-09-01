"""
MLB Rolling Stats Fetcher
Utilise l'API officielle MLB (statsapi.mlb.com) — gratuite, aucune auth.
Retourne les moyennes sur les N derniers matchs plutôt que la saison entière.
"""
import requests, time

MLB_API   = "https://statsapi.mlb.com/api/v1"
HEADERS   = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
TIMEOUT   = 10
SEASON    = "2026"
N_BATTING = 15   # Derniers matchs frappeurs
N_PITCHING = 6  # Derniers départs lanceurs

_player_id_cache: dict = {}   # name_lower -> int | None
_batting_cache:   dict = {}   # player_id  -> dict | None
_pitching_cache:  dict = {}   # player_id  -> dict | None
_hand_cache:      dict = {}   # player_id  -> "R" | "L" | None


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


def get_pitcher_hand(name: str) -> object:
    """
    Main du lanceur ("R" ou "L") via people/{id}.pitchHand.
    Sert à choisir le split d'offense adverse (vs RHP / vs LHP).
    Retourne None si introuvable.
    """
    pid = _search_player_id(name)
    if pid is None:
        return None
    if pid in _hand_cache:
        return _hand_cache[pid]
    try:
        r = requests.get(f"{MLB_API}/people/{pid}", headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 200:
            people = r.json().get("people", [])
            if people:
                code = (people[0].get("pitchHand") or {}).get("code", "")
                hand = code.upper() if code.upper() in ("R", "L") else None
                _hand_cache[pid] = hand
                return hand
    except Exception:
        pass
    _hand_cache[pid] = None
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
LEAGUE_AVG_K      = 0.215
LEAGUE_K_FALLBACK = 0.22   # K% MLB de référence si l'API ne répond pas

_team_k_cache:      dict = {}   # team_name -> float
_team_k_season_cache: dict = {} # (team, hand) -> dict
_league_k_cache:    dict = {}   # "rate" -> float


def _f(v, default=0.0) -> float:
    """L'API renvoie parfois les compteurs en string ('1234')."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _resolve_team_id(team_name: str):
    """ID MLB d'une équipe, avec repli sur le dernier mot du nom."""
    team_id = TEAM_ID_MAP.get(team_name)
    if team_id is not None:
        return team_id
    tl = (team_name or "").lower()
    if not tl:
        return None
    for name, tid in TEAM_ID_MAP.items():
        if name.lower().split()[-1] == tl.split()[-1]:
            return tid
    return None


def get_league_k_rate() -> float:
    """
    K% moyen de la MLB pour la saison en cours (K / PA, agrégé sur les 30
    équipes). C'est le dénominateur de l'ajustement adverse: sans lui, on
    normalise par une constante qui date d'une autre saison.
    Repli: LEAGUE_K_FALLBACK (0.22).
    """
    if "rate" in _league_k_cache:
        return _league_k_cache["rate"]

    rate = LEAGUE_K_FALLBACK
    try:
        r = requests.get(
            f"{MLB_API}/teams/stats",
            params={"stats": "season", "group": "hitting",
                    "season": SEASON, "sportIds": 1},
            headers=HEADERS, timeout=TIMEOUT
        )
        if r.status_code == 200:
            splits = r.json().get("stats", [{}])[0].get("splits", [])
            pa = sum(_f(s.get("stat", {}).get("plateAppearances")) for s in splits)
            k  = sum(_f(s.get("stat", {}).get("strikeOuts")) for s in splits)
            # Garde-fou: en début de saison l'échantillon est trop mince.
            if pa >= 20000 and k > 0:
                rate = round(k / pa, 4)
    except Exception:
        pass

    _league_k_cache["rate"] = rate
    return rate


def get_team_k_rate_season(team_name: str, vs_hand: str = None) -> dict:
    """
    K% de l'équipe sur la SAISON, contre la main du lanceur qu'elle affronte
    quand le split est disponible (sitCodes vr / vl).

    Retourne {"k_pct": float, "source": str, "pa": int}.

    Volontairement: jamais de fenêtre 10 jours seule. Un K% sur 10 matchs
    (~350 PA) bouge de plusieurs points par pur bruit, et c'est ce bruit qui
    faisait exploser les projections. Ordre de repli:
      1. saison vs RHP / vs LHP  (PA >= 200)
      2. saison complète         (PA >= 500)
      3. K% de ligue
    """
    hand = (vs_hand or "").upper()
    if hand not in ("R", "L"):
        hand = ""
    cache_key = (team_name, hand)
    if cache_key in _team_k_season_cache:
        return _team_k_season_cache[cache_key]

    lg = get_league_k_rate()
    out = {"k_pct": lg, "source": "ligue", "pa": 0}
    team_id = _resolve_team_id(team_name)
    if team_id is None:
        _team_k_season_cache[cache_key] = out
        return out

    # 1. Split contre la main du lanceur
    if hand:
        try:
            r = requests.get(
                f"{MLB_API}/teams/{team_id}/stats",
                params={"stats": "statSplits", "sitCodes": "vr" if hand == "R" else "vl",
                        "group": "hitting", "season": SEASON},
                headers=HEADERS, timeout=TIMEOUT
            )
            if r.status_code == 200:
                splits = r.json().get("stats", [{}])[0].get("splits", [])
                st = splits[0].get("stat", {}) if splits else {}
                pa = _f(st.get("plateAppearances"))
                k  = _f(st.get("strikeOuts"))
                if pa >= 200 and k > 0:
                    out = {
                        "k_pct":  round(k / pa, 4),
                        "source": "saison vs " + ("RHP" if hand == "R" else "LHP"),
                        "pa":     int(pa),
                    }
                    _team_k_season_cache[cache_key] = out
                    return out
        except Exception:
            pass

    # 2. Saison complète (main inconnue ou split trop mince)
    try:
        r = requests.get(
            f"{MLB_API}/teams/{team_id}/stats",
            params={"stats": "season", "group": "hitting", "season": SEASON},
            headers=HEADERS, timeout=TIMEOUT
        )
        if r.status_code == 200:
            splits = r.json().get("stats", [{}])[0].get("splits", [])
            st = splits[0].get("stat", {}) if splits else {}
            pa = _f(st.get("plateAppearances"))
            k  = _f(st.get("strikeOuts"))
            if pa >= 500 and k > 0:
                out = {"k_pct": round(k / pa, 4), "source": "saison", "pa": int(pa)}
    except Exception:
        pass

    _team_k_season_cache[cache_key] = out
    return out


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
