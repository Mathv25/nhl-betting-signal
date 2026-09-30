"""
Fermeture, resultat et CLV des predictions de data/predictions.csv.

    python3 close_and_settle.py --close     cotes de fermeture (cron toutes les 30 min)
    python3 close_and_settle.py --settle    resultats (une fois par jour)
    python3 close_and_settle.py             les deux

FERMETURE — Pinnacle sans marge (Shin), releve juste avant le debut du match:
seules les predictions dont le match commence dans les CLOSE_WINDOW_MIN
prochaines minutes sont fermees. Un releve apres le debut serait une cote en
direct, pas une fermeture: on prefere un trou a une fausse valeur.
Marches fermes: moneyline et totaux (decision du 2026-09-23 — pas les props K,
trop cheres a fermer; pas les ecarts -1.5). Un appel par sport concerne, filtre
sur Pinnacle: 1 region-equivalent x 2 marches = 2 credits.

    cote_fermeture  = 1 / p_Pinnacle_Shin     (cote juste de fermeture)
    clv             = cote_prise / cote_fermeture - 1        (misee chez bet365)
    clv_reference   = cote_reference / cote_fermeture - 1    (prix vu ailleurs)

RESULTATS — sources gratuites, zero credit Odds API: API MLB (scores et
retraits des partants), API LNH, scoreboard ESPN (NFL).
    W / L / P (push) / VOID (lanceur non partant, match introuvable apres 3 jours)
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests                 # noqa: E402

import odds_api                 # noqa: E402
import predictions_log as PL     # noqa: E402

CLOSE_WINDOW_MIN = int(os.environ.get("CLOSE_WINDOW_MIN", "") or 35)
SETTLE_AFTER_H   = 4.5          # un match est juge termine 4h30 apres son debut
VOID_AFTER_DAYS  = 3

SPORT_KEYS = {"mlb": "baseball_mlb", "nhl": "icehockey_nhl", "nfl": "americanfootball_nfl"}
# marche du journal -> marche Odds API ferme
CLOSE_MARKETS = {"mlb_ml": "h2h", "nhl_ml": "h2h", "nfl_ml": "h2h",
                 "mlb_total": "totals", "nhl_total": "totals", "nfl_total": "totals"}
REFERENCE_BOOK = "pinnacle"


# ── Utilitaires ─────────────────────────────────────────────────────────────

def _dt(s: str):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    s = s.lower().replace(".", "").strip()
    return {"oakland athletics": "athletics", "st louis cardinals": "st louis cardinals"}.get(s, s)


def _teams(match: str) -> tuple:
    if " @ " not in (match or ""):
        return "", ""
    away, home = match.split(" @ ", 1)
    return away.strip(), home.strip()


def _line(selection: str):
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(?:K)?$", selection or "")
    return float(m.group(1)) if m else None


def _f(v):
    return PL.to_float(v)


# ── Fermeture ───────────────────────────────────────────────────────────────

def _closing_prob(event: dict, marche: str, selection: str):
    """p Shin de Pinnacle pour la selection, ou None."""
    bk = next((b for b in event.get("bookmakers", []) if b.get("key") == REFERENCE_BOOK), None)
    if not bk:
        return None
    key = CLOSE_MARKETS[marche]
    mkt = next((m for m in bk.get("markets", []) if m.get("key") == key), None)
    if not mkt:
        return None
    outs = mkt.get("outcomes", [])
    if key == "h2h":
        team = selection[:-3].strip() if selection.endswith(" ML") else selection
        names = [o.get("name", "") for o in outs]
        if len(outs) != 2 or _norm(team) not in [_norm(n) for n in names]:
            return None
        probs = odds_api.devig([o["price"] for o in outs], "shin")
        return probs[[_norm(n) for n in names].index(_norm(team))] if probs else None
    side = "Over" if selection.startswith("Over") else "Under"
    line = _line(selection)
    pair = [o for o in outs if o.get("point") is not None and abs(float(o["point"]) - line) < 1e-6]
    if len(pair) != 2:
        return None          # Pinnacle cote une autre ligne: pas comparable
    probs = odds_api.devig([o["price"] for o in pair], "shin")
    idx = [o.get("name") for o in pair].index(side) if side in [o.get("name") for o in pair] else None
    return probs[idx] if (probs and idx is not None) else None


def _find_event(events: list, row: dict):
    ev = next((e for e in events if e.get("id") and e.get("id") == row.get("event_id")), None)
    if ev:
        return ev
    away, home = _teams(row.get("match", ""))
    start = _dt(row.get("commence_time"))
    cands = [e for e in events if _norm(e.get("home_team")) == _norm(home)
             and _norm(e.get("away_team")) == _norm(away)]
    if not cands:
        return None
    if start is None:
        return cands[0]
    return min(cands, key=lambda e: abs(((_dt(e.get("commence_time")) or start) - start).total_seconds()))


def close(rows: list, now: datetime = None, client=None) -> int:
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=CLOSE_WINDOW_MIN)
    todo = [r for r in rows
            if r.get("marche") in CLOSE_MARKETS and not r.get("cote_fermeture")
            and (_dt(r.get("commence_time")) or now) > now
            and (_dt(r.get("commence_time")) or horizon + timedelta(1)) <= horizon]
    if not todo:
        print("  [Fermeture] aucune prediction ne commence dans les "
              f"{CLOSE_WINDOW_MIN} prochaines minutes — aucun credit depense")
        return 0
    client = client or odds_api.get_client(os.environ.get("ODDS_API_KEY", ""))
    n = 0
    for sport in sorted({r["sport"] for r in todo}):
        events = client.get(f"sports/{SPORT_KEYS[sport]}/odds", {
            "bookmakers": REFERENCE_BOOK, "markets": "h2h,totals", "oddsFormat": "decimal",
        }, cost=2) or []
        for r in (x for x in todo if x["sport"] == sport):
            ev = _find_event(events, r)
            p = _closing_prob(ev, r["marche"], r["selection"]) if ev else None
            if not p:
                continue
            fair = 1.0 / p
            r["fermeture_novig"] = round(p, 4)
            r["cote_fermeture"] = round(fair, 3)
            fill_clv(r)
            n += 1
    print(f"  [Fermeture] {n}/{len(todo)} prediction(s) fermee(s) a Pinnacle (Shin)")
    return n


def fill_clv(r: dict) -> None:
    fair = _f(r.get("cote_fermeture"))
    if not fair:
        return
    taken = _f(r.get("cote_prise"))
    if taken and taken > 1:
        r["clv"] = round(taken / fair - 1.0, 4)
    ref = _f(r.get("cote_reference"))
    if ref and ref > 1:
        r["clv_reference"] = round(ref / fair - 1.0, 4)


# ── Resultats ───────────────────────────────────────────────────────────────

def _get_json(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=15)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


_score_cache: dict = {}


def mlb_scores(day: str) -> list:
    key = ("mlb", day)
    if key not in _score_cache:
        d = _get_json("https://statsapi.mlb.com/api/v1/schedule",
                      {"sportId": 1, "date": day, "hydrate": "linescore"}) or {}
        out = []
        for de in d.get("dates", []):
            for g in de.get("games", []):
                if g.get("status", {}).get("abstractGameState") != "Final":
                    continue
                t = g.get("teams", {})
                out.append({"home": t.get("home", {}).get("team", {}).get("name", ""),
                            "away": t.get("away", {}).get("team", {}).get("name", ""),
                            "hs": t.get("home", {}).get("score"), "as": t.get("away", {}).get("score"),
                            "start": g.get("gameDate", "")})
        _score_cache[key] = out
    return _score_cache[key]


def nhl_scores(day: str) -> list:
    key = ("nhl", day)
    if key not in _score_cache:
        d = _get_json(f"https://api-web.nhle.com/v1/score/{day}") or {}
        out = []
        for g in d.get("games", []):
            if g.get("gameState") not in ("OFF", "FINAL"):
                continue
            def full(t):
                return f"{t.get('placeName', {}).get('default', '')} {t.get('name', {}).get('default', '')}".strip()
            out.append({"home": full(g.get("homeTeam", {})), "away": full(g.get("awayTeam", {})),
                        "hs": g.get("homeTeam", {}).get("score"), "as": g.get("awayTeam", {}).get("score"),
                        "start": g.get("startTimeUTC", "")})
        _score_cache[key] = out
    return _score_cache[key]


def nfl_scores(day: str) -> list:
    key = ("nfl", day)
    if key not in _score_cache:
        d = _get_json("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
                      {"dates": day.replace("-", "")}) or {}
        out = []
        for ev in d.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            if not comp.get("status", {}).get("type", {}).get("completed"):
                continue
            sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
            h, a = sides.get("home", {}), sides.get("away", {})
            out.append({"home": h.get("team", {}).get("displayName", ""),
                        "away": a.get("team", {}).get("displayName", ""),
                        "hs": _f(h.get("score")), "as": _f(a.get("score")),
                        "start": ev.get("date", "")})
        _score_cache[key] = out
    return _score_cache[key]


SCORES = {"mlb": mlb_scores, "nhl": nhl_scores, "nfl": nfl_scores}

# Props NFL: marche du journal -> (categorie ESPN, cle de la stat).
NFL_PROP_STATS = {
    "nfl_prop_reception_yds": ("receiving", "receivingYards"),
    "nfl_prop_rush_yds":      ("rushing", "rushingYards"),
    "nfl_prop_pass_yds":      ("passing", "passingYards"),
}
_box_cache: dict = {}


def nfl_box(match: str, commence_time: str):
    """
    Feuille de match ESPN (gratuite) d'un match NFL termine:
    {"stats": {(categorie, joueur_norm): {cle: valeur}}, "joueurs": set(joueur_norm)},
    ou None si le match n'est pas termine ou introuvable.
    """
    key = (match, commence_time)
    if key in _box_cache:
        return _box_cache[key]
    away, home = _teams(match)
    start = _dt(commence_time)
    days = {(start + timedelta(days=d)).strftime("%Y%m%d") for d in (-1, 0)} if start else set()
    ev_id = None
    for day in sorted(days):
        d = _get_json("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
                      {"dates": day}) or {}
        for ev in d.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            sides = {c.get("homeAway"): c.get("team", {}).get("displayName", "")
                     for c in comp.get("competitors", [])}
            if (_norm(sides.get("home")) == _norm(home) and _norm(sides.get("away")) == _norm(away)
                    and comp.get("status", {}).get("type", {}).get("completed")):
                ev_id = ev.get("id")
    res = None
    if ev_id:
        s = _get_json("https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary",
                      {"event": ev_id}) or {}
        stats, joueurs = {}, set()
        for team in (s.get("boxscore") or {}).get("players") or []:
            for cat in team.get("statistics") or []:
                keys = cat.get("keys") or []
                for a in cat.get("athletes") or []:
                    nm = _norm((a.get("athlete") or {}).get("displayName", ""))
                    joueurs.add(nm)
                    stats[(cat.get("name"), nm)] = dict(zip(keys, a.get("stats") or []))
        res = {"stats": stats, "joueurs": joueurs} if joueurs else None
    _box_cache[key] = res
    return res


def settle_nfl_prop(row: dict):
    """
    W/L/P d'une prop de verges NFL, VOID si le joueur n'a pas joue, None si
    inconnu (match pas fini ou feuille absente).

    ESPN ne liste dans une categorie que les joueurs qui y ont une stat: un
    receveur a 0 reception n'est pas dans « receiving ». S'il apparait
    ailleurs sur la feuille, il a joue: 0 verge. Absent partout: il n'a pas
    joue, et bet365 annule la prop.
    """
    cat, stat = NFL_PROP_STATS[row["marche"]]
    box = nfl_box(row.get("match", ""), row.get("commence_time", ""))
    if box is None:
        return None
    sel = row.get("selection", "")
    m = re.match(r"^(.*) (Over|Under) ([\d.]+)$", sel)
    if not m:
        return None
    joueur, side, line = _norm(m.group(1)), m.group(2), float(m.group(3))
    if joueur not in box["joueurs"]:
        return "VOID"
    val = _f((box["stats"].get((cat, joueur)) or {}).get(stat)) or 0.0
    if val == line:
        return "P"
    return "W" if (val > line) == (side == "Over") else "L"


_nhl_box: dict = {}


def settle_nhl_sog(row: dict):
    """
    W/L d'un pari de tirs au but LNH par la feuille de match (API LNH, gratuite).
    Joueur absent de la feuille = VOID (bet365 annule). Match pas fini = None.
    """
    gid, pid = row.get("event_id"), row.get("player_id")
    if not gid or not pid:
        return None
    if gid not in _nhl_box:
        _nhl_box[gid] = _get_json(f"https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore")
    box = _nhl_box[gid] or {}
    if box.get("gameState") not in ("OFF", "FINAL"):
        return None
    sog = None
    for side in ("homeTeam", "awayTeam"):
        t = (box.get("playerByGameStats") or {}).get(side) or {}
        for grp in ("forwards", "defense"):
            for p in t.get(grp) or []:
                if str(p.get("playerId")) == str(int(float(pid))):
                    sog = p.get("sog") or 0
    if sog is None:
        return "VOID"
    m = re.search(r" (Over|Under) ([\d.]+) SOG$", row.get("selection", ""))
    if not m:
        return None
    line = float(m.group(2))
    if sog == line:
        return "P"
    return "W" if (sog > line) == (m.group(1) == "Over") else "L"


def close_sog(rows: list, now: datetime = None, client=None) -> int:
    """
    Cote de fermeture des paris de tirs REELLEMENT saisis (cote_prise), dans les
    CLOSE_WINDOW_MIN minutes avant le match. bet365 n'est pas dans le flux:
    fermeture = prix juste de reference a la MEME ligne (Pinnacle Shin, sinon
    mediane sharp, sinon mediane no-vig des books US). 2 credits par match
    (1 marche x regions us,eu), seulement pour les matchs avec un pari saisi.
    """
    import market_reference as MR
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=CLOSE_WINDOW_MIN)
    todo = [r for r in rows if r.get("marche") == "nhl_sog" and r.get("cote_prise")
            and not r.get("cote_fermeture")
            and (_dt(r.get("commence_time")) or now) > now
            and (_dt(r.get("commence_time")) or horizon + timedelta(1)) <= horizon]
    if not todo:
        return 0
    client = client or odds_api.get_client(os.environ.get("ODDS_API_KEY", ""))
    events = client.get("sports/icehockey_nhl/events", {}, cost=0) or []
    n = 0
    by_match = {}
    for r in todo:
        by_match.setdefault(r.get("match", ""), []).append(r)
    for match, rs in by_match.items():
        ev = _find_event(events, dict(rs[0], match=_abbr_to_names(match, events, rs[0])))
        if not ev:
            continue
        data = client.get(f"sports/icehockey_nhl/events/{ev['id']}/odds", {
            "regions": "us,eu", "markets": "player_shots_on_goal", "oddsFormat": "decimal"}, cost=2) or {}
        for r in rs:
            m = re.search(r"^(.*) (Over|Under) ([\d.]+) SOG$", r.get("selection", ""))
            if not m:
                continue
            who, side, line = _norm(m.group(1)), m.group(2), float(m.group(3))
            per_book = {}
            for bm in data.get("bookmakers", []):
                for mk in bm.get("markets", []):
                    for oc in mk.get("outcomes", []):
                        if _norm(oc.get("description")) == who and oc.get("point") is not None \
                                and abs(float(oc["point"]) - line) < 1e-6:
                            per_book.setdefault(bm["key"], {})[oc["name"]] = oc["price"]
            pair = MR.reference_pair(per_book, "Over", "Under")
            if not pair:
                ps = sorted(d[0] for d in (odds_api.devig([v.get("Over"), v.get("Under")], "shin")
                                           for v in per_book.values() if v.get("Over") and v.get("Under")) if d)
                if not ps:
                    continue
                p_over = ps[len(ps) // 2]
            else:
                p_over = pair["Over"]
            p = p_over if side == "Over" else 1 - p_over
            r["fermeture_novig"] = round(p, 4)
            r["cote_fermeture"] = round(1 / p, 3)
            fill_clv(r)
            n += 1
    print(f"  [Fermeture SOG] {n}/{len(todo)} pari(s) de tirs ferme(s)")
    return n


def _abbr_to_names(match: str, events: list, row: dict) -> str:
    """'MTL @ TOR' -> 'Montreal Canadiens @ Toronto Maple Leafs' via l'evenement le plus proche."""
    import nhl_stats
    try:
        inv = {v: k for k, v in getattr(nhl_stats, "TEAM_ABBR", {}).items()}
    except Exception:
        inv = {}
    a, _, h = match.partition(" @ ")
    return f"{inv.get(a.strip(), a.strip())} @ {inv.get(h.strip(), h.strip())}"


