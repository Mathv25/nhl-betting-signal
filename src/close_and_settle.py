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
