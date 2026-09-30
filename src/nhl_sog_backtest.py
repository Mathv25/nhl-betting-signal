"""
Backtest walk-forward du modele SOG sur la saison 2025-26 (NON NEGOCIABLE avant
la mise en production).

    python3 nhl_sog_backtest.py            rapport + docs/nhl_sog_backtest.json

Deroulement:
  1. AJUSTEMENT sur 2024-25, en walk-forward lui aussi: facteurs de contexte
     (domicile, back-to-back, rythme) et dispersion r de la binomiale negative.
     Rien de 2025-26 n'y entre.
  2. TEST sur 2025-26: jour par jour, chaque match n'est projete qu'avec les
     matchs des jours precedents (plus 2024-25 comme prior), puis ajoute a
     l'historique. Aucun match du jour ne sert a projeter un autre match du
     meme jour.

COTES: l'historique bet365 n'existe pas (bet365 n'est dans aucun flux). Deux
proxys, et c'est la principale limite de ce backtest:
  A. ligne principale proxy = le .5 le plus proche de la moyenne de tirs du
     joueur avant le match, a 1.87 / 1.87 (marge ~7%, typique d'une prop
     bet365 a -115/-115);
  B. toutes les lignes 1.5-4.5, prix d'un « book naif » = Poisson sur la
     moyenne du joueur, marge 7%. Sert aux tranches de cote.
Un vrai book est plus fin que ces proxys: le ROI mesure ici est une borne
HAUTE. La calibration, elle, ne depend d'aucune cote: c'est le chiffre fiable.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nhl_sog_data as D      # noqa: E402
import nhl_sog_model as M     # noqa: E402

PROXY_ODDS = 1.87
PROXY_MARGIN = 1.07
MIN_EDGE = 0.04               # p_modele - p_implicite (points de probabilite)
MIN_PROB = 0.58
BET_LINES = [1.5, 2.5, 3.5, 4.5]
ODDS_BUCKETS = [(1.01, 1.50), (1.50, 1.65), (1.65, 1.80), (1.80, 2.00), (2.00, 2.50), (2.50, 99)]

_HERE = os.path.dirname(os.path.abspath(__file__))


def _by_date(players: list, teams: list) -> list:
    days = defaultdict(lambda: ([], []))
    for r in players:
        days[r["gameDate"]][0].append(r)
    for t in teams:
        days[t["gameDate"]][1].append(t)
    return sorted(days.items())


def naive_mean(h: M.History, pid: int) -> float:
    """Moyenne de tirs du joueur avant le match (saison en cours, completee par la precedente)."""
    cur = h.games.get(pid, [])
    rows = cur if len(cur) >= M.MIN_GP else (h.prev_rows.get(pid, [])[-20:] + cur)
    return sum(r["sog"] for r in rows) / len(rows) if rows else None


def walk(season_players, season_teams, prev_players=(), prev_teams=(), ctx=None,
         only_eligible=True):
    """Projette chaque joueur-match de la saison, sans fuite. Retourne les enregistrements."""
    h = M.History(prev_players, prev_teams)
    recs = []
    for day, (prow, trow) in _by_date(season_players, season_teams):
        for r in prow:
            pid = r["playerId"]
            el = M.eligibility(h, pid)
            if only_eligible and not el["ok"]:
                continue
            pj = M.project(h, pid, r["team"], r["opp"], r["home"], day, ctx)
            if not pj or pj["lam_base"] <= 0:
                continue
            recs.append({"date": day, "gameId": r["gameId"], "pid": pid, "name": r["name"],
                         "y": r["sog"], "naive": naive_mean(h, pid), **pj})
        h.add_game(prow, trow)
    return recs


def logloss_binary(recs, key_p, lines=BET_LINES):
    s, n = 0.0, 0
    for x in recs:
        for L in lines:
            p = min(max(key_p(x, L), 1e-6), 1 - 1e-6)
            o = x["y"] > L
            s -= math.log(p if o else 1 - p)
            n += 1
    return s / n if n else None


def max_drawdown(pnl: list) -> float:
    peak = cum = dd = 0.0
    for v in pnl:
        cum += v
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return round(dd, 2)


def summarize(bets: list) -> dict:
    n = len(bets)
    if not n:
        return {"n": 0}
    w = sum(b["win"] for b in bets)
    pnl = [(b["odds"] - 1) if b["win"] else -1.0 for b in bets]
    return {"n": n, "win_pct": round(w / n * 100, 1), "roi_pct": round(sum(pnl) / n * 100, 1),
            "units": round(sum(pnl), 1), "max_dd_u": max_drawdown(pnl),
            "avg_odds": round(sum(b["odds"] for b in bets) / n, 2),
            "avg_p": round(sum(b["p"] for b in bets) / n * 100, 1)}


def calibration(pairs: list) -> list:
    """pairs = (p, issue). Tranches de 5 points de 50 a 100."""
    out = []
    for lo in range(50, 100, 5):
        sel = [(p, o) for p, o in pairs if lo / 100 <= p < (lo + 5) / 100]
        if sel:
            out.append({"tranche": f"{lo}-{lo + 5}%", "n": len(sel),
                        "p_moy": round(sum(p for p, _ in sel) / len(sel) * 100, 1),
                        "reel": round(sum(o for _, o in sel) / len(sel) * 100, 1)})
    return out


def run(verbose: bool = True) -> dict:
    p24, t24 = D.load("20242025")
    p25, t25 = D.load("20252026")
    if not p24 or not p25:
        raise SystemExit("cache absent: python3 nhl_sog_data.py 20242025 20252026")

    # 1. Ajustement sur 2024-25
    fit_recs = walk(p24, t24)
    ctx = M.fit_context([{"y": x["y"], "lam_base": x["lam_base"], "home": x["home"],
                          "b2b_me": x["b2b_me"], "b2b_opp": x["b2b_opp"], "pace": x["pace"]}
                         for x in fit_recs])
    fit_recs_ctx = [dict(x, lam=x["lam_base"] * (ctx["home"].get(str(x["home"]), 1)
                                                 * ctx["b2b_me"].get(str(x["b2b_me"]), 1)
                                                 * ctx["b2b_opp"].get(str(x["b2b_opp"]), 1)
                                                 * x["pace"] ** ctx["pace_beta"]))
                    for x in fit_recs]
    r_nb = M.fit_nb_r([(x["y"], x["lam"]) for x in fit_recs_ctx])

    # Surdispersion observee joueur par joueur (2024-25, joueurs eligibles)
    by_p = defaultdict(list)
    for r in p24:
        by_p[r["playerId"]].append(r["sog"])
    vm = []
    for pid, ys in by_p.items():
        if len(ys) >= 40 and sum(ys) / len(ys) >= 2.5:
            m = sum(ys) / len(ys)
            v = sum((y - m) ** 2 for y in ys) / (len(ys) - 1)
            vm.append(v / m)
    vm.sort()

    # 2. Test sur 2025-26
    test = walk(p25, t25, p24, t24, ctx)

    ll = {
        "poisson": logloss_binary(test, lambda x, L: M.p_over(L, x["lam"], "poisson")),
        "binomiale_negative": logloss_binary(test, lambda x, L: M.p_over(L, x["lam"], "nb", r_nb)),
        "naif_poisson_moyenne": logloss_binary(test, lambda x, L: M.p_over(L, max(x["naive"], 0.05), "poisson")),
    }
    dist = "nb" if ll["binomiale_negative"] < ll["poisson"] else "poisson"
    P = (lambda L, lam: M.p_over(L, lam, "nb", r_nb)) if dist == "nb" else \
        (lambda L, lam: M.p_over(L, lam, "poisson"))

    # Calibration (toutes lignes, cote favorisee par le modele)
    cal_pairs = []
    for x in test:
        for L in BET_LINES:
            p = P(L, x["lam"])
            cal_pairs.append((p, x["y"] > L) if p >= 0.5 else (1 - p, x["y"] < L))

    # Paris proxy A (ligne principale a 1.87/1.87)
    bets_a = []
    for x in test:
        L = round(x["naive"] - 0.5) + 0.5
        L = min(max(L, 0.5), 6.5)
        po = P(L, x["lam"])
        for side, p in (("Over", po), ("Under", 1 - po)):
            if p >= MIN_PROB and p - 0.5 >= MIN_EDGE:      # devig 1.87/1.87 = 50%
                win = x["y"] > L if side == "Over" else x["y"] < L
                bets_a.append({"date": x["date"], "name": x["name"], "line": L, "side": side,
                               "p": p, "odds": PROXY_ODDS, "win": win, "lam": x["lam"], "y": x["y"]})

    # Paris proxy B (book naif, toutes lignes) — un pari max par joueur-match
    bets_b = []
    for x in test:
        best = None
        for L in BET_LINES:
            pn = M.p_over(L, max(x["naive"], 0.05), "poisson")
            po = P(L, x["lam"])
            for side, p, pi in (("Over", po, pn), ("Under", 1 - po, 1 - pn)):
                if not (0.02 < pi < 0.98):
                    continue
                odds = round(1 / (pi * PROXY_MARGIN), 2)
                edge = p - pi
                if p >= MIN_PROB and edge >= MIN_EDGE and odds > 1.01 and (best is None or edge > best["edge"]):
                    win = x["y"] > L if side == "Over" else x["y"] < L
                    best = {"date": x["date"], "name": x["name"], "line": L, "side": side, "p": p,
                            "odds": odds, "edge": edge, "win": win, "lam": x["lam"], "y": x["y"]}
        if best:
            bets_b.append(best)

    def split(bets, key):
        g = defaultdict(list)
        for b in bets:
            g[key(b)].append(b)
        return {str(k): summarize(v) for k, v in sorted(g.items())}

    def bucket(o):
        for lo, hi in ODDS_BUCKETS:
            if lo <= o < hi:
                return f"{lo:.2f}-{hi:.2f}" if hi < 99 else f"{lo:.2f}+"
        return "?"

    report = {
        "saison_test": "2025-26", "saison_ajustement": "2024-25",
        "univers": {"min_sog_pg": M.MIN_SOG_PG, "min_icf_pg": M.MIN_ICF_PG, "min_gp": M.MIN_GP},
        "n_joueur_matchs": len(test), "n_joueurs": len({x["pid"] for x in test}),
        "contexte": ctx, "nb_r": round(r_nb, 2),
        "variance_sur_moyenne_2024_25": {"n": len(vm), "mediane": round(vm[len(vm) // 2], 2) if vm else None,
                                         "p10": round(vm[len(vm) // 10], 2) if vm else None,
                                         "p90": round(vm[len(vm) * 9 // 10], 2) if vm else None},
        "logloss": {k: round(v, 4) for k, v in ll.items()}, "distribution": dist,
        "biais_lambda": round(sum(x["y"] for x in test) / sum(x["lam"] for x in test), 3) if test else None,
        "calibration": calibration(cal_pairs),
        "seuils": {"min_edge": MIN_EDGE, "min_prob": MIN_PROB},
        "proxy_A": {"description": "ligne .5 la plus proche de la moyenne, 1.87/1.87",
                    "global": summarize(bets_a), "par_ligne": split(bets_a, lambda b: b["line"]),
                    "par_cote_side": split(bets_a, lambda b: b["side"]),
                    "calibration_paris": calibration([(b["p"], b["win"]) for b in bets_a])},
        "proxy_B": {"description": "book naif Poisson(moyenne), marge 7%, lignes 1.5-4.5",
                    "global": summarize(bets_b), "par_ligne": split(bets_b, lambda b: b["line"]),
                    "par_side": split(bets_b, lambda b: b["side"]),
                    "par_tranche_cote": split(bets_b, lambda b: bucket(b["odds"])),
                    "calibration_paris": calibration([(b["p"], b["win"]) for b in bets_b])},
    }
    report["verdict_detail"] = verdict(report, ll)
    report["valide"] = all(c["ok"] for c in report["verdict_detail"])

    # Parametres pour la saison en direct: ajustes sur 2025-26 (la derniere
    # saison complete), avec 2024-25 comme prior — meme procedure qu'en test.
    live_ctx = M.fit_context([{"y": x["y"], "lam_base": x["lam_base"], "home": x["home"],
                               "b2b_me": x["b2b_me"], "b2b_opp": x["b2b_opp"], "pace": x["pace"]}
                              for x in test])
    live_recs = [(x["y"], x["lam_base"] * (live_ctx["home"].get(str(x["home"]), 1)
                                          * live_ctx["b2b_me"].get(str(x["b2b_me"]), 1)
                                          * live_ctx["b2b_opp"].get(str(x["b2b_opp"]), 1)
                                          * x["pace"] ** live_ctx["pace_beta"])) for x in test]
    report["parametres_direct"] = {"contexte": live_ctx, "nb_r": round(M.fit_nb_r(live_recs), 2),
                                   "distribution": dist, "ajuste_sur": "2025-26"}
    if verbose:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return report


# Criteres fixes AVANT d'avoir vu les resultats (2026-09-30). Tous requis.
CAL_TOL = 3.0          # points
CAL_MIN_N = 300
MIN_BETS = 200


def verdict(rep: dict, ll: dict) -> list:
    out = []
    bad = [c for c in rep["calibration"] if c["n"] >= CAL_MIN_N and 55 <= int(c["tranche"][:2]) < 80
           and abs(c["p_moy"] - c["reel"]) > CAL_TOL]
    out.append({"critere": f"calibration 55-80% a {CAL_TOL:g} pts (tranches n>={CAL_MIN_N})",
                "ok": not bad, "detail": bad})
    best = min(ll["poisson"], ll["binomiale_negative"])
    out.append({"critere": "log-loss meilleure que le naif (Poisson sur la moyenne)",
                "ok": best < ll["naif_poisson_moyenne"],
                "detail": {"modele": round(best, 4), "naif": round(ll["naif_poisson_moyenne"], 4)}})
    ga = rep["proxy_A"]["global"]
    out.append({"critere": f"ROI proxy A > 0 sur {MIN_BETS}+ paris (borne haute)",
                "ok": ga.get("n", 0) >= MIN_BETS and ga.get("roi_pct", -1) > 0, "detail": ga})
    ok_bets = ga.get("n", 0) >= MIN_BETS and ga.get("win_pct", 0) >= ga.get("avg_p", 100) - CAL_TOL
    out.append({"critere": f"paris: reussite >= proba moyenne - {CAL_TOL:g} pts",
                "ok": ok_bets, "detail": {"reussite": ga.get("win_pct"), "proba": ga.get("avg_p")}})
    return out


def write_params(rep: dict) -> str:
    """docs/nhl_sog_params.json, lu par nhl_sog_live et record_prediction."""
    pd = rep["parametres_direct"]
    prm = {"contexte": pd["contexte"], "nb_r": pd["nb_r"], "distribution": pd["distribution"],
           "ajuste_sur": pd["ajuste_sur"], "valide": rep["valide"],
           "verdict": ("valide par le backtest 2025-26" if rep["valide"] else
                       "backtest 2025-26 non concluant: " + "; ".join(
                           c["critere"] for c in rep["verdict_detail"] if not c["ok"])),
           "seuils": {"min_edge": MIN_EDGE, "min_prob": MIN_PROB}, "marge_estimee": PROXY_MARGIN - 1}
    out = os.path.join(_HERE, "..", "docs", "nhl_sog_params.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(prm, f, ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    rep = run()
    out = os.path.join(_HERE, "..", "docs", "nhl_sog_backtest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print(f"\n-> {out}\n-> {write_params(rep)}")
