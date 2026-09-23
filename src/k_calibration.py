"""
Calibration par barreau des probabilites K — P(K >= k), k = 3..10.

Regles (fixees le 2026-09-23):
  1. Un barreau n'est calibre qu'avec au moins MIN_N predictions resolues a ce
     barreau dans data/predictions.csv (courbes completes, misees ou non).
     Sinon: probabilite brute affichee, et aucune prop K ne peut etre
     « a miser » sur ce barreau — affichage informatif seulement.
  2. Calibration isotonique (PAV) de l'issue sur la probabilite brute, par
     barreau: la correspondance brute -> calibree est croissante.
  3. Retrecissement vers la brute selon la taille d'echantillon:
         p = n/(n+SHRINK) * p_calibree + SHRINK/(n+SHRINK) * p_brute
  4. Puis PAV sur le ladder du lanceur pour que P(K >= k) reste decroissante
     en k apres calibration.

La brute est la binomiale negative de mlb_k_distribution (deja corrigee par
K_MU_FACTOR). Les deux valeurs sont conservees et affichees.

Lancer:  cd src && python3 k_calibration.py   (tableaux de calibration)
"""
from __future__ import annotations

import json
import math
import os

import predictions_log as PL

MIN_N  = 50
SHRINK = 100.0
MARKET = "props_k"
LADDER = list(range(3, 11))
PLACEHOLDER_ODDS = 1.909      # mlb_props_analyzer.B365_ODDS — cote supposee, pas reelle


# ── Regression isotonique (Pool Adjacent Violators) ─────────────────────────

def pav(values: list, weights: list = None, increasing: bool = True) -> list:
    """Projection isotonique ponderee de `values` (croissante par defaut)."""
    if not values:
        return []
    w = list(weights) if weights else [1.0] * len(values)
    sign = 1.0 if increasing else -1.0
    blocks = []                                   # [somme ponderee, poids, taille]
    for v, wi in zip(values, w):
        blocks.append([sign * v * wi, wi, 1])
        while len(blocks) >= 2 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, ww, n = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += ww
            blocks[-1][2] += n
    out = []
    for s, ww, n in blocks:
        out.extend([sign * s / ww] * n)
    return out


class RungMap:
    """Correspondance isotonique brute -> taux reel pour un barreau."""

    def __init__(self, pairs: list):
        # Ex aequo en x regroupes d'abord (moyenne ponderee): sans ca, l'ordre
        # arbitraire des issues a x egal fausse le PAV.
        groups: dict = {}
        for x, y in pairs:                         # (p_brute, issue 0/1)
            g = groups.setdefault(x, [0.0, 0])
            g[0] += y
            g[1] += 1
        xs = sorted(groups)
        self.n = len(pairs)
        fitted = pav([groups[x][0] / groups[x][1] for x in xs],
                     [groups[x][1] for x in xs])
        # Compresse les blocs: (x moyen pondere du bloc, valeur du bloc)
        self.xs, self.ys = [], []
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and fitted[j + 1] == fitted[i]:
                j += 1
            w = [groups[xs[t]][1] for t in range(i, j + 1)]
            self.xs.append(sum(xs[t] * wt for t, wt in zip(range(i, j + 1), w)) / sum(w))
            self.ys.append(fitted[i])
            i = j + 1

    def __call__(self, p: float) -> float:
        xs, ys = self.xs, self.ys
        if not xs:
            return p
        if p <= xs[0]:
            return ys[0]
        if p >= xs[-1]:
            return ys[-1]
        for a in range(len(xs) - 1):
            if xs[a] <= p <= xs[a + 1]:
                span = xs[a + 1] - xs[a]
                t = (p - xs[a]) / span if span > 0 else 0.0
                return ys[a] + t * (ys[a + 1] - ys[a])
        return ys[-1]


