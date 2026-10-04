"""
Props NFL a ligne differente: distribution empirique des verges autour de la
mediane du joueur (docs/nfl_prop_calibration.json, construit par
nfl_calibration.py).

    ratio = verges du match / mediane du joueur (ses AUTRES matchs de la saison)

Par marche et par tranche de mediane, on garde les quantiles fins du ratio,
zeros compris. En direct:

  1. Pinnacle donne une ligne L_p et P(Over L_p) sans marge. On cherche la
     mediane implicite m telle que P(ratio * m > L_p) = P(Over L_p) — si
     Pinnacle est a 50/50, m ~ L_p; sinon m se deplace.
  2. Pour la ligne bet365 L_b: P(Over L_b) = P(ratio > L_b / m).
     Ligne entiere: un resultat egal a la ligne est un push (rembourse), on
     travaille donc a L_b +/- 0.5 (les verges sont entieres).
  3. edge = cote * p - 1, mise = 1/4 Kelly plafonne (NFL_STAKING).

Miroir JS dans la page (nflProbAt): les deux doivent rester identiques — un
test compare les deux sur les memes entrees.
"""
from __future__ import annotations

import json
import os
from bisect import bisect_left, bisect_right

_HERE = os.path.dirname(os.path.abspath(__file__))
CAL_PATH = os.path.join(_HERE, "..", "docs", "nfl_prop_calibration.json")

# Seuils de l'onglet NFL (props a ligne ajustee). Separes des autres sports.
MIN_EDGE = 0.03
MIN_PROB = 0.55
MIN_ODDS, MAX_ODDS = 1.60, 2.10
SUSPECT_EDGE = 0.12
MIN_MEDIAN = 15.0          # en dessous, l'ecart de ligne ne vaut rien
BOOST_MIN_EDGE = 0.03

_cal_cache: dict = {}


def load_calibration(path: str = None) -> dict:
    p = path or CAL_PATH
    if p not in _cal_cache:
        try:
            with open(p, encoding="utf-8") as f:
                _cal_cache[p] = json.load(f)
        except (OSError, ValueError):
            _cal_cache[p] = {}
    return _cal_cache[p]


def bucket_for(cal_market: dict, median: float) -> dict | None:
    """Tranche [lo, hi) qui contient la mediane (la derniere est ouverte)."""
    buckets = (cal_market or {}).get("buckets") or []
    for b in buckets:
        if b["lo"] <= median < b["hi"]:
            return b
    if buckets and median >= buckets[-1]["lo"]:
        return buckets[-1]
    return buckets[0] if buckets else None


def survival(bucket: dict, r: float) -> float:
    """
    P(ratio > r) sur la distribution empirique (quantiles equi-espaces,
    interpolation lineaire entre deux quantiles, masse ponctuelle respectee).
    """
    q = bucket["q"]
    n = len(q) - 1
    if r < q[0]:
        return 1.0
    if r >= q[-1]:
        return 0.0
    lo, hi = bisect_left(q, r), bisect_right(q, r)
    if hi > lo:                          # r tombe sur un palier (ex. zeros)
        return 1.0 - (hi - 1) / n
    i = lo - 1                           # q[i] < r < q[i+1]
    frac = (r - q[i]) / (q[i + 1] - q[i])
    return 1.0 - (i + frac) / n


def quantile(bucket: dict, u: float) -> float:
    """Inverse de 1 - survival: plus petite valeur r avec P(ratio <= r) >= u."""
    q = bucket["q"]
    n = len(q) - 1
    x = min(max(u, 0.0), 1.0) * n
    i = min(int(x), n - 1)
    return q[i] + (x - i) * (q[i + 1] - q[i])


def _center(b: dict) -> float:
    """Centre d'une tranche; la derniere (ouverte) est centree a 1.25 x lo."""
    return (b["lo"] + b["hi"]) / 2.0 if b["hi"] < 1e8 else b["lo"] * 1.25


