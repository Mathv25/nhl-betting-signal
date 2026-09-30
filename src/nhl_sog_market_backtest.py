"""
Backtest SOG contre le VRAI marche (echantillon 2025-26, nhl_sog_market_fetch).

    python3 nhl_sog_market_backtest.py   -> docs/nhl_sog_market_backtest.json

Pour chaque joueur-match de l'univers present dans le releve:
  - p_marche  = mediane, sur les books cotant les deux cotes a cette ligne, de
                la probabilite sans marge (Shin) de l'Over;
  - cote jouee = cote MEDIANE des books pour ce cote: on ne s'offre pas la
                 meilleure cote du marche (bet365 n'est pas la, et prendre le
                 meilleur prix mesurerait le magasinage, pas le modele);
  - p_modele  = projection walk-forward (meme code que nhl_sog_backtest).

Deux questions:
  1. Le modele apporte-t-il de l'information AU-DELA du marche ?
     p_melange = w x p_modele + (1 - w) x p_marche, w choisi sur la premiere
     moitie chronologique (log-loss), evalue sur la seconde. Si w ~ 0, le
     modele n'ajoute rien.
  2. Les paris du modele brut (edge >= 4 pts, p >= 58%) gagnent-ils a la cote
     mediane ?

Criteres fixes AVANT les resultats (2026-09-30), tous requis:
  a. log-loss du melange < log-loss du marche, sur la seconde moitie;
  b. ROI > 0 sur au moins 100 paris (modele brut, cote mediane);
  c. reussite des paris >= probabilite moyenne annoncee - 3 pts.
Limite: 300 matchs, pas bet365. Un ROI de +5% sur 150 paris a un intervalle
de confiance d'environ +/-15%: meme valide, c'est un indice, pas une preuve.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import odds_api                    # noqa: E402
import nhl_sog_data as D           # noqa: E402
import nhl_sog_model as M          # noqa: E402
import nhl_sog_backtest as B       # noqa: E402
import nhl_sog_lineup as LU        # noqa: E402
import nhl_sog_market_fetch as F   # noqa: E402

MIN_EDGE, MIN_PROB = B.MIN_EDGE, B.MIN_PROB
_HERE = os.path.dirname(os.path.abspath(__file__))


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2)


def market_lines(par_ligne: dict) -> dict:
    """{ligne: {"p": p_over marche, "over": cote med, "under": cote med, "n": books}}"""
    out = {}
    for L, books in par_ligne.items():
        ps, oo, uu = [], [], []
        for bk, c in books.items():
            if c.get("Over") and c.get("Under"):
                d = odds_api.devig([c["Over"], c["Under"]], "shin")
                if d:
                    ps.append(d[0])
                    oo.append(c["Over"])
                    uu.append(c["Under"])
        if len(ps) >= 2:
            out[float(L)] = {"p": _median(ps), "over": _median(oo), "under": _median(uu), "n": len(ps)}
    return out


def ll(p, o):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -math.log(p if o else 1 - p)


def run(verbose=True) -> dict:
    mk = F.load()
    prm = json.load(open(os.path.join(_HERE, "..", "docs", "nhl_sog_backtest.json"), encoding="utf-8"))
    ctx, r_nb = prm["contexte"], prm["nb_r"]
    p24, t24 = D.load("20242025")
    p25, t25 = D.load("20252026")
    recs = B.walk(p25, t25, p24, t24, ctx)

    obs = []            # une ligne par (joueur-match, ligne de marche)
    for x in recs:
        g = mk.get(str(x["gameId"]))
        if not g or not g.get("players"):
            continue
        pl = g["players"].get(LU.norm(x["name"]))
        if not pl:
            continue
        for L, m in market_lines(pl).items():
            pm = M.p_over(L, x["lam"], "nb", r_nb)
            obs.append({"date": x["date"], "gameId": x["gameId"], "name": x["name"], "line": L,
                        "y": x["y"], "p_model": pm, "p_mkt": m["p"], "over": m["over"],
                        "under": m["under"], "n_books": m["n"], "lam": x["lam"]})
    obs.sort(key=lambda o: (o["date"], o["gameId"]))
    n = len(obs)
    half = obs[: n // 2], obs[n // 2:]

    def logloss(rows, f):
        return sum(ll(f(o), o["y"] > o["line"]) for o in rows) / len(rows) if rows else None

    grid = [i / 20 for i in range(0, 21)]
    w_best = min(grid, key=lambda w: logloss(half[0], lambda o: w * o["p_model"] + (1 - w) * o["p_mkt"]))
    ll_rep = {
        "marche_2e_moitie": round(logloss(half[1], lambda o: o["p_mkt"]), 4),
        "modele_2e_moitie": round(logloss(half[1], lambda o: o["p_model"]), 4),
        "melange_2e_moitie": round(logloss(half[1], lambda o: w_best * o["p_model"] + (1 - w_best) * o["p_mkt"]), 4),
        "w_choisi_1re_moitie": w_best,
        "marche_tout": round(logloss(obs, lambda o: o["p_mkt"]), 4),
        "modele_tout": round(logloss(obs, lambda o: o["p_model"]), 4),
    }

    # Paris du modele brut: un par joueur-match, le plus gros edge.
    best = {}
    for o in obs:
        for side, p, pi, odds in (("Over", o["p_model"], o["p_mkt"], o["over"]),
                                  ("Under", 1 - o["p_model"], 1 - o["p_mkt"], o["under"])):
            e = p - pi
            if p >= MIN_PROB and e >= MIN_EDGE:
                k = (o["gameId"], o["name"])
                if k not in best or e > best[k]["edge"]:
                    win = o["y"] > o["line"] if side == "Over" else o["y"] < o["line"]
                    best[k] = {"date": o["date"], "name": o["name"], "line": o["line"], "side": side,
                               "p": p, "p_mkt": pi, "edge": e, "odds": odds, "win": win}
    bets = sorted(best.values(), key=lambda b: b["date"])

    def split(key):
        g = defaultdict(list)
        for b in bets:
            g[key(b)].append(b)
        return {str(k): B.summarize(v) for k, v in sorted(g.items())}

    def bucket(o):
        for lo, hi in B.ODDS_BUCKETS:
            if lo <= o < hi:
                return f"{lo:.2f}-{hi:.2f}" if hi < 99 else f"{lo:.2f}+"

    glob = B.summarize(bets)
    crit = [
        {"critere": "melange < marche en log-loss (2e moitie, w choisi sur la 1re)",
         "ok": ll_rep["melange_2e_moitie"] < ll_rep["marche_2e_moitie"],
         "detail": {k: ll_rep[k] for k in ("melange_2e_moitie", "marche_2e_moitie", "w_choisi_1re_moitie")}},
        {"critere": "ROI > 0 sur 100+ paris a la cote mediane", "ok": glob.get("n", 0) >= 100 and glob.get("roi_pct", -1) > 0,
         "detail": glob},
        {"critere": "reussite >= proba annoncee - 3 pts", "ok": glob.get("n", 0) >= 100
         and glob.get("win_pct", 0) >= glob.get("avg_p", 100) - 3.0,
         "detail": {"reussite": glob.get("win_pct"), "proba": glob.get("avg_p")}},
    ]
    rep = {
        "echantillon": {"matchs_releves": sum(1 for v in mk.values() if v.get("players")),
                        "observations": n, "joueur_matchs": len({(o["gameId"], o["name"]) for o in obs})},
        "logloss": ll_rep,
        "ecart_modele_marche_moyen_pts": round(sum(o["p_model"] - o["p_mkt"] for o in obs) / n * 100, 2) if n else None,
        "calibration_marche": B.calibration([(o["p_mkt"], o["y"] > o["line"]) if o["p_mkt"] >= .5
                                             else (1 - o["p_mkt"], o["y"] < o["line"]) for o in obs]),
        "calibration_modele": B.calibration([(o["p_model"], o["y"] > o["line"]) if o["p_model"] >= .5
                                             else (1 - o["p_model"], o["y"] < o["line"]) for o in obs]),
        "paris": {"global": glob, "par_ligne": split(lambda b: b["line"]), "par_side": split(lambda b: b["side"]),
                  "par_tranche_cote": split(lambda b: bucket(b["odds"])),
                  "calibration": B.calibration([(b["p"], b["win"]) for b in bets])},
        "verdict_detail": crit, "valide": all(c["ok"] for c in crit),
    }
    if verbose:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    return rep


if __name__ == "__main__":
    rep = run()
    out = os.path.join(_HERE, "..", "docs", "nhl_sog_market_backtest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    # Le verdict du marche prime: il est reporte dans les parametres lus par
    # la page et par record_prediction (valide = les deux backtests).
    pp = os.path.join(_HERE, "..", "docs", "nhl_sog_params.json")
    prm = json.load(open(pp, encoding="utf-8"))
    g = rep["paris"]["global"]
    prm["valide"] = bool(prm.get("valide")) and rep["valide"]
    prm["verdict_marche"] = (
        f"contre le marche ({rep['echantillon']['matchs_releves']} matchs 2025-26): "
        f"poids optimal du modele w={rep['logloss']['w_choisi_1re_moitie']:g}, "
        f"paris {g.get('n', 0)} a {g.get('win_pct')}% pour {g.get('avg_p')}% annonces, ROI {g.get('roi_pct')}%")
    if not prm["valide"]:
        prm["verdict"] = "non valide — " + prm["verdict_marche"]
    with open(pp, "w", encoding="utf-8") as f:
        json.dump(prm, f, ensure_ascii=False, indent=1)
    print(f"\n-> {out}\n-> {pp}: {prm['verdict']}")
