"""
Estime le poids w du melange modele-marche, par marche, en walk-forward.

    p_final = w * p_modele + (1 - w) * p_marche_novig

Sur data/predictions.csv, pour chaque marche ayant au moins MIN_ROWS (200)
predictions reglees (W/L) avec p_modele ET p_marche_novig:
  - walk-forward par jour: le w applique au jour d est celui qui minimise la
    log-loss sur tous les jours ANTERIEURS (au moins MIN_TRAIN lignes), puis on
    mesure la log-loss hors echantillon du jour d. Aucune fuite de donnees;
  - comparaison hors echantillon: marche seul (w=0), modele seul (w=1), w de
    la config, w walk-forward;
  - w optimal sur tout l'echantillon (celui qu'on proposerait pour la suite).

    cd src && python3 blend_backtest.py            rapport -> ../docs/blend_backtest.json
    cd src && python3 blend_backtest.py --apply    ecrit aussi BLEND_W dans config/betting.json
                                                   (seulement si le walk-forward bat le w actuel)
L'historique importe de results.json est exclu: il n'a pas de p_marche_novig.
"""
from __future__ import annotations

import argparse
import json
import math
import os

import betting_config
import predictions_log as PL

MIN_ROWS  = 200
MIN_TRAIN = 100
GRID      = [i / 20 for i in range(21)]        # 0.00, 0.05, ... 1.00
EPS       = 1e-6
_HERE     = os.path.dirname(os.path.abspath(__file__))
OUT       = os.path.join(_HERE, "..", "docs", "blend_backtest.json")


def logloss(rows: list, w: float) -> float:
    tot = 0.0
    for pm, pk, y in rows:
        p = min(max(w * pm + (1 - w) * pk, EPS), 1 - EPS)
        tot -= math.log(p) if y else math.log(1 - p)
    return tot / len(rows)


def best_w(rows: list) -> float:
    return min(GRID, key=lambda w: logloss(rows, w))


def dataset(rows: list) -> dict:
    by: dict = {}
    for r in rows:
        if r.get("resultat") not in ("W", "L"):
            continue
        pm, pk = PL.to_float(r.get("prob_modele")), PL.to_float(r.get("prob_marche_novig"))
        if pm is None or pk is None or not (0 < pk < 1):
            continue
        by.setdefault(r.get("marche", ""), []).append(
            (r.get("date", ""), pm, pk, 1 if r["resultat"] == "W" else 0))
    return by


def walk_forward(items: list, w_config: float) -> dict:
    items = sorted(items)
    days = sorted({d for d, *_ in items})
    oos, used = [], []
    for d in days:
        train = [(pm, pk, y) for dd, pm, pk, y in items if dd < d]
        test = [(pm, pk, y) for dd, pm, pk, y in items if dd == d]
        if len(train) < MIN_TRAIN:
            continue
        w = best_w(train)
        used.append(w)
        oos.extend((w, t) for t in test)
    if not oos:
        return {}
    tests = [t for _, t in oos]

    def ll_fixed(w):
        return logloss(tests, w)

    ll_wf = sum(-math.log(min(max(w * pm + (1 - w) * pk, EPS), 1 - EPS)) if y
                else -math.log(1 - min(max(w * pm + (1 - w) * pk, EPS), 1 - EPS))
                for w, (pm, pk, y) in oos) / len(oos)
    return {"n_hors_echantillon": len(oos), "logloss_walk_forward": ll_wf,
            "logloss_marche_seul": ll_fixed(0.0), "logloss_modele_seul": ll_fixed(1.0),
            "logloss_w_config": ll_fixed(w_config), "w_dernier": used[-1],
            "w_moyen": sum(used) / len(used)}


def run(apply: bool = False) -> dict:
    data = dataset([r for r in PL.load() if r.get("version_modele") != "historique-results.json"])
    report = {"min_rows": MIN_ROWS, "marches": {}}
    new_w = {}
    for marche, items in sorted(data.items()):
        w_cfg = betting_config.blend_w(marche)
        entry = {"n": len(items), "w_config": w_cfg}
        if len(items) < MIN_ROWS:
            entry["statut"] = f"attente ({len(items)}/{MIN_ROWS} reglees)"
        else:
            full = [(pm, pk, y) for _, pm, pk, y in items]
            entry["w_optimal"] = best_w(full)
            entry.update(walk_forward(items, w_cfg))
            wf = entry.get("logloss_walk_forward")
            better = wf is not None and wf < entry.get("logloss_w_config", float("inf"))
            entry["statut"] = "w propose" if better else "garder le w actuel"
            if better:
                new_w[marche] = entry["w_optimal"]
        report["marches"][marche] = entry
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    if apply and new_w:
        path = betting_config.path()
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg.setdefault("BLEND_W", {}).update(new_w)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
        betting_config.reset()
        report["applique"] = new_w
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    rep = run(ap.parse_args().apply)
    if not rep["marches"]:
        print("Aucune prediction reglee avec p_modele et p_marche_novig pour l'instant.")
    for m, e in rep["marches"].items():
        extra = ""
        if "w_optimal" in e:
            extra = (f" w*={e['w_optimal']:.2f} | log-loss hors echantillon: walk-forward "
                     f"{e.get('logloss_walk_forward', float('nan')):.4f}, marche "
                     f"{e.get('logloss_marche_seul', float('nan')):.4f}, modele "
                     f"{e.get('logloss_modele_seul', float('nan')):.4f}, config "
                     f"{e.get('logloss_w_config', float('nan')):.4f}")
        print(f"{m:12} n={e['n']:5} w_config={e['w_config']:.2f} {e['statut']}{extra}")
    if rep.get("applique"):
        print("BLEND_W mis a jour:", rep["applique"], "— incrementer MODEL_VERSION")