class Calibrator:
    def __init__(self, rows: list = None):
        rows = PL.load() if rows is None else rows
        per_k: dict = {}
        for r in rows:
            if r.get("marche") != MARKET or r.get("resultat") not in ("W", "L"):
                continue
            k = PL.to_float(r.get("k"))
            p = PL.to_float(r.get("prob_brute"))
            if k is None or p is None:
                continue
            per_k.setdefault(int(k), []).append((p, 1 if r["resultat"] == "W" else 0))
        self.n = {k: len(v) for k, v in per_k.items()}
        self.maps = {k: RungMap(v) for k, v in per_k.items() if len(v) >= MIN_N}

    def is_calibrated(self, k: int) -> bool:
        return k in self.maps

    def rung(self, k: int, p_raw: float) -> tuple:
        """(p_utilisee, p_calibree ou None, n) — en fraction [0, 1]."""
        n = self.n.get(k, 0)
        if k not in self.maps:
            return p_raw, None, n
        p_cal = self.maps[k](p_raw)
        w = n / (n + SHRINK)
        return w * p_cal + (1 - w) * p_raw, p_cal, n

    def ladder(self, raw: dict) -> dict:
        """
        raw: {k: p_brute en fraction}. Retourne {k: {"prob", "prob_raw",
        "prob_cal", "calibrated", "n_cal"}} avec prob decroissante en k.
        """
        ks = sorted(raw)
        used, info = [], {}
        for k in ks:
            p, pc, n = self.rung(k, raw[k])
            used.append(p)
            info[k] = {"prob_raw": raw[k], "prob_cal": pc,
                       "calibrated": pc is not None, "n_cal": n}
        mono = pav(used, increasing=False)
        for k, p in zip(ks, mono):
            info[k]["prob"] = min(max(p, 0.0), 1.0)
        return info


_default = None


def default() -> Calibrator:
    """Calibrateur charge une fois par execution depuis data/predictions.csv."""
    global _default
    if _default is None:
        try:
            _default = Calibrator()
        except Exception:
            _default = Calibrator(rows=[])
    return _default


def reset() -> None:
    global _default
    _default = None


# ── Tableaux pour l'utilisateur ─────────────────────────────────────────────

def rung_from_line(line) -> int:
    """Over 5.5 -> K >= 6; Over 4.0 -> K >= 5 (4 = push)."""
    return int(math.floor(float(line))) + 1


def resolved_bets_table(bets: list) -> list:
    """
    Paris K resolus de docs/results.json, par barreau: n, prob moyenne
    annoncee, prob implicite moyenne de la cote prise, taux reel, ROI a 1u.
    Attention: ce sont des paris SELECTIONNES (biais de selection), et
    `our_prob` melange trois versions du modele.
    """
    rows: dict = {}
    for b in bets:
        if b.get("market_type") != "strikeouts" or b.get("result") not in ("W", "L"):
            continue
        k = rung_from_line(b.get("line", 0))
        rows.setdefault(k, []).append(b)
    out = []
    for k in sorted(rows):
        bs = rows[k]
        n = len(bs)
        wins = sum(1 for b in bs if b["result"] == "W")
        odds = [float(b.get("b365_odds") or 0) for b in bs]
        # 1.909 = B365_ODDS, la cote FIXE supposee du 8 juin au 7 juillet — pas
        # une cote prise. La compter inventerait un ROI.
        with_odds = [(b, o) for b, o in zip(bs, odds)
                     if o > 1.0 and abs(o - PLACEHOLDER_ODDS) > 1e-6]
        roi = None
        if with_odds:
            profit = sum((o - 1.0) if b["result"] == "W" else -1.0 for b, o in with_odds)
            roi = 100.0 * profit / len(with_odds)
        out.append({
            "k": k, "n": n,
            "prob_annoncee": round(sum(float(b.get("our_prob") or 0) for b in bs) / n, 1),
            "n_cote": len(with_odds),
            "prob_implicite": (round(100.0 * sum(1.0 / o for _, o in with_odds) / len(with_odds), 1)
                               if with_odds else None),
            "taux_reel": round(100.0 * wins / n, 1),
            "roi_pct": round(roi, 1) if roi is not None else None,
        })
    return out


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "docs", "results.json"), encoding="utf-8") as f:
        bets = json.load(f).get("bets", [])
    print("Paris K resolus (results.json — selectionnes, versions melangees):")
    print(f"{'K>=':>4} {'n':>5} {'prob ann.':>9} {'n cote':>7} {'impl. cote':>10} {'reel':>6} {'ROI':>7}")
    for r in resolved_bets_table(bets):
        impl = f"{r['prob_implicite']:.1f}" if r["prob_implicite"] is not None else "—"
        roi = f"{r['roi_pct']:+.1f}%" if r["roi_pct"] is not None else "—"
        print(f"{r['k']:>4} {r['n']:>5} {r['prob_annoncee']:>8.1f}% {r['n_cote']:>7} {impl:>10} "
              f"{r['taux_reel']:>5.1f}% {roi:>7}")
    cal = default()
    print("\nBarreaux calibres depuis data/predictions.csv:",
          {k: cal.n.get(k, 0) for k in LADDER}, f"(seuil {MIN_N})")