def settle_leg(leg: dict):
    """Resultat d'une jambe de boost (meme logique qu'une prediction simple)."""
    row = {"sport": "nfl", "marche": leg.get("marche", ""), "selection": leg.get("selection", ""),
           "match": leg.get("match", ""), "commence_time": leg.get("commence_time", ""),
           "date": (leg.get("commence_time") or "")[:10]}
    if row["marche"] in NFL_PROP_STATS:
        return settle_nfl_prop(row)
    g = _game_result(row)
    return settle_game_row(row, g) if g else None


def settle_boost(row: dict):
    """
    Un boost gagne si toutes ses jambes gagnent. Une jambe perdue suffit a le
    perdre. Une jambe nulle ou annulee: bet365 recalcule a la cote NON boostee
    des jambes restantes, qu'on ne connait pas — VOID, exclu des statistiques
    plutot que regle a un prix invente.
    """
    import json
    try:
        legs = json.loads(row.get("legs") or "[]")
    except ValueError:
        return None
    if not legs:
        return None
    res = [settle_leg(l) for l in legs]
    if "L" in res:
        return "L"
    if None in res:
        return None
    return "W" if all(r == "W" for r in res) else "VOID"


def _game_result(row: dict):
    away, home = _teams(row.get("match", ""))
    start = _dt(row.get("commence_time"))
    days = {row.get("date", "")}
    if start:
        # Le jour du match peut differer en UTC (matchs du soir): on regarde aussi la veille/lendemain.
        days |= {(start + timedelta(days=d)).strftime("%Y-%m-%d") for d in (-1, 0)}
    cands = []
    for day in sorted(x for x in days if x):
        for g in SCORES[row["sport"]](day):
            if _norm(g["home"]) == _norm(home) and _norm(g["away"]) == _norm(away):
                cands.append(g)
    if start is not None:
        # Programme double: le match 1 termine n'est pas le match 2 a venir.
        cands = [g for g in cands
                 if abs(((_dt(g["start"]) or start) - start).total_seconds()) < 3 * 3600]
    if not cands:
        return None
    if start is None:
        return cands[0]
    return min(cands, key=lambda g: abs(((_dt(g["start"]) or start) - start).total_seconds()))


