"""
Modele de score LNH (2026-09-24): Dixon-Coles en temps reglementaire, buts
dans un filet desert, prolongation et fusillade.

Couches, dans l'ordre:
  1. Temps reglementaire HORS filet desert: Poisson(lh) x Poisson(la) avec la
     correction de Dixon-Coles sur 0-0, 1-0, 0-1, 1-1 (parametre RHO).
  2. Filet desert: a la fin, l'equipe qui mene par m (1 ou 2) marque dans un
     filet desert avec la probabilite EN_Q[m] (puis un second but avec EN_Q2).
     Deplace de la masse de l'ecart m vers m+1: plus de victoires par 2 buts,
     plus de buts au total — ce qu'un Poisson ne produit pas.
  3. Egalite apres 60 minutes: prolongation (P_OT) ou fusillade. En
     prolongation, legere prime a la meilleure equipe (OT_HOME + OT_K x d,
     d = (lh - la) / (lh + la)); en fusillade, SO_HOME (~50/50).
     Le vainqueur d'un match a egalite gagne par UN but, et le total officiel
     des livres ajoute un but (but en prolongation, ou but de fusillade).

Les lambdas en entree sont des buts PAR MATCH toutes situations (ce que
donnent les stats d'equipe): REG_SHARE les ramene aux buts en temps
reglementaire hors filet desert.

Parametres estimes par nhl_dc_fit.py sur les saisons passees
(docs/nhl_dc_params.json). Ne pas les retoucher a la main.
"""
from __future__ import annotations

import math

# ── Parametres estimes (nhl_dc_fit.py, 3936 matchs 2023-24 a 2025-26) ───────
# RHO quasi nul: en LNH, les scores faibles ne sont pas sur-representes par
#   rapport a un Poisson; la correction est gardee mais ne pese presque rien.
# EN_Q: l'equipe qui mene par 1 marque dans un filet desert 48% du temps,
#   par 2: 67%. C'est ce qui bat le Poisson sur les totaux (log-loss Over 5.5
#   en walk-forward: 0.707 contre 0.717, puis 0.697 contre 0.714).
# OT_K: la « prime a la meilleure equipe » vaut 0.4 en echantillon mais
#   degrade la moneyline en prevision (walk-forward: 0.6834 a k=0 contre
#   0.6845 a k=0.4). Retenu: 0. Seules restent la legere prime a domicile en
#   prolongation (51%) et en fusillade (52%).
RHO       = -0.004
EN_Q      = {1: 0.479, 2: 0.672}
EN_Q2     = 0.092
P_OT      = 0.680
OT_HOME   = 0.01
OT_K      = 0.0
SO_HOME   = 0.522
REG_SHARE = 0.9141
MAX_GOALS = 12


def _pois(lam: float, k: int) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def tau(h: int, a: int, lh: float, la: float, rho: float) -> float:
    """Correction de Dixon-Coles (1997) sur les scores faibles."""
    if h == 0 and a == 0:
        return 1.0 - lh * la * rho
    if h == 0 and a == 1:
        return 1.0 + lh * rho
    if h == 1 and a == 0:
        return 1.0 + la * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def reg_matrix(lh: float, la: float, rho: float = None, n: int = MAX_GOALS) -> list:
    """P(h, a) en temps reglementaire hors filet desert, normalisee."""
    rho = RHO if rho is None else rho
    m = [[max(_pois(lh, h) * _pois(la, a) * tau(h, a, lh, la, rho), 0.0)
          for a in range(n + 1)] for h in range(n + 1)]
    tot = sum(map(sum, m))
    return [[x / tot for x in row] for row in m]


