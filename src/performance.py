"""
Onglet Performance — docs/performance.json, calcule depuis data/predictions.csv.

Par groupe de marches (ML, totaux, props K, NFL, ecarts):
  - CLV moyen avec intervalle de confiance a 95% (mises reelles chez bet365),
    et a part le « CLV papier » du prix de reference vu chez un autre book;
  - ROI des mises reelles (cote_prise et mise_u > 0);
  - Brier du modele contre Brier du marche, sur les MEMES predictions;
  - calibration par decile: probabilite predite moyenne contre taux reel.
Le taux de reussite n'est volontairement pas un indicateur: sans la cote, il
ne dit rien (60% de reussite a 1.50 perd de l'argent).

Deux epoques separees: le journal depuis le 2026-09-23, et l'historique
importe de results.json (versions de modele melangees, paris selectionnes).
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

import predictions_log as PL

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(_HERE, "..", "docs", "performance.json")
HIST = "historique-results.json"

GROUPS = [
    ("ML",       {"mlb_ml", "nhl_ml"}),
    ("Totaux",   {"mlb_total", "nhl_total"}),
    ("Props K",  {"props_k"}),
    ("NFL",      None),                         # tout marche nfl_*
    ("Ecarts",   {"mlb_rl", "nhl_puck"}),
]


def _group_of(marche: str):
    if (marche or "").startswith("nfl_"):
        return "NFL"
    for name, ms in GROUPS:
        if ms and marche in ms:
            return name
    return None


def mean_ci(xs: list) -> dict:
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "ci_low": None, "ci_high": None}
    m = sum(xs) / n
    o = sorted(xs)
    med = o[n // 2] if n % 2 else (o[n // 2 - 1] + o[n // 2]) / 2
    if n < 2:
        return {"n": n, "mean": m, "median": med, "ci_low": None, "ci_high": None}
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    h = 1.96 * sd / math.sqrt(n)
    # La mediane accompagne la moyenne: un seul prix aberrant (cote en direct
    # relevee apres le debut) suffit a deplacer la moyenne de dizaines de points.
    return {"n": n, "mean": m, "median": med, "ci_low": m - h, "ci_high": m + h}


def _profit(r) -> float:
    o, s = PL.to_float(r.get("cote_prise")), PL.to_float(r.get("mise_u")) or 0
    res = r.get("resultat")
    if res == "W":
        return s * (o - 1)
    if res == "L":
        return -s
    return 0.0


def group_stats(rows: list) -> dict:
    resolved = [r for r in rows if r.get("resultat") in ("W", "L")]
    y = {id(r): 1 if r["resultat"] == "W" else 0 for r in resolved}

    clv = mean_ci([PL.to_float(r["clv"]) for r in rows if PL.to_float(r.get("clv")) is not None])
    clv_ref = mean_ci([PL.to_float(r["clv_reference"]) for r in rows
                       if PL.to_float(r.get("clv_reference")) is not None])

    staked = [r for r in rows if (PL.to_float(r.get("mise_u")) or 0) > 0
              and PL.to_float(r.get("cote_prise")) and r.get("resultat") in ("W", "L", "P")]
    stake = sum(PL.to_float(r["mise_u"]) for r in staked)
    roi = {"n": len(staked), "mise_u": stake,
           "profit_u": sum(_profit(r) for r in staked) if staked else 0.0,
           "roi": (sum(_profit(r) for r in staked) / stake) if stake else None}

    both = [r for r in resolved if PL.to_float(r.get("prob_modele")) is not None
            and PL.to_float(r.get("prob_marche_novig")) is not None]
    brier = {
        "n": len(both),
        "modele": (sum((PL.to_float(r["prob_modele"]) - y[id(r)]) ** 2 for r in both) / len(both)) if both else None,
        "marche": (sum((PL.to_float(r["prob_marche_novig"]) - y[id(r)]) ** 2 for r in both) / len(both)) if both else None,
        "n_modele_seul": len([r for r in resolved if PL.to_float(r.get("prob_modele")) is not None]),
    }
    alone = [r for r in resolved if PL.to_float(r.get("prob_modele")) is not None]
    brier["modele_toutes"] = (sum((PL.to_float(r["prob_modele"]) - y[id(r)]) ** 2 for r in alone)
                              / len(alone)) if alone else None

    deciles = []
    for d in range(10):
        lo, hi = d / 10, (d + 1) / 10
        b = [r for r in alone if lo <= PL.to_float(r["prob_modele"]) < hi or (d == 9 and PL.to_float(r["prob_modele"]) == 1.0)]
        if not b:
            continue
        deciles.append({"decile": d + 1, "lo": lo, "hi": hi, "n": len(b),
                        "pred": sum(PL.to_float(r["prob_modele"]) for r in b) / len(b),
                        "reel": sum(y[id(r)] for r in b) / len(b)})
    return {"n_predictions": len(rows), "n_reglees": len(resolved),
            "clv": clv, "clv_reference": clv_ref, "roi": roi, "brier": brier,
            "calibration": deciles}


def compute(rows: list) -> dict:
    epochs = {"journal": [r for r in rows if r.get("version_modele") != HIST],
              "historique": [r for r in rows if r.get("version_modele") == HIST]}
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "epoques": {}}
    for ep, rs in epochs.items():
        groups = {}
        for name, _ in GROUPS:
            sub = [r for r in rs if _group_of(r.get("marche")) == name]
            if sub:
                groups[name] = group_stats(sub)
        out["epoques"][ep] = {"n": len(rs), "groupes": groups}
    return out


def write(path: str = None) -> dict:
    rep = compute(PL.load())
    with open(path or OUT, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    return rep


if __name__ == "__main__":
    rep = write()
    for ep, e in rep["epoques"].items():
        print(f"== {ep}: {e['n']} predictions")
        for g, st in e["groupes"].items():
            c, b, r = st["clv"], st["brier"], st["roi"]
            fmt = lambda v, p=1: "—" if v is None else f"{100 * v:+.{p}f}%"
            print(f"  {g:8} n={st['n_predictions']:5} reglees={st['n_reglees']:5} "
                  f"CLV={fmt(c['mean'])} (n={c['n']}) CLVref={fmt(st['clv_reference']['mean'])} "
                  f"(n={st['clv_reference']['n']}) ROI={fmt(r['roi'])} (n={r['n']}) "
                  f"Brier mod/marche={b['modele'] and round(b['modele'], 4)}/{b['marche'] and round(b['marche'], 4)} (n={b['n']})")
