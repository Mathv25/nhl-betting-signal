"""
Donnees du module SOG (tirs au but LNH) — tout vient de l'API LNH, gratuite.

Deux sources, mises en cache dans data/nhl_sog/ (committe: en CI le disque est
neuf a chaque run, et 1312 play-by-play par saison ne se retelechargent pas):

  1. api.nhle.com/stats/rest — une ligne par joueur et par match:
       summary   -> tirs (SOG), temps de glace, domicile/exterieur, adversaire
       realtime  -> tentatives (iCF = totalShotAttempts), ratees, bloquees
       timeonice -> TOI a egalite (ev), en avantage (pp), en desavantage (sh)
     L'API plafonne une requete a 10 000 lignes: on pagine par semaine.

  2. api-web.nhle.com play-by-play — une ligne par match, pour separer les
     tentatives et les tirs a 5v5 de ceux en avantage numerique (le rapport
     realtime ne donne que le total). Force du tireur lue dans situationCode
     (4 chiffres: gardien ext., patineurs ext., patineurs dom., gardien dom.).

HYPOTHESES
  - SOG = « shot-on-goal » + « goal » (un but est un tir cadre, comme chez
    les books). Les tirs dans un filet desert comptent aussi: bet365 les compte.
  - « 5v5 » = 5 patineurs contre 5 ET deux gardiens dans le filet (1551).
    « pp » = l'equipe du tireur a plus de patineurs que l'adversaire, gardien
    adverse present. Le reste (4v4, 3v3, desavantage, filet desert) = « autre ».
  - TOI a 5v5: l'API ne le donne pas par joueur et par match. On prend le TOI
    « ev » (egalite: 5v5 + 4v4 + 3v3). Le 4v4 pese quelques secondes par match;
    l'erreur est petite et documentee.
"""
from __future__ import annotations

import csv
import gzip
import os
import time
from datetime import date, timedelta

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
REST = "https://api.nhle.com/stats/rest/en"
WEB = "https://api-web.nhle.com/v1"

SEASON_START = {"20242025": date(2024, 10, 4), "20252026": date(2025, 10, 7),
                "20262027": date(2026, 9, 29)}
SEASON_END = {"20242025": date(2025, 4, 18), "20252026": date(2026, 4, 17),
              "20262027": date(2027, 4, 20)}

PLAYER_FIELDS = [
    "season", "gameId", "gameDate", "playerId", "name", "pos", "team", "opp", "home",
    "sog", "icf", "missed", "blocked", "toi", "toi_ev", "toi_pp", "toi_sh",
    "icf_5v5", "sog_5v5", "icf_pp", "sog_pp",
]
TEAM_FIELDS = [
    "season", "gameId", "gameDate", "team", "opp", "home", "gf", "ga",
    "sog_for", "sog_against", "sog_for_5v5", "sog_against_5v5",
    "icf_against_5v5", "pp_toi",
]


def cache_dir() -> str:
    return os.environ.get("NHL_SOG_DATA") or os.path.join(_HERE, "..", "data", "nhl_sog")


def _path(kind: str, season: str) -> str:
    return os.path.join(cache_dir(), f"{kind}_{season}.csv.gz")


def _sec(s) -> float:
    """'12:34' ou secondes -> secondes."""
    if s is None or s == "":
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    m, _, sec = str(s).partition(":")
    return float(m) * 60 + float(sec or 0)


_session = requests.Session()


def _get(url: str, params=None, tries: int = 4):
    for i in range(tries):
        try:
            r = _session.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2 * (i + 1))
                continue
            return None
        except requests.RequestException:
            time.sleep(2 * (i + 1))
    return None


# ── 1. Rapports par joueur et par match ─────────────────────────────────────

def _report(report: str, d0: date, d1: date) -> list:
    exp = (f'gameTypeId=2 and gameDate>="{d0:%Y-%m-%d}" and gameDate<="{d1:%Y-%m-%d} 23:59:59"')
    data = _get(f"{REST}/skater/{report}", {"isAggregate": "false", "isGame": "true",
                                            "start": 0, "limit": -1, "cayenneExp": exp})
    rows = (data or {}).get("data") or []
    if data and data.get("total", 0) > len(rows):
        raise RuntimeError(f"{report} {d0}..{d1}: {data['total']} lignes > {len(rows)} (fenetre trop large)")
    return rows


