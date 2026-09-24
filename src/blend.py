"""
Melange modele-marche, applique AVANT tout calcul d'edge et de mise.

    p_final = w * p_modele + (1 - w) * p_marche_novig

w par marche dans config/betting.json (BLEND_W, defaut 0.3), estime par
blend_backtest.py (walk-forward, log-loss) des que 200+ predictions sont
reglees pour ce marche. L'edge et Kelly se calculent sur p_final, jamais sur
p_modele.

Sans probabilite de marche:
  - marche binaire symetrique (moneyline): retrecissement vers 50%, comme le
    faisait deja le modele MLB — un modele sans marche ne s'ecarte pas seul;
  - autres marches (barreaux K, totaux): p_modele, marque source="modele seul".
"""
from __future__ import annotations

import betting_config

SYMMETRIC = {"mlb_ml", "nhl_ml", "nfl_ml"}


def p_final(p_model, p_market, marche: str) -> tuple:
    """(p_final, source). Probabilites en fraction [0, 1]."""
    if p_model is None:
        return (p_market, "marche seul") if p_market is not None else (None, "aucune")
    w = betting_config.blend_w(marche)
    if p_market is not None and 0.0 < p_market < 1.0:
        return w * p_model + (1.0 - w) * p_market, f"melange w={w:g}"
    if marche in SYMMETRIC:
        return 0.5 + w * (p_model - 0.5), f"retreci vers 50% w={w:g} (pas de marche)"
    return p_model, "modele seul (pas de marche)"


def floor_odds(p: float) -> float:
    """Cote plancher: en dessous, l'edge sur p_final est negatif (cote = 1/p)."""
    return round(1.0 / p, 3) if p and p > 0 else 0.0
