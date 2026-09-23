"""
Reconstitution historique des projections K, sans fuite de donnees futures.

Pour chaque depart MLB depuis START_DATE, on recalcule la projection que
mlb_props_analyzer aurait produite LA VEILLE du match, avec seulement ce qui
etait connu a cette date:
  - blend rolling/saison du lanceur: memes regles que
    mlb_rolling_stats.get_pitcher_rolling, sur ses apparitions ANTERIEURES;
  - K% de l'adversaire: byDateRange du debut de saison a la veille du lundi
    de la semaine du match (instantane hebdomadaire, donc jamais posterieur);
  - K% de ligue: somme des 30 equipes au meme instantane;
  - facteur de parc: table statique PARK_FACTORS.

Difference connue avec le direct: le direct utilise le K% adverse CONTRE LA
MAIN du lanceur (statSplits). L'API ignore les dates sur statSplits — elle
renverrait la saison complete, donc des matchs futurs. On prend le K% global.

La projection reconstituee est celle d'AVANT la correction K_MU_FACTOR:
c'est elle que le facteur corrige, donc un nouvel ajustement reste comparable.

Ensuite: biais (projete - reel), puis ajustement par maximum de
vraisemblance d'une binomiale negative K ~ NB(moyenne = c * proj, r):
Var = mu + mu^2 / r. Un seul couple (c, r), global.

Lancer:  cd src && python3 mlb_k_backtest.py            (ecrit ../docs/k_calibration.json)
Cache:   ../.cache/mlb_bt/ (API MLB gratuite, aucun credit Odds API)
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta

import requests

import mlb_k_distribution as KD          # importe scipy proprement (voir ce module)
from mlb_props_analyzer import PARK_FACTORS, K_REGRESSION_EXP
from mlb_starters import TEAM_NAME_MAP
from mlb_rolling_stats import N_PITCHING, _innings_to_float

from scipy.optimize import minimize
from scipy.stats import nbinom, poisson

MLB_API    = "https://statsapi.mlb.com/api/v1"
SEASON     = "2026"
SEASON_START = "2026-03-01"
START_DATE = os.environ.get("KBT_START", "2026-06-01")
END_DATE   = os.environ.get("KBT_END", "")          # defaut: hier
_HERE      = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR  = os.path.join(_HERE, "..", ".cache", "mlb_bt")
OUT_PATH   = os.path.join(_HERE, "..", "docs", "k_calibration.json")
LADDER     = list(range(3, 11))
MIN_PRIOR  = 2      # comme le direct: < 2 departs connus -> pas de projection


# ── Acces API avec cache disque ──────────────────────────────────────────────

def _get(path: str, params: dict, cache_key: str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    fp = os.path.join(CACHE_DIR, cache_key + ".json")
    if os.path.exists(fp):
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    for attempt in range(3):
        try:
            r = requests.get(f"{MLB_API}/{path}", params=params, timeout=20)
            if r.status_code == 200:
                data = r.json()
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                return data
        except Exception:
            pass
        time.sleep(1 + attempt)
    return None


def _norm_team(name: str) -> str:
    return TEAM_NAME_MAP.get(name, name)


# ── Instantanes hebdomadaires du K% equipes ──────────────────────────────────

def _snapshot_day(game_day: date) -> date:
    """Veille du lundi de la semaine du match: aucune donnee du match lui-meme."""
    monday = game_day - timedelta(days=game_day.weekday())
    return monday - timedelta(days=1)


_snap_mem: dict = {}


def team_k_snapshot(snap: date) -> dict:
    """{equipe: (k, pa)} et '__league__' du debut de saison a `snap` inclus."""
    key = snap.isoformat()
    if key in _snap_mem:
        return _snap_mem[key]
    data = _get("teams/stats",
                {"stats": "byDateRange", "group": "hitting", "season": SEASON,
                 "sportIds": 1, "startDate": SEASON_START, "endDate": key},
                f"teams_{key}")
    out = {}
    tot_k = tot_pa = 0.0
    for s in ((data or {}).get("stats") or [{}])[0].get("splits", []):
        name = _norm_team(s.get("team", {}).get("name", ""))
        k  = float(s.get("stat", {}).get("strikeOuts") or 0)
        pa = float(s.get("stat", {}).get("plateAppearances") or 0)
        out[name] = (k, pa)
        tot_k += k
        tot_pa += pa
    out["__league__"] = (tot_k, tot_pa)
    _snap_mem[key] = out
    return out


# ── Projection a la date, memes regles que le direct ────────────────────────

def rolling_blend(prior: list) -> float | None:
    """
    Copie de get_pitcher_rolling appliquee aux apparitions anterieures.
    prior: [{"k": int, "ip": float}, ...] en ordre chronologique.
    """
    all_starts = [g for g in prior if g["ip"] >= 3.0]
    if len(all_starts) < MIN_PRIOR:
        return None
    all_k = [g["k"] for g in all_starts]
    season_avg = sum(all_k) / len(all_k)
    k_vals = [g["k"] for g in all_starts[-N_PITCHING:]]
    if len(k_vals) >= 3:
        mean = sum(k_vals) / len(k_vals)
        std = (sum((x - mean) ** 2 for x in k_vals) / len(k_vals)) ** 0.5
        if std > 0:
            filt = [k for k in k_vals if not (k < mean - 1.0 * std and k <= 3)]
            if filt:
                k_vals = filt
    weights = [1.0 + 0.5 * i for i in range(len(k_vals))]
    rolling = sum(k * w for k, w in zip(k_vals, weights)) / sum(weights)
    return 0.70 * rolling + 0.30 * season_avg


def projection(blend: float, opp: str, home: str, snap: dict, use_park: bool = True) -> float:
    lk, lpa = snap.get("__league__", (0, 0))
    lg = (lk / lpa) if lpa >= 20000 else 0.22
    k, pa = snap.get(opp, (0, 0))
    opp_k = (k / pa) if pa >= 500 else lg
    pf = PARK_FACTORS.get(home, 1.0) if use_park else 1.0
    return blend * ((opp_k / lg) ** K_REGRESSION_EXP) * pf


# ── Collecte des departs ─────────────────────────────────────────────────────

def collect_starts(end: str) -> list:
    sched = _get("schedule", {"sportId": 1, "startDate": START_DATE, "endDate": end,
                              "hydrate": "probablePitcher", "gameType": "R"},
                 f"sched_{START_DATE}_{end}")
    pitcher_ids = set()
    for d in (sched or {}).get("dates", []):
        for g in d.get("games", []):
            for side in ("home", "away"):
                pp = g.get("teams", {}).get(side, {}).get("probablePitcher")
                if pp and pp.get("id"):
                    pitcher_ids.add(pp["id"])
    print(f"  {len(pitcher_ids)} lanceurs partants probables {START_DATE} -> {end}")

    rows = []
    for i, pid in enumerate(sorted(pitcher_ids)):
        log = _get(f"people/{pid}/stats",
                   {"stats": "gameLog", "group": "pitching", "season": SEASON},
                   f"log_{pid}")
        splits = ((log or {}).get("stats") or [{}])[0].get("splits", [])
        apps = []
        for s in splits:
            st = s.get("stat", {})
            outs = st.get("outs")
            ip = (float(outs) / 3.0) if outs is not None else _innings_to_float(st.get("inningsPitched", "0"))
            apps.append({
                "date": s.get("date", ""),
                "k":    int(st.get("strikeOuts") or 0),
                "ip":   ip,
                "gs":   int(st.get("gamesStarted") or 0),
                "opp":  _norm_team(s.get("opponent", {}).get("name", "")),
                "home": bool(s.get("isHome")),
                "team": _norm_team(s.get("team", {}).get("name", "")),
                "name": (s.get("player") or {}).get("fullName", str(pid)),
            })
        apps.sort(key=lambda a: a["date"])
        for j, a in enumerate(apps):
            if not a["gs"] or not (START_DATE <= a["date"] <= end):
                continue
            prior = [p for p in apps[:j] if p["date"] < a["date"]]   # strictement avant
            blend = rolling_blend(prior)
            if blend is None:
                continue
            home_team = a["team"] if a["home"] else a["opp"]
            snap = team_k_snapshot(_snapshot_day(date.fromisoformat(a["date"])))
            ip_prior = [p["ip"] for p in prior if p["gs"]][-KD_IP_WINDOW:]
            rows.append({
                "pid": pid, "name": a["name"], "date": a["date"],
                "opp": a["opp"], "home_team": home_team,
                "blend": round(blend, 3),
                "proj": round(projection(blend, a["opp"], home_team, snap), 3),
                "proj_nopark": round(projection(blend, a["opp"], home_team, snap, False), 3),
                "ip_prior": ip_prior,
                "k": a["k"], "ip": round(a["ip"], 3),
            })
        if (i + 1) % 50 == 0:
            print(f"  ... {i + 1}/{len(pitcher_ids)} lanceurs")
    return rows


KD_IP_WINDOW = 15


# ── Ajustement NB par maximum de vraisemblance ──────────────────────────────

def nb_params(mu: float, r: float) -> tuple:
    """scipy nbinom(n, p) avec moyenne mu et Var = mu + mu^2/r."""
    return r, r / (r + mu)


def fit_nb(proj: list, k: list) -> dict:
    def nll(theta):
        c, log_r = theta
        if c <= 0:
            return 1e12
        r = math.exp(log_r)
        tot = 0.0
        for m, y in zip(proj, k):
            n, p = nb_params(max(c * m, 1e-6), r)
            tot -= nbinom.logpmf(y, n, p)
        return tot

    res = minimize(nll, x0=[1.0, math.log(20.0)], method="Nelder-Mead",
                   options={"xatol": 1e-4, "fatol": 1e-3, "maxiter": 400})
    c, log_r = res.x
    ll_pois = sum(poisson.logpmf(y, max(c * m, 1e-6)) for m, y in zip(proj, k))
    return {"c": round(float(c), 4), "r": round(math.exp(log_r), 3),
            "nll": round(float(res.fun), 2), "nll_poisson_same_c": round(-ll_pois, 2),
            "n": len(k)}


def nb_at_least(mu: float, r: float, kk: int) -> float:
    n, p = nb_params(mu, r)
    return float(nbinom.sf(kk - 1, n, p))


# ── Rapport ─────────────────────────────────────────────────────────────────

def ladder_table(rows: list, prob_fn) -> list:
    out = []
    for kk in LADDER:
        preds = [prob_fn(r, kk) for r in rows]
        hits = [1 if r["k"] >= kk else 0 for r in rows]
        n = len(rows)
        out.append({"k": kk, "n": n,
                    "pred": round(100 * sum(preds) / n, 1),
                    "real": round(100 * sum(hits) / n, 1),
                    "brier": round(sum((p - h) ** 2 for p, h in zip(preds, hits)) / n, 4)})
    return out


def run():
    end = END_DATE or (date.today() - timedelta(days=1)).isoformat()
    rows = collect_starts(end)
    if len(rows) < 200:
        print(f"  Trop peu de departs reconstitues ({len(rows)}) — abandon")
        return None
    proj = [r["proj"] for r in rows]
    ks = [r["k"] for r in rows]
    n = len(rows)
    bias_before = sum(p - y for p, y in zip(proj, ks)) / n

    fit = fit_nb(proj, ks)
    fit_np = fit_nb([r["proj_nopark"] for r in rows], ks)
    c, rr = fit["c"], fit["r"]
    bias_after = sum(c * p - y for p, y in zip(proj, ks)) / n

    # Biais par decile de projection (avant/apres)
    order = sorted(range(n), key=lambda i: proj[i])
    deciles = []
    for d in range(10):
        idx = order[d * n // 10:(d + 1) * n // 10]
        if not idx:
            continue
        mp = sum(proj[i] for i in idx) / len(idx)
        mk = sum(ks[i] for i in idx) / len(idx)
        deciles.append({"decile": d + 1, "n": len(idx), "proj": round(mp, 2),
                        "proj_corr": round(c * mp, 2), "real": round(mk, 2)})

    def current_model(r, kk):
        m = KD.build_ip_mixture_model(r["proj"], r["ip_prior"] or None,
                             (sum(r["ip_prior"]) / len(r["ip_prior"])) if r["ip_prior"] else None)
        return KD.p_at_least(m, kk) / 100.0

    ladder_cur = ladder_table(rows, current_model)
    ladder_nb = ladder_table(rows, lambda r, kk: nb_at_least(c * r["proj"], rr, kk))

    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "window": [START_DATE, end],
        "n_starts": n,
        "mean_proj": round(sum(proj) / n, 3),
        "mean_real": round(sum(ks) / n, 3),
        "bias_before": round(bias_before, 3),
        "bias_after": round(bias_after, 3),
        "fit": fit,
        "fit_without_park": fit_np,
        "deciles": deciles,
        "ladder_current_model": ladder_cur,
        "ladder_nb_fitted": ladder_nb,
        "notes": ("K% adverse global (byDateRange) et non par main; instantane "
                  "hebdomadaire a la veille du lundi; toutes les sorties comptent, "
                  "y compris les departs courts."),
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


if __name__ == "__main__":
    rep = run()
    if rep:
        print(json.dumps({k: rep[k] for k in ("n_starts", "mean_proj", "mean_real",
                                             "bias_before", "bias_after", "fit",
                                             "fit_without_park")}, indent=2))
        print("\nDeciles:", *rep["deciles"], sep="\n  ")
        print("\nLadder modele actuel (brut):", *rep["ladder_current_model"], sep="\n  ")
        print("\nLadder NB ajustee:", *rep["ladder_nb_fitted"], sep="\n  ")