def fetch_player_games(season: str, d0: date = None, d1: date = None) -> dict:
    """{(gameId, playerId): ligne} des trois rapports fusionnes, semaine par semaine."""
    d0 = d0 or SEASON_START[season]
    d1 = min(d1 or SEASON_END[season], date.today())
    out: dict = {}
    d = d0
    while d <= d1:
        e = min(d + timedelta(days=6), d1)
        summ = _report("summary", d, e)
        real = {(r["gameId"], r["playerId"]): r for r in _report("realtime", d, e)}
        toi = {(r["gameId"], r["playerId"]): r for r in _report("timeonice", d, e)}
        for s in summ:
            k = (s["gameId"], s["playerId"])
            rt, ti = real.get(k, {}), toi.get(k, {})
            out[k] = {
                "season": season, "gameId": s["gameId"], "gameDate": s["gameDate"][:10],
                "playerId": s["playerId"], "name": s.get("skaterFullName", ""),
                "pos": s.get("positionCode", ""), "team": s.get("teamAbbrev", ""),
                "opp": s.get("opponentTeamAbbrev", ""), "home": 1 if s.get("homeRoad") == "H" else 0,
                "sog": s.get("shots") or 0, "icf": rt.get("totalShotAttempts") or 0,
                "missed": rt.get("missedShots") or 0, "blocked": rt.get("shotAttemptsBlocked") or 0,
                "toi": _sec(s.get("timeOnIcePerGame")), "toi_ev": _sec(ti.get("evTimeOnIce")),
                "toi_pp": _sec(ti.get("ppTimeOnIce")), "toi_sh": _sec(ti.get("shTimeOnIce")),
            }
        print(f"  [SOG data] {season} {d}..{e}: {len(summ)} lignes", flush=True)
        d = e + timedelta(days=1)
    return out


# ── 2. Play-by-play: separation 5v5 / avantage numerique ────────────────────

SHOT_TYPES = {"shot-on-goal", "missed-shot", "blocked-shot", "goal"}


def strength(situation: str, shooter_home: bool) -> str:
    """'5v5', 'pp' ou 'autre' du point de vue de l'equipe du tireur."""
    if not situation or len(situation) != 4:
        return "autre"
    ag, a_sk, h_sk, hg = (int(c) for c in situation)
    own, opp = (h_sk, a_sk) if shooter_home else (a_sk, h_sk)
    if ag != 1 or hg != 1:
        # Un filet vide d'un cote ou de l'autre (6e attaquant): ni du 5v5 ni
        # un avantage, et ce temps n'est pas compte dans le TOI « pp ».
        return "autre"
    if own == 5 and opp == 5:
        return "5v5"
    if own > opp:
        return "pp"
    return "autre"


def parse_pbp(pbp: dict) -> tuple:
    """
    (par_joueur, par_equipe) d'un match.
      par_joueur = {playerId: {icf_5v5, sog_5v5, icf_pp, sog_pp}}
      par_equipe = {teamId: {sog, sog_5v5, icf_5v5, goals}} (pour l'equipe qui TIRE)
    """
    team_of = {r["playerId"]: r["teamId"] for r in pbp.get("rosterSpots") or []}
    home_id = (pbp.get("homeTeam") or {}).get("id")
    pl: dict = {}
    tm: dict = {}
    for ev in pbp.get("plays") or []:
        typ = ev.get("typeDescKey")
        if typ not in SHOT_TYPES:
            continue
        # Les tirs de fusillade ne sont ni des tirs officiels ni des buts du
        # match (et bet365 ne les compte pas).
        if (ev.get("periodDescriptor") or {}).get("periodType") == "SO":
            continue
        det = ev.get("details") or {}
        shooter = det.get("shootingPlayerId") or det.get("scoringPlayerId")
        t = team_of.get(shooter)
        if shooter is None or t is None:
            continue
        stg = strength(ev.get("situationCode", ""), t == home_id)
        on_goal = typ in ("shot-on-goal", "goal")
        p = pl.setdefault(shooter, {"icf_5v5": 0, "sog_5v5": 0, "icf_pp": 0, "sog_pp": 0})
        s = tm.setdefault(t, {"sog": 0, "sog_5v5": 0, "icf_5v5": 0, "goals": 0})
        if on_goal:
            s["sog"] += 1
        if typ == "goal":
            s["goals"] += 1
        if stg in ("5v5", "pp"):
            p["icf_" + stg] += 1
            if on_goal:
                p["sog_" + stg] += 1
        if stg == "5v5":
            s["icf_5v5"] += 1
            if on_goal:
                s["sog_5v5"] += 1
    return pl, tm


# ── Construction et cache ───────────────────────────────────────────────────

