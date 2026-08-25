"""
MLB Team Model — couche de données pour les bets moneyline / run line.

Source: API officielle MLB (statsapi.mlb.com), gratuite, sans auth.

Ce module ne fait AUCUN jugement de pari — il ne fait que récupérer et
normaliser les ingrédients. Le modèle de probabilité vit dans
`mlb_ml_analyzer.py`.

Disponible via cette API (vérifié):
  - Lanceur: ERA, WHIP, K, BB, HBP, HR, IP, battersFaced, GS → FIP, K-BB%, IP/départ
  - Équipe offense vs main du lanceur (sitCodes vl/vr): OPS, SLG, AVG, OBP, K, PA → ISO, K%
  - Rotation vs bullpen (sitCodes sp/rp): ERA, WHIP, K, BB, HR, HBP, IP, BF → FIP, K-BB%
  - Usage bullpen: IP et lancers par releveur via les boxscores des derniers jours
  - Défense: fielding%, errors, rangeFactor
  - Stade: dimensions, type de toit

NON disponible (Statcast/Fangraphs, pas dans cette API) — ne pas prétendre l'avoir:
  - xERA, SIERA (nécessitent les données de balles frappées)
  - wRC+ (nécessite les ajustements ligue/parc de Fangraphs) → on utilise
    l'OPS vs main, normalisé par la moyenne de la ligue, comme substitut
  - Catcher framing / cadrage des prises
  - Météo avant l'heure du match (le champ existe mais reste vide jusqu'au
    début du match) → traité comme neutre quand absent
"""
import requests
from datetime import datetime, timedelta

MLB_API = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 15
SEASON  = "2026"

# Constante FIP de la ligue — recalculée dynamiquement si possible, sinon défaut.
FIP_CONSTANT_DEFAULT = 3.15

# Moyennes de ligue utilisées pour normaliser. Recalculées au premier appel de
# `load_league_context()`; ces valeurs ne servent que de repli.
LEAGUE = {
    "ops_vs_r":   0.715,
    "ops_vs_l":   0.720,
    "runs_per_g": 4.45,
    "fip":        4.05,
    "k_bb_pct":   0.135,
    "fip_const":  FIP_CONSTANT_DEFAULT,
}

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

_cache: dict = {}   # clé arbitraire -> valeur, vidé par process


