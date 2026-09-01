"""
Modele de retraits au baton en deux etapes: manches lancees, puis K | manches.

Pourquoi pas un Poisson simple (ni une normale a ecart-type forfaitaire):
la principale source de variance d'un total de K n'est pas le taux de retraits,
c'est la duree du depart. Un lanceur a 1.0 K/manche sorti en 4e ou qui finit la
7e produit deux distributions tres differentes, et un Poisson(lambda) unique
ecrase ce melange — il sous-estime les queues (peu de K comme beaucoup de K).

Modele:
  1. IP ~ distribution discrete empirique des 15 derniers departs, recentree
     sur la moyenne d'IP du lanceur. Moins de MIN_STARTS_EMPIRICAL departs
     connus -> binomiale tronquee sur les retraits (27 outs, p = IP_moy*3/27,
     tronquee a [1, 9] manches).
  2. K | IP ~ Poisson(rate * IP), rate = lambda_ajuste / E[IP].
  3. P(K >= n) = somme_IP P(IP) * P(K >= n | IP)   (marginalisation)

Par construction E[K] = rate * E[IP] = lambda_ajuste: la meme lambda alimente
la projection affichee et chaque barreau du ladder — une seule source de verite.
Et Var(K) = lambda + rate^2 * Var(IP) > lambda: la surdispersion recherchee.
"""
from __future__ import annotations

import os as _os
import sys as _sys

# ── Import de scipy: contournement d'un piege de ce repo ─────────────────────
# Tout tourne avec cwd=src (`cd src && python signal.py`), donc sys.path[0] est
# src/ — et src/signal.py fait de l'ombre au module `signal` de la stdlib.
# numpy importe platform -> subprocess -> signal en transitif: sans retirer src/
# du path pendant l'import, scipy recupere src/signal.py et le pipeline casse.
# On restaure le path juste apres; l'effet de bord est benefique (sys.modules
# garde le vrai module signal pour le reste du process).
_here  = _os.path.dirname(_os.path.abspath(__file__))
_moved = [p for p in _sys.path
          if _os.path.abspath(p or _os.getcwd()) == _here]
for _p in _moved:
    _sys.path.remove(_p)
try:
    from scipy.stats import binom, poisson
finally:
    _sys.path[0:0] = _moved

# Bornes physiques d'un depart, en manches.
IP_MIN = 1.0
IP_MAX = 9.0
OUTS_PER_GAME = 27

# En dessous de ce nombre de departs connus, l'histogramme empirique n'a pas de
# forme exploitable (2-3 valeurs a 33% chacune) -> binomiale tronquee.
MIN_STARTS_EMPIRICAL = 5

# Repli si on ne connait meme pas la moyenne d'IP du lanceur.
DEFAULT_MEAN_IP = 5.3


def _thirds(ip: float) -> float:
    """Arrondit une valeur de manches au tiers (un retrait) le plus proche."""
    return round(ip * 3) / 3.0


def _clip_ip(ip: float) -> float:
    return min(max(ip, 1.0 / 3.0), IP_MAX)


def _normalize(dist: list) -> list:
    total = sum(p for _, p in dist)
    if total <= 0:
        return []
    return [(ip, p / total) for ip, p in dist if p > 0]


def dist_mean(dist: list) -> float:
    return sum(ip * p for ip, p in dist)


def dist_var(dist: list) -> float:
    m = dist_mean(dist)
    return sum(p * (ip - m) ** 2 for ip, p in dist)


def _recenter(dist: list, target_mean: float, iters: int = 8) -> list:
    """
    Ramene E[IP] sur `target_mean` en redimensionnant les valeurs d'IP.

    Multiplicatif (et non additif) pour ne jamais produire d'IP negatif, et
    itere parce que le clip a [1/3, 9] deplace la moyenne a chaque passe.

    Les IP redimensionnees ne sont volontairement PAS requantifiees en tiers de
    manche: le Poisson conditionnel accepte n'importe quel reel, alors qu'un
    arrondi au tiers rend impossible tout recentrage plus fin que ~1/6 de
    manche. Un residu peut subsister si la cible force beaucoup de masse contre
    le plafond de 9 manches.
    """
    if target_mean is None or target_mean <= 0 or not dist:
        return dist
    out = dist
    for _ in range(iters):
        m = dist_mean(out)
        if m <= 0 or abs(m - target_mean) < 0.005:
            break
        scale = target_mean / m
        merged: dict = {}
        for ip, p in out:
            key = round(_clip_ip(ip * scale), 6)
            merged[key] = merged.get(key, 0.0) + p
        out = _normalize(sorted(merged.items()))
    return out


def empirical_ip_distribution(ip_values: list, mean_ip: float = None) -> list:
    """
    Histogramme des manches lancees sur les departs fournis, recentre sur
    `mean_ip` si fourni. Retourne [(ip, prob), ...] trie par ip.
    """
    vals = [_clip_ip(_thirds(float(v))) for v in (ip_values or []) if float(v) > 0]
    if not vals:
        return []
    counts: dict = {}
    w = 1.0 / len(vals)
    for v in vals:
        counts[v] = counts.get(v, 0.0) + w
    dist = _normalize(sorted(counts.items()))
    return _recenter(dist, mean_ip)