def settle_game_row(row: dict, g: dict):
    hs, as_ = _f(g["hs"]), _f(g["as"])
    if hs is None or as_ is None:
        return None
    away, home = _teams(row.get("match", ""))
    sel = row.get("selection", "")
    m = row.get("marche", "")
    if m.endswith("_ml"):
        team = sel[:-3].strip()
        mine, other = (hs, as_) if _norm(team) == _norm(home) else (as_, hs)
        return "P" if mine == other else ("W" if mine > other else "L")
    if m.endswith("_total"):
        line = _line(sel)
        tot = hs + as_
        if tot == line:
            return "P"
        return "W" if (tot > line) == sel.startswith("Over") else "L"
    # ecarts: "Equipe -1.5" / "Equipe +2.5"
    pt = _line(sel)
    team = sel[: sel.rfind(" ")].strip()
    mine, other = (hs, as_) if _norm(team) == _norm(home) else (as_, hs)
    diff = mine + pt - other
    return "P" if diff == 0 else ("W" if diff > 0 else "L")


_k_cache: dict = {}


def pitcher_ks(name: str, day: str):
    """(K, partant?) du lanceur ce jour-la via l'API MLB, ou None si inconnu."""
    key = (name, day)
    if key in _k_cache:
        return _k_cache[key]
    res = None
    try:
        from mlb_rolling_stats import _search_player_id
        pid = _search_player_id(name)
        if pid:
            d = _get_json(f"https://statsapi.mlb.com/api/v1/people/{pid}/stats",
                          {"stats": "gameLog", "group": "pitching", "season": day[:4]}) or {}
            splits = (d.get("stats") or [{}])[0].get("splits", [])
            games = [s for s in splits if s.get("date") == day]
            if games:
                st = games[0].get("stat", {})
                res = (int(st.get("strikeOuts") or 0), int(st.get("gamesStarted") or 0) > 0)
            else:
                res = (0, False)
    except Exception:
        res = None
    _k_cache[key] = res
    return res