def with_empty_net(m: list, q: dict = None, q2: float = None) -> list:
    """Ajoute les buts dans un filet desert de l'equipe qui mene par 1 ou 2."""
    q = EN_Q if q is None else q
    q2 = EN_Q2 if q2 is None else q2
    n = len(m) - 1
    out = [[0.0] * (n + 3) for _ in range(n + 3)]
    for h in range(n + 1):
        for a in range(n + 1):
            p = m[h][a]
            if p == 0:
                continue
            d = h - a
            qm = q.get(abs(d), 0.0)
            if qm <= 0:
                out[h][a] += p
                continue
            one, two = qm * (1 - q2), qm * q2
            out[h][a] += p * (1 - qm)
            if d > 0:
                out[h + 1][a] += p * one
                out[h + 2][a] += p * two
            else:
                out[h][a + 1] += p * one
                out[h][a + 2] += p * two
    return out


def final_matrix(lh: float, la: float, params: dict = None) -> list:
    """Temps reglementaire complet (filet desert inclus), a partir de lambdas par match."""
    p = params or {}
    share = p.get("reg_share", REG_SHARE)
    base = reg_matrix(lh * share, la * share, p.get("rho"))
    return with_empty_net(base, p.get("en_q"), p.get("en_q2"))


def ot_home_prob(lh: float, la: float, params: dict = None) -> float:
    """P(domicile gagne | egalite apres 60 min), prolongation puis fusillade."""
    p = params or {}
    d = (lh - la) / (lh + la) if (lh + la) > 0 else 0.0
    p_ot_home = min(max(0.5 + p.get("ot_home", OT_HOME) + p.get("ot_k", OT_K) * d, 0.05), 0.95)
    p_ot = p.get("p_ot", P_OT)
    return p_ot * p_ot_home + (1 - p_ot) * p.get("so_home", SO_HOME)


def game_probs(lh: float, la: float, params: dict = None) -> dict:
    """
    Probabilites des marches principaux. Totaux et ecarts comme les livres:
    le total compte le but de prolongation ou de fusillade.
    """
    m = final_matrix(lh, la, params)
    n = len(m)
    reg_h = sum(m[h][a] for h in range(n) for a in range(n) if h > a)
    reg_a = sum(m[h][a] for h in range(n) for a in range(n) if a > h)
    tie = 1.0 - reg_h - reg_a
    p_oh = ot_home_prob(lh, la, params)
    home_ml = reg_h + tie * p_oh
    # Un match a egalite se gagne par un but: jamais -1.5.
    home_m15 = sum(m[h][a] for h in range(n) for a in range(n) if h - a >= 2)
    away_m15 = sum(m[h][a] for h in range(n) for a in range(n) if a - h >= 2)

    def over(line):
        s = 0.0
        for h in range(n):
            for a in range(n):
                tot = h + a + (1 if h == a else 0)
                if tot > line:
                    s += m[h][a]
        return s

    return {
        "reg_home": reg_h, "reg_away": reg_a, "reg_tie": tie,
        "home_ml": home_ml, "away_ml": 1.0 - home_ml,
        "home_-1.5": home_m15, "away_+1.5": 1.0 - home_m15,
        "away_-1.5": away_m15, "home_+1.5": 1.0 - away_m15,
        "over": over,
    }


# ── Gardien partant ─────────────────────────────────────────────────────────
LEAGUE_GA60   = 3.058     # buts par equipe et par match, 2023-24 a 2025-26 (nhl_dc_fit.py)
GSAX_SHRINK_S = 90000.0   # secondes de glace « a priori » (25 h): retrecit un petit echantillon


def goalie_multiplier(gsax: float, icetime_s: float, league_ga60: float = None) -> float:
    """
    Multiplicateur du lambda ADVERSE selon le gardien partant:
        GSAx/60 retreci = (xG - G) / heures x t / (t + T0)
        mult = (GA60_ligue - GSAx60) / GA60_ligue
    Un gardien a +0.3 GSAx/60 sur une saison pleine baisse le lambda adverse
    d'environ 10%. Borne a [0.80, 1.20].
    """
    lg = league_ga60 or LEAGUE_GA60
    if not icetime_s or icetime_s <= 0:
        return 1.0
    g60 = gsax / (icetime_s / 3600.0) * (icetime_s / (icetime_s + GSAX_SHRINK_S))
    return round(min(max((lg - g60) / lg, 0.80), 1.20), 4)
