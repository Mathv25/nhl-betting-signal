"""
Projections SOG du soir -> docs/nhl_sog.json (lu par l'onglet « SOG »).

Aucune cote n'est lue ici: bet365 n'est dans aucun flux. On publie, pour
chaque joueur de l'univers, lambda et P(Over) a chaque ligne; la cote bet365
se saisit dans la page, qui calcule l'edge et la mise.

Parametres (docs/nhl_sog_params.json), ecrits par nhl_sog_backtest.py:
facteurs de contexte et dispersion ajustes sur la DERNIERE saison complete,
distribution retenue, et le verdict du backtest (« valide »). Tant que le
backtest n'a pas valide le modele, chaque ligne est « informatif »: jamais
« A MISER ».
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests                    # noqa: E402

import nhl_sog_data as D           # noqa: E402
import nhl_sog_model as M          # noqa: E402
import nhl_sog_lineup as LU        # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
WEB = "https://api-web.nhle.com/v1"
SHOW_LINES = [1.5, 2.5, 3.5, 4.5, 5.5]


def params_path() -> str:
    return os.path.join(_HERE, "..", "docs", "nhl_sog_params.json")


def out_path() -> str:
    return os.environ.get("NHL_SOG_PATH") or os.path.join(_HERE, "..", "docs", "nhl_sog.json")


def load_params() -> dict:
    try:
        with open(params_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def season_of(d: date) -> str:
    y = d.year if d.month >= 8 else d.year - 1
    return f"{y}{y + 1}"


def prev_season(s: str) -> str:
    y = int(s[:4]) - 1
    return f"{y}{y + 1}"


def _roster(abbr: str, s) -> dict:
    """{nom_norm: (playerId, pos)} des patineurs de l'effectif courant."""
    try:
        r = s.get(f"{WEB}/roster/{abbr}/current", timeout=20).json()
    except Exception:
        return {}
    out = {}
    for grp in ("forwards", "defensemen"):
        for p in r.get(grp, []):
            nm = f"{p['firstName']['default']} {p['lastName']['default']}"
            out[LU.norm(nm)] = (p["id"], "D" if grp == "defensemen" else "F", nm)
    return out


def run(today: date = None, update_data: bool = True) -> dict:
    # Soir LNH = date en heure de l'Est (en CI la machine est en UTC: apres
    # 20h ET ce serait deja le lendemain).
    import pytz
    today = today or datetime.now(pytz.timezone("America/Toronto")).date()
    cur, prev = season_of(today), prev_season(season_of(today))
    prm = load_params()
    ctx, r_nb, dist = prm.get("contexte"), prm.get("nb_r"), prm.get("distribution", "nb")

    if update_data:
        try:
            D.build(cur)
        except Exception as e:
            print(f"  [SOG] mise a jour des donnees impossible: {e}")
    p_prev, t_prev = D.load(prev)
    p_cur, t_cur = D.load(cur)
    h = M.History(p_prev, t_prev)
    for day, (pr, tr) in sorted(_by_date(p_cur, t_cur, before=today.isoformat()).items()):
        h.add_game(pr, tr)

    s = requests.Session()
    try:
        sched = s.get(f"{WEB}/schedule/{today:%Y-%m-%d}", timeout=20).json()
        games = [g for g in (sched.get("gameWeek") or [{}])[0].get("games", [])
                 if g.get("gameType") == 2 and (sched["gameWeek"][0].get("date") == today.isoformat())]
    except Exception as e:
        print(f"  [SOG] calendrier illisible: {e}")
        games = []

    rows = []
    for g in games:
        sides = [(g["homeTeam"], g["awayTeam"], 1), (g["awayTeam"], g["homeTeam"], 0)]
        match = f"{g['awayTeam']['abbrev']} @ {g['homeTeam']['abbrev']}"
        for team, opp, home in sides:
            abbr, oabbr = team["abbrev"], opp["abbrev"]
            full = f"{team.get('placeName', {}).get('default', '')} {team.get('commonName', {}).get('default', '')}"
            roster = _roster(abbr, s)
            dfo = LU.dfo_lines(full, s)
            for key, (pid, pos, nm) in roster.items():
                el = M.eligibility(h, pid)
                if not el["ok"]:
                    continue
                entry = (dfo.get("players") or {}).get(key)
                pj = M.project(h, pid, abbr, oabbr, home, today.isoformat(), ctx)
                if not pj:
                    continue
                lam = pj["lam"]
                probs = {f"{L:g}": round(M.p_over(L, lam, dist, r_nb), 4) for L in SHOW_LINES}
                rows.append({
                    "playerId": pid, "joueur": nm, "pos": pos, "team": abbr, "opp": oabbr,
                    "home": home, "match": match, "commence": g.get("startTimeUTC", ""),
                    "event_id": g.get("id"), "lam": lam,
                    "p_over": probs,
                    "alignement": LU.status(entry), "trio": (entry or {}).get("line"),
                    "vague_pp": (entry or {}).get("pp"),
                    "source_alignement": dfo.get("source", ""), "maj_alignement": dfo.get("updated", ""),
                    "gp": el["gp"], "gp_saison": el["gp_cur"], "sog_pg": round(el["sog_pg"], 2),
                    "icf_pg": round(el["icf_pg"], 2),
                    "detail": {k: (round(v, 3) if isinstance(v, float) else v)
                               for k, v in pj.items() if k not in ("lam",)},
                })
    rows.sort(key=lambda x: -x["lam"])
    state = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": today.isoformat(), "saison": cur,
        "valide": bool(prm.get("valide")), "verdict": prm.get("verdict", "backtest absent"),
        "distribution": dist, "nb_r": r_nb,
        "seuils": prm.get("seuils") or {"min_edge": 0.04, "min_prob": 0.58},
        "marge_estimee": prm.get("marge_estimee", 0.07),
        "univers": {"min_sog_pg": M.MIN_SOG_PG, "min_icf_pg": M.MIN_ICF_PG, "min_gp": M.MIN_GP},
        "n_matchs": len(games), "joueurs": rows,
    }
    with open(out_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    print(f"  [SOG] {len(rows)} joueur(s) dans l'univers sur {len(games)} match(s) "
          f"— {'valide' if state['valide'] else 'INFORMATIF (backtest non valide)'}")
    return state


def _by_date(players, teams, before: str) -> dict:
    days: dict = {}
    for r in players:
        if r["gameDate"] < before:
            days.setdefault(r["gameDate"], ([], []))[0].append(r)
    for t in teams:
        if t["gameDate"] < before:
            days.setdefault(t["gameDate"], ([], []))[1].append(t)
    return days


def load_state() -> dict:
    try:
        with open(out_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


if __name__ == "__main__":
    st = run(update_data="--no-update" not in sys.argv)
    for x in st["joueurs"][:15]:
        print(f"  {x['joueur']:24} {x['match']:12} lam {x['lam']:.2f}  "
              f"P(>2.5) {x['p_over']['2.5']:.2f}  P(>3.5) {x['p_over']['3.5']:.2f}  {x['alignement']}")