def _get(path: str, params: dict = None) -> dict:
    try:
        r = requests.get(f"{MLB_API}/{path}", params=params or {},
                         headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return {}
        return r.json()
    except Exception:
        return {}


def _ip_to_float(ip) -> float:
    """'155.1' = 155 manches et 1 retrait = 155.333"""
    try:
        s = str(ip)
        if "." not in s:
            return float(s)
        whole, frac = s.split(".")
        return float(whole) + {"0": 0.0, "1": 1 / 3, "2": 2 / 3}.get(frac, 0.0)
    except Exception:
        return 0.0


def _f(v, default=0.0) -> float:
    try:
        if v in (None, "", "-", ".---"):
            return default
        return float(v)
    except Exception:
        return default


def _fip(hr, bb, hbp, k, ip, const=None) -> float:
    """FIP = (13*HR + 3*(BB+HBP) - 2*K)/IP + constante."""
    ip = _ip_to_float(ip)
    if ip <= 0:
        return LEAGUE["fip"]
    c = LEAGUE["fip_const"] if const is None else const
    return round((13 * hr + 3 * (bb + hbp) - 2 * k) / ip + c, 3)


def _split_stat(entity: str, team_or_player_id: int, group: str, sit_code: str) -> dict:
    """Récupère un split (sitCodes) pour une équipe ou un joueur."""
    key = ("split", entity, team_or_player_id, group, sit_code)
    if key in _cache:
        return _cache[key]
    data = _get(f"{entity}/{team_or_player_id}/stats", {
        "stats": "statSplits", "sitCodes": sit_code,
        "group": group, "season": SEASON,
    })
    splits = (data.get("stats") or [{}])[0].get("splits") or []
    out = splits[0].get("stat", {}) if splits else {}
    _cache[key] = out
    return out


# ── Contexte de ligue ────────────────────────────────────────────────────────

def load_league_context() -> dict:
    """
    Calcule les moyennes de ligue de la saison en cours pour normaliser les
    équipes. Sans ça, un OPS de .715 n'a aucun sens — il faut savoir si c'est
    au-dessus ou en dessous de la moyenne de CETTE saison.
    """
    if _cache.get("league_loaded"):
        return LEAGUE

    data = _get("teams/stats", {
        "stats": "season", "group": "hitting", "season": SEASON,
        "sportIds": 1,
    })
    splits = (data.get("stats") or [{}])[0].get("splits") or []
    if splits:
        runs = sum(_f(s["stat"].get("runs")) for s in splits)
        games = sum(_f(s["stat"].get("gamesPlayed")) for s in splits)
        if games > 0:
            # chaque match compte 2 équipes → runs/équipe/match
            LEAGUE["runs_per_g"] = round(runs / games, 3)

    pdata = _get("teams/stats", {
        "stats": "season", "group": "pitching", "season": SEASON,
        "sportIds": 1,
    })
    psplits = (pdata.get("stats") or [{}])[0].get("splits") or []
    if psplits:
        tot = {"hr": 0.0, "bb": 0.0, "hbp": 0.0, "k": 0.0, "ip": 0.0, "er": 0.0, "bf": 0.0}
        for s in psplits:
            st = s["stat"]
            tot["hr"]  += _f(st.get("homeRuns"))
            tot["bb"]  += _f(st.get("baseOnBalls"))
            tot["hbp"] += _f(st.get("hitByPitch"))
            tot["k"]   += _f(st.get("strikeOuts"))
            tot["ip"]  += _ip_to_float(st.get("inningsPitched"))
            tot["er"]  += _f(st.get("earnedRuns"))
            tot["bf"]  += _f(st.get("battersFaced"))
        if tot["ip"] > 0:
            era = 9 * tot["er"] / tot["ip"]
            raw = (13 * tot["hr"] + 3 * (tot["bb"] + tot["hbp"]) - 2 * tot["k"]) / tot["ip"]
            # La constante FIP est définie pour que FIP ligue == ERA ligue.
            LEAGUE["fip_const"] = round(era - raw, 3)
            LEAGUE["fip"]       = round(era, 3)
        if tot["bf"] > 0:
            LEAGUE["k_bb_pct"] = round((tot["k"] - tot["bb"]) / tot["bf"], 4)

    # OPS de ligue contre chaque main: moyenne des 30 équipes.
    for hand, key in (("vr", "ops_vs_r"), ("vl", "ops_vs_l")):
        vals = []
        for tid in set(TEAM_ID_MAP.values()):
            st = _split_stat("teams", tid, "hitting", hand)
            v = _f(st.get("ops"))
            if v > 0:
                vals.append(v)
        if vals:
            LEAGUE[key] = round(sum(vals) / len(vals), 4)

    _cache["league_loaded"] = True
    return LEAGUE


# ── Lanceur partant ─────────────────────────────────────────────────────────

def get_pitcher_profile(pitcher_id: int) -> dict:
    """
    Profil du lanceur partant: FIP, K-BB%, WHIP, manches par départ, main,
    et forme récente (5 derniers départs).

    On privilégie FIP et K-BB% sur l'ERA: l'ERA inclut la défense et la
    séquence des coups sûrs, donc elle est beaucoup plus bruitée à 25 départs.
    """
    key = ("pitcher", pitcher_id)
    if key in _cache:
        return _cache[key]

    people = _get(f"people/{pitcher_id}").get("people") or []
    if not people:
        _cache[key] = None
        return None
    person = people[0]
    hand = (person.get("pitchHand") or {}).get("code", "R")

    # IMPORTANT: on agrège les DÉPARTS seulement, pas la saison complète.
    # Beaucoup de lanceurs alternent départs et relève (Ian Seymour: 40
    # apparitions, 11 départs, la moitié de ses manches en relève). Utiliser
    # les totaux de saison donnait 8.1 manches par départ au lieu de 4.7 — le
    # modèle effaçait alors le bullpen adverse et créditait le partant de
    # statistiques flattées par ses sorties en relève.
    agg = _starts_aggregate(pitcher_id)
    if not agg or agg["starts"] < 1 or agg["ip"] < 5:
        _cache[key] = None
        return None

    ip = agg["ip"]
    gs = float(agg["starts"])
    bf = agg["bf"]
    hr, bb, hbp, k = agg["hr"], agg["bb"], agg["hbp"], agg["k"]
    st = agg["season_stat"]        # pour ERA/WHIP affichés (référence saison)

    # Régression vers la moyenne de la ligue. Un partant à 25 manches n'a pas
    # établi son vrai niveau: on le tire vers la ligue avec un a priori de
    # 40 manches. À 155 manches le poids propre est de 80%, à 25 manches de 38%.
    # Sans ça, une recrue avec 3 bons départs serait traitée comme un as.
    PRIOR_IP = 40.0
    w = ip / (ip + PRIOR_IP)
    fip_raw  = _fip(hr, bb, hbp, k, ip)
    kbb_raw  = (k - bb) / bf if bf > 0 else LEAGUE["k_bb_pct"]
    low_sample = ip < 40 or gs < 8

    prof = {
        "id":         pitcher_id,
        "name":       person.get("fullName", ""),
        "hand":       hand,
        "era":        _f(st.get("era"), LEAGUE["fip"]),
        "whip":       _f(st.get("whip"), 1.30),
        "fip_brut":   fip_raw,
        "fip":        round(w * fip_raw + (1 - w) * LEAGUE["fip"], 3),
        "k_bb_pct":   round(w * kbb_raw + (1 - w) * LEAGUE["k_bb_pct"], 4),
        "k_pct":      round(k / bf, 4) if bf > 0 else 0.22,
        # Manches par départ: ip et gs sont déjà restreints aux départs.
        # Régressée vers 5.2 avec un a priori de 4 départs.
        "ip_per_gs":  round((ip + 5.2 * 4) / (gs + 4), 2) if gs > 0 else 5.2,
        "gs":         int(gs),
        "ip":         round(ip, 1),
        "ip_saison":  round(_ip_to_float(st.get("inningsPitched")), 1),
        "poids_propre": round(w, 3),
        "echantillon_faible": low_sample,
    }
    prof["recent"] = _pitcher_recent_form(pitcher_id)
    _cache[key] = prof
    return prof


def _pitcher_game_log(pitcher_id: int) -> list:
    """Game log de lancer de la saison, mis en cache (utilisé 2x par profil)."""
    key = ("gamelog", pitcher_id)
    if key in _cache:
        return _cache[key]
    data = _get(f"people/{pitcher_id}/stats", {
        "stats": "gameLog", "group": "pitching", "season": SEASON,
    })
    splits = (data.get("stats") or [{}])[0].get("splits") or []
    _cache[key] = splits
    return splits


def _starts_aggregate(pitcher_id: int) -> dict:
    """
    Agrège les statistiques du lanceur en DÉPART seulement.

    Le game log distingue chaque apparition; `gamesStarted > 0` isole les
    départs. C'est indispensable pour tout lanceur qui fait aussi de la
    relève: ses manches et ses taux en relève ne décrivent pas ce qu'il fera
    comme partant.
    """
    splits = _pitcher_game_log(pitcher_id)
    if not splits:
        return None
    starts = [g for g in splits if _f(g["stat"].get("gamesStarted")) > 0]
    if not starts:
        return None

    agg = {"hr": 0.0, "bb": 0.0, "hbp": 0.0, "k": 0.0, "ip": 0.0, "bf": 0.0}
    for g in starts:
        s = g["stat"]
        agg["hr"]  += _f(s.get("homeRuns"))
        agg["bb"]  += _f(s.get("baseOnBalls"))
        agg["hbp"] += _f(s.get("hitByPitch"))
        agg["k"]   += _f(s.get("strikeOuts"))
        agg["ip"]  += _ip_to_float(s.get("inningsPitched"))
        agg["bf"]  += _f(s.get("battersFaced"))

    # Stats de saison conservées seulement pour l'affichage (ERA/WHIP).
    sdata = _get(f"people/{pitcher_id}/stats", {
        "stats": "season", "group": "pitching", "season": SEASON,
    })
    ssplits = (sdata.get("stats") or [{}])[0].get("splits") or []
    agg["season_stat"] = ssplits[0]["stat"] if ssplits else {}
    agg["starts"] = len(starts)
    return agg


def _pitcher_recent_form(pitcher_id: int, n: int = 5) -> dict:
    """
    Forme récente sur les n derniers départs, en FIP plutôt qu'en ERA.
    Retourne aussi l'écart vs le FIP saison — c'est le signal de forme.
    """
    splits = _pitcher_game_log(pitcher_id)
    starts = [g for g in splits if _f(g["stat"].get("gamesStarted")) > 0]
    if len(starts) < 2:
        return {"games": 0}
    recent = starts[-n:]
    agg = {"hr": 0.0, "bb": 0.0, "hbp": 0.0, "k": 0.0, "ip": 0.0, "bf": 0.0}
    for g in recent:
        st = g["stat"]
        agg["hr"]  += _f(st.get("homeRuns"))
        agg["bb"]  += _f(st.get("baseOnBalls"))
        agg["hbp"] += _f(st.get("hitByPitch"))
        agg["k"]   += _f(st.get("strikeOuts"))
        agg["ip"]  += _ip_to_float(st.get("inningsPitched"))
        agg["bf"]  += _f(st.get("battersFaced"))
    if agg["ip"] <= 0:
        return {"games": 0}
    return {
        "games":     len(recent),
        "fip":       _fip(agg["hr"], agg["bb"], agg["hbp"], agg["k"], agg["ip"]),
        "k_bb_pct":  round((agg["k"] - agg["bb"]) / agg["bf"], 4) if agg["bf"] > 0 else None,
        "ip_per_gs": round(agg["ip"] / len(recent), 2),
    }


# ── Offense d'équipe, par main du lanceur adverse ───────────────────────────

def get_team_offense(team_id: int, vs_hand: str) -> dict:
    """
    Offense de l'équipe contre la main du lanceur qu'elle affronte.
    `vs_hand` = 'R' ou 'L' (la main du LANCEUR adverse).

    ISO = SLG - AVG (puissance isolée). K% = K/PA.
    `ops_index` = OPS de l'équipe / OPS moyen de la ligue contre cette main.
    C'est le substitut du wRC+ (indisponible dans cette API).
    """
    sit = "vr" if vs_hand.upper() == "R" else "vl"
    st  = _split_stat("teams", team_id, "hitting", sit)
    if not st:
        return None
    ops = _f(st.get("ops"))
    slg = _f(st.get("slg"))
    avg = _f(st.get("avg"))
    pa  = _f(st.get("plateAppearances"))
    if ops <= 0 or pa < 100:
        return None
    lg_ops = LEAGUE["ops_vs_r"] if sit == "vr" else LEAGUE["ops_vs_l"]
    return {
        "vs_hand":   vs_hand.upper(),
        "ops":       ops,
        "slg":       slg,
        "avg":       avg,
        "obp":       _f(st.get("obp")),
        "iso":       round(slg - avg, 4),
        "k_pct":     round(_f(st.get("strikeOuts")) / pa, 4) if pa > 0 else None,
        "bb_pct":    round(_f(st.get("baseOnBalls")) / pa, 4) if pa > 0 else None,
        "hr":        int(_f(st.get("homeRuns"))),
        "pa":        int(pa),
        "ops_index": round(ops / lg_ops, 4) if lg_ops > 0 else 1.0,
    }


def get_team_offense_recent(team_id: int, n_games: int = 12) -> dict:
    """
    Production récente de l'offense (n derniers matchs). Sert de correction de
    forme, pondérée faiblement: la qualité sous-jacente (splits saison) est
    plus prédictive qu'une séquence de 12 matchs.
    """
    key = ("off_recent", team_id, n_games)
    if key in _cache:
        return _cache[key]
    data = _get(f"teams/{team_id}/stats", {
        "stats": "gameLog", "group": "hitting", "season": SEASON,
    })
    splits = (data.get("stats") or [{}])[0].get("splits") or []
    if len(splits) < 5:
        _cache[key] = None
        return None
    recent = splits[-n_games:]
    runs = sum(_f(g["stat"].get("runs")) for g in recent)
    pa   = sum(_f(g["stat"].get("plateAppearances")) for g in recent)
    tb   = sum(_f(g["stat"].get("totalBases")) for g in recent)
    ab   = sum(_f(g["stat"].get("atBats")) for g in recent)
    out = {
        "games":       len(recent),
        "runs_per_g":  round(runs / len(recent), 3),
        "slg":         round(tb / ab, 4) if ab > 0 else None,
        "pa":          int(pa),
    }
    _cache[key] = out
    return out


# ── Bullpen ─────────────────────────────────────────────────────────────────

def get_bullpen(team_id: int) -> dict:
    """
    Qualité du bullpen via le split 'rp' (relève seulement) — pas les stats
    d'équipe globales, qui sont dominées par la rotation.
    """
    st = _split_stat("teams", team_id, "pitching", "rp")
    if not st:
        return None
    ip = _ip_to_float(st.get("inningsPitched"))
    bf = _f(st.get("battersFaced"))
    if ip < 50:
        return None
    hr, bb, hbp, k = (_f(st.get("homeRuns")), _f(st.get("baseOnBalls")),
                      _f(st.get("hitByPitch")), _f(st.get("strikeOuts")))
    return {
        "era":      _f(st.get("era"), LEAGUE["fip"]),
        "whip":     _f(st.get("whip"), 1.30),
        "fip":      _fip(hr, bb, hbp, k, ip),
        "k_bb_pct": round((k - bb) / bf, 4) if bf > 0 else LEAGUE["k_bb_pct"],
        "ip":       round(ip, 1),
    }


def get_bullpen_usage(team_id: int, days: int = 3, ref_date: str = None) -> dict:
    """
    Fatigue du bullpen: manches et lancers de relève sur les `days` derniers
    jours, plus l'état du stoppeur.

    `closer_used_b2b` = le stoppeur (plus de sauvetages) a lancé les 2 derniers
    jours consécutifs → souvent indisponible ou limité.
    """
    ref = datetime.strptime(ref_date, "%Y-%m-%d") if ref_date else datetime.utcnow()
    start = (ref - timedelta(days=days)).strftime("%Y-%m-%d")
    end   = (ref - timedelta(days=1)).strftime("%Y-%m-%d")

    key = ("bp_usage", team_id, start, end)
    if key in _cache:
        return _cache[key]

    sched = _get("schedule", {
        "sportId": 1, "teamId": team_id, "startDate": start, "endDate": end,
    })
    pks = [(d.get("date"), g["gamePk"])
           for d in sched.get("dates", []) for g in d.get("games", [])
           if (g.get("status") or {}).get("abstractGameState") == "Final"]

    rel_ip = 0.0
    rel_pitches = 0.0
    by_pitcher: dict = {}
    for gdate, pk in pks:
        box = _get(f"game/{pk}/boxscore")
        for side in ("home", "away"):
            t = (box.get("teams") or {}).get(side) or {}
            if ((t.get("team") or {}).get("id")) != team_id:
                continue
            for pid in t.get("pitchers", []):
                pdata = (t.get("players") or {}).get(f"ID{pid}") or {}
                st = ((pdata.get("stats") or {}).get("pitching") or {})
                if _f(st.get("gamesStarted")) > 0:
                    continue        # c'est le partant, pas la relève
                ip = _ip_to_float(st.get("inningsPitched"))
                rel_ip      += ip
                rel_pitches += _f(st.get("numberOfPitches"))
                nm = ((pdata.get("person") or {}).get("fullName")) or str(pid)
                by_pitcher.setdefault(nm, []).append(gdate)

    n_games = max(len(pks), 1)
    out = {
        "days":          days,
        "games":         len(pks),
        "rel_ip":        round(rel_ip, 1),
        "rel_ip_per_g":  round(rel_ip / n_games, 2),
        "rel_pitches":   int(rel_pitches),
        "arms_used":     len(by_pitcher),
        "by_pitcher":    by_pitcher,
    }

    closer = _get_closer_name(team_id)
    out["closer"] = closer
    if closer and closer in by_pitcher:
        dates = sorted(set(by_pitcher[closer]))
        out["closer_days_used"] = len(dates)
        out["closer_used_b2b"]  = len(dates) >= 2 and dates[-1] == end
    else:
        out["closer_days_used"] = 0
        out["closer_used_b2b"]  = False
    _cache[key] = out
    return out


def _get_closer_name(team_id: int) -> str:
    """Le stoppeur = le releveur avec le plus de sauvetages cette saison."""
    key = ("closer", team_id)
    if key in _cache:
        return _cache[key]
    # L'endpoint équipe ne donne pas le détail par joueur → passer par le roster.
    # ~12 lanceurs × 1 appel, mis en cache par équipe pour la durée du process.
    roster = _get(f"teams/{team_id}/roster/active").get("roster", [])
    best, best_sv = None, 0
    for p in roster:
        if (p.get("position") or {}).get("abbreviation") != "P":
            continue
        pid = (p.get("person") or {}).get("id")
        if not pid:
            continue
        pd = _get(f"people/{pid}/stats", {
            "stats": "season", "group": "pitching", "season": SEASON,
        })
        sp = (pd.get("stats") or [{}])[0].get("splits") or []
        if not sp:
            continue
        sv = _f(sp[0]["stat"].get("saves"))
        if sv > best_sv:
            best, best_sv = (p.get("person") or {}).get("fullName"), sv
    _cache[key] = best
    return best


# ── Défense et stade ────────────────────────────────────────────────────────

def get_team_defense(team_id: int) -> dict:
    """
    Défense d'équipe. Attention: cette API ne donne ni DRS ni OAA — seulement
    fielding%, erreurs et range factor. C'est un signal FAIBLE, à pondérer
    comme tel. Le cadrage du receveur n'est pas disponible du tout.
    """
    key = ("def", team_id)
    if key in _cache:
        return _cache[key]
    data = _get(f"teams/{team_id}/stats", {
        "stats": "season", "group": "fielding", "season": SEASON,
    })
    splits = (data.get("stats") or [{}])[0].get("splits") or []
    if not splits:
        _cache[key] = None
        return None
    st = splits[0]["stat"]
    out = {
        "fielding_pct":   _f(st.get("fielding"), 0.984),
        "errors":         int(_f(st.get("errors"))),
        "range_factor":   _f(st.get("rangeFactorPer9Inn"), 3.95),
        "games":          int(_f(st.get("gamesPlayed"))),
        # Le cadrage du receveur n'existe pas dans cette API.
        "catcher_framing": None,
    }
    _cache[key] = out
    return out


def get_venue_context(game_pk: int) -> dict:
    """
    Contexte du stade + météo si disponible. La météo n'est publiée qu'à
    l'approche du match — `weather_available: False` signifie "traiter comme
    neutre", pas "conditions neutres confirmées".
    """
    # Le feed live vit sous /api/v1.1/, pas /api/v1/ → requête directe.
    try:
        r = requests.get(
            f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live",
            headers=HEADERS, timeout=TIMEOUT,
        )
        data = r.json() if r.status_code == 200 else {}
    except Exception:
        data = {}
    gd = data.get("gameData") or {}
    venue = gd.get("venue") or {}
    fi = venue.get("fieldInfo") or {}
    w  = gd.get("weather") or {}
    temp = _f(w.get("temp")) if w.get("temp") else None
    wind = w.get("wind") or ""
    return {
        "venue":             venue.get("name", ""),
        "roof":              fi.get("roofType", ""),
        "center":            fi.get("center"),
        "weather_available": bool(w),
        "temp_f":            temp,
        "wind":              wind,
        "condition":         w.get("condition", ""),
    }