def _write(path: str, fields: list, rows: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def _read(path: str) -> list:
    if not os.path.exists(path):
        return []
    with gzip.open(path, "rt", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


INT_COLS = {"gameId", "playerId", "home", "sog", "icf", "missed", "blocked",
            "icf_5v5", "sog_5v5", "icf_pp", "sog_pp", "gf", "ga", "sog_for", "sog_against",
            "sog_for_5v5", "sog_against_5v5", "icf_against_5v5"}
FLOAT_COLS = {"toi", "toi_ev", "toi_pp", "toi_sh", "pp_toi"}


def _typed(rows: list) -> list:
    for r in rows:
        for k in list(r):
            if k in INT_COLS:
                r[k] = int(float(r[k] or 0))
            elif k in FLOAT_COLS:
                r[k] = float(r[k] or 0)
    return rows


def load(season: str) -> tuple:
    """(lignes joueur-match, lignes equipe-match) du cache, typees."""
    return _typed(_read(_path("players", season))), _typed(_read(_path("teams", season)))


def build(season: str, refresh: bool = False) -> tuple:
    """
    Met a jour le cache d'une saison. Incremental: seuls les matchs absents du
    cache (ou tous si refresh) sont telecharges. Retourne load(season).
    """
    old_p, old_t = ([], []) if refresh else load(season)
    have = {r["gameId"] for r in old_t}
    d0 = SEASON_START[season]
    if have and not refresh:
        # Incremental: 3 jours de marge (matchs reportes, reprise d'un arret).
        d0 = max(date.fromisoformat(r["gameDate"]) for r in old_t) - timedelta(days=3)
    pg = fetch_player_games(season, d0)
    new_games = sorted({g for g, _ in pg} - have)
    print(f"  [SOG data] {season}: {len(new_games)} nouveau(x) match(s) a lire (play-by-play)")

    players = [r for r in old_p if r["gameId"] not in set(new_games)]
    teams = [r for r in old_t if r["gameId"] not in set(new_games)]
    for i, gid in enumerate(new_games, 1):
        pbp = _get(f"{WEB}/gamecenter/{gid}/play-by-play")
        if not pbp or pbp.get("gameState") not in ("OFF", "FINAL"):
            continue
        pl, tm = parse_pbp(pbp)
        ids = {(pbp.get("homeTeam") or {}).get("id"): pbp["homeTeam"]["abbrev"],
               (pbp.get("awayTeam") or {}).get("id"): pbp["awayTeam"]["abbrev"]}
        rows = [r for (g, _), r in pg.items() if g == gid]
        for r in rows:
            r.update(pl.get(r["playerId"], {"icf_5v5": 0, "sog_5v5": 0, "icf_pp": 0, "sog_pp": 0}))
            players.append(r)
        by_abbr = {ids[t]: v for t, v in tm.items() if t in ids}
        for tid, ab in ids.items():
            opp = next(a for a in ids.values() if a != ab)
            me, them = by_abbr.get(ab, {}), by_abbr.get(opp, {})
            pp = max((r["toi_pp"] for r in rows if r["team"] == ab), default=0.0)
            teams.append({
                "season": season, "gameId": gid, "gameDate": pbp.get("gameDate", "")[:10],
                "team": ab, "opp": opp, "home": 1 if tid == pbp["homeTeam"]["id"] else 0,
                "gf": me.get("goals", 0), "ga": them.get("goals", 0),
                "sog_for": me.get("sog", 0), "sog_against": them.get("sog", 0),
                "sog_for_5v5": me.get("sog_5v5", 0), "sog_against_5v5": them.get("sog_5v5", 0),
                "icf_against_5v5": them.get("icf_5v5", 0), "pp_toi": pp,
            })
        if i % 100 == 0:
            print(f"  [SOG data] {season}: {i}/{len(new_games)} play-by-play", flush=True)
        if i % 200 == 0:
            # Point de reprise: un arret en cours de route ne perd que <200 matchs.
            _write(_path("players", season), PLAYER_FIELDS, players)
            _write(_path("teams", season), TEAM_FIELDS, teams)
        time.sleep(0.15)          # l'API LNH etrangle les rafales

    players.sort(key=lambda r: (r["gameDate"], r["gameId"], r["playerId"]))
    teams.sort(key=lambda r: (r["gameDate"], r["gameId"], r["team"]))
    _write(_path("players", season), PLAYER_FIELDS, players)
    _write(_path("teams", season), TEAM_FIELDS, teams)
    return load(season)


if __name__ == "__main__":
    import sys
    for s in (sys.argv[1:] or ["20252026"]):
        p, t = build(s, refresh="--refresh" in sys.argv)
        print(f"{s}: {len(p)} lignes joueur-match, {len(t)} lignes equipe-match")