def binomial_ip_distribution(mean_ip: float) -> list:
    """
    Repli sans historique suffisant: nombre de retraits ~ Binomiale(27, p)
    tronquee a [3, 27] retraits (1 a 9 manches), avec p cale pour que la
    moyenne tronquee retombe sur `mean_ip`.
    """
    target = mean_ip if mean_ip and mean_ip > 0 else DEFAULT_MEAN_IP
    target = min(max(target, IP_MIN), IP_MAX)

    def build(p: float) -> list:
        p = min(max(p, 0.02), 0.98)
        lo, hi = int(IP_MIN * 3), int(IP_MAX * 3)
        pairs = [(o / 3.0, float(binom.pmf(o, OUTS_PER_GAME, p)))
                 for o in range(lo, hi + 1)]
        return _normalize(pairs)

    p = target * 3.0 / OUTS_PER_GAME
    dist = build(p)
    # La troncature tire la moyenne vers le haut (on coupe les sorties tres
    # courtes) -> on corrige p au lieu de deformer les valeurs d'IP.
    for _ in range(20):
        m = dist_mean(dist)
        if abs(m - target) < 0.01 or m <= 0:
            break
        p *= target / m
        dist = build(p)
    return dist


def build_k_model(lambda_adj: float, ip_values: list = None,
                  mean_ip: float = None) -> dict:
    """
    Assemble le modele pour un lanceur.

    lambda_adj : projection K ajustee (regressee) — la seule lambda du systeme.
    ip_values  : manches des derniers departs (les 15 derniers cote appelant).
    mean_ip    : moyenne d'IP visee; a defaut, celle des `ip_values`.

    Le taux par manche est calcule sur la moyenne EFFECTIVE de la distribution
    retenue, donc E[K] == lambda_adj exactement, quel que soit le repli utilise.
    """
    lam = max(float(lambda_adj or 0.0), 0.0)

    n_starts = len([v for v in (ip_values or []) if float(v) > 0])
    if n_starts >= MIN_STARTS_EMPIRICAL:
        dist   = empirical_ip_distribution(ip_values, mean_ip)
        source = f"empirique {n_starts} departs"
    else:
        target = mean_ip
        if not target and ip_values:
            target = sum(float(v) for v in ip_values) / max(len(ip_values), 1)
        dist   = binomial_ip_distribution(target)
        source = "binomiale tronquee"

    if not dist:
        dist   = binomial_ip_distribution(mean_ip or DEFAULT_MEAN_IP)
        source = "binomiale tronquee"

    eff_mean = dist_mean(dist)
    rate     = (lam / eff_mean) if eff_mean > 0 else 0.0

    return {
        "lambda":   round(lam, 3),
        "ip_dist":  dist,
        "mean_ip":  round(eff_mean, 3),
        "var_ip":   round(dist_var(dist), 3),
        "rate":     round(rate, 4),
        "source":   source,
        "n_starts": n_starts,
    }


def p_at_least(model: dict, n: int) -> float:
    """P(K >= n) en pourcentage, marginalisee sur la distribution d'IP."""
    if n <= 0:
        return 100.0
    rate = model.get("rate", 0.0)
    if rate <= 0:
        return 0.0
    total = 0.0
    for ip, p in model.get("ip_dist", []):
        mu = rate * ip
        if mu <= 0:
            continue
        total += p * float(poisson.sf(n - 1, mu))   # sf(n-1) = P(K >= n)
    return round(total * 100, 2)


def p_over(model: dict, line: float) -> float:
    """
    P(K > line) en pourcentage. Une ligne 4.5 se lit K >= 5; une ligne entiere
    (rare, push possible chez le book) se lit strictement au-dessus.
    """
    import math
    need = int(math.floor(float(line)) + 1)
    return p_at_least(model, need)


def ladder(model: dict, lo: int = 3, hi: int = 10) -> list:
    """Ladder brut (non calibre) P(K >= n) pour n de `lo` a `hi`."""
    return [{"line": n - 0.5, "k_exact": n, "prob": p_at_least(model, n)}
            for n in range(lo, hi + 1)]


def moments(model: dict) -> dict:
    """
    Moments exacts du melange:
      E[K]   = rate * E[IP]                       (== lambda par construction)
      Var[K] = rate * E[IP] + rate^2 * Var[IP]    (Poisson + variance des IP)
    """
    rate = model.get("rate", 0.0)
    e_ip = dist_mean(model.get("ip_dist", []))
    v_ip = dist_var(model.get("ip_dist", []))
    mean = rate * e_ip
    var  = mean + rate ** 2 * v_ip
    return {
        "mean":              round(mean, 4),
        "var":               round(var, 4),
        "std":               round(var ** 0.5, 4),
        "poisson_var":       round(mean, 4),
        "overdispersion":    round(var / mean, 4) if mean > 0 else 0.0,
    }