def weights(cal_market: dict, median: float) -> list:
    """
    [(tranche, poids)]: interpolation lineaire entre les deux tranches dont
    les centres encadrent la mediane. Sans elle, p sautait de 2 points quand
    la mediane franchissait 50 verges (passage de 25-50 a 50-75).
    """
    bs = (cal_market or {}).get("buckets") or []
    if not bs:
        return []
    cs = [_center(b) for b in bs]
    if median <= cs[0]:
        return [(bs[0], 1.0)]
    if median >= cs[-1]:
        return [(bs[-1], 1.0)]
    for i in range(len(bs) - 1):
        if cs[i] <= median <= cs[i + 1]:
            t = (median - cs[i]) / (cs[i + 1] - cs[i])
            return [(bs[i], 1.0 - t), (bs[i + 1], t)]
    return [(bs[-1], 1.0)]


def survival_at(cal_market: dict, median: float, r: float) -> float:
    return sum(w * survival(b, r) for b, w in weights(cal_market, median))


def is_validated(cal_market: dict, median: float) -> bool:
    """Valide si toute tranche qui pese plus de 25 % est validee hors echantillon."""
    ws = weights(cal_market, median)
    return bool(ws) and all(b.get("valide") for b, w in ws if w > 0.25)


def implied_median(cal_market: dict, line: float, p_over: float) -> float | None:
    """
    Mediane m telle que P(Over line) = p_over (meme convention de push que
    prob_at). P(Over) croit avec m: bissection sur [0.2, 5] x line.
    """
    if not (0.0 < p_over < 1.0) or line <= 0 or not weights(cal_market, line):
        return None
    lo, hi = 0.2 * line, 5.0 * line
    f = lambda m: prob_at(cal_market, m, line, "Over") - p_over   # noqa: E731
    if f(lo) > 0 or f(hi) < 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _is_whole(x: float) -> bool:
    return abs(x - round(x)) < 1e-9


def prob_at(cal_market: dict, median: float, line: float, side: str) -> float | None:
    """
    P(gagner) a la ligne `line` pour une mediane donnee. Ligne entiere: le
    push est exclu des deux cotes (Over gagne a line+1 et plus).
    """
    if median is None or median <= 0 or not weights(cal_market, median):
        return None
    if _is_whole(line):
        p_over = survival_at(cal_market, median, (line + 0.5) / median)
        p_under = 1.0 - survival_at(cal_market, median, (line - 0.5) / median)
    else:
        p_over = survival_at(cal_market, median, line / median)
        p_under = 1.0 - p_over
    return p_over if side == "Over" else p_under


def prob_from_reference(cal_market: dict, ref_line: float, ref_p_over: float,
                        line: float, side: str) -> dict | None:
    """Tout le calcul en direct: mediane implicite puis p a la ligne bet365."""
    m = implied_median(cal_market, ref_line, ref_p_over)
    if m is None:
        return None
    p = prob_at(cal_market, m, line, side)
    if p is None:
        return None
    return {"median": round(m, 2), "p": round(p, 4), "valide": is_validated(cal_market, m)}


def edge(odds: float, p: float) -> float:
    return odds * p - 1.0


def kelly_pct(p: float, odds: float, fraction: float = 0.25, cap_pct: float = 2.0) -> float:
    """Mise en % de la bankroll: Kelly fractionne, plafonne."""
    if not (odds > 1.0) or not (0.0 < p < 1.0):
        return 0.0
    f = (p * odds - 1.0) / (odds - 1.0)
    if f <= 0:
        return 0.0
    return round(min(f * fraction * 100.0, cap_pct), 2)


def prop_status(p: float, odds: float) -> str:
    """« a_miser » / « a_verifier » / « sous_seuil » selon les regles de l'onglet."""
    if p is None or not odds:
        return "sous_seuil"
    e = edge(odds, p)
    if e > SUSPECT_EDGE:
        return "a_verifier"
    if e >= MIN_EDGE and p >= MIN_PROB and MIN_ODDS <= odds <= MAX_ODDS:
        return "a_miser"
    return "sous_seuil"