def settle(rows: list, now: datetime = None) -> int:
    now = now or datetime.now(timezone.utc)
    n = 0
    for r in rows:
        if r.get("resultat") or r.get("sport") not in SCORES:
            continue
        start = _dt(r.get("commence_time"))
        if start is None or now - start < timedelta(hours=SETTLE_AFTER_H):
            continue
        res = None
        if r.get("marche") == "props_k":
            kk = pitcher_ks(r.get("joueur", ""), r.get("date", ""))
            if kk is not None:
                ks, started = kk
                k_need = int(_f(r.get("k")) or 0)
                if started:
                    res = "W" if ks >= k_need else "L"
                elif _game_result(r):
                    # Match termine et le lanceur n'a pas ete partant: nul.
                    # Sans score final publie, on attend (retard de l'API).
                    res = "VOID"
        elif r.get("marche") == "nhl_sog":
            res = settle_nhl_sog(r)
        elif r.get("marche") == "nfl_boost":
            res = settle_boost(r)
        elif r.get("marche") in NFL_PROP_STATS:
            res = settle_nfl_prop(r)
        else:
            g = _game_result(r)
            if g:
                res = settle_game_row(r, g)
        if res is None and now - start > timedelta(days=VOID_AFTER_DAYS):
            res = "VOID"
        if res:
            r["resultat"] = res
            fill_clv(r)
            n += 1
    print(f"  [Resultats] {n} prediction(s) reglee(s)")
    return n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--close", action="store_true")
    ap.add_argument("--settle", action="store_true")
    a = ap.parse_args(argv)
    both = not (a.close or a.settle)
    rows = PL.load()
    if not rows:
        print("data/predictions.csv vide — rien a faire")
        return
    n = 0
    if a.close or both:
        n += close(rows)
        try:
            n += close_sog(rows)
        except Exception as e:
            print(f"  [Fermeture SOG] erreur: {e}")
    if a.settle or both:
        n += settle(rows)
    if not n:
        # Rien de ferme ni de regle: aucun fichier touche, donc aucun commit
        # ni redeploiement Pages toutes les 30 minutes.
        return
    PL.save(rows)
    try:
        import performance
        performance.write()
    except Exception as e:
        print(f"  [Performance] erreur: {e}")


if __name__ == "__main__":
    main()
