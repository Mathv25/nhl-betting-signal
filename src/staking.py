"""
Gestion des mises — un seul calcul pour tous les marches (2026-09-24).

Mises en % du bankroll (1 unite = 1%, convention du tracker):
  1. Kelly fractionne:   f* = (p x cote - 1) / (cote - 1),  mise = KELLY_FRACTION x f*
  2. plafond par pari:   MAX_BET_PCT (1.5%)
  3. plafond par soir:   MAX_NIGHT_PCT (3%) d'exposition totale; au-dela, toutes
                         les mises du soir sont reduites proportionnellement.
p est TOUJOURS p_final (blend.py), jamais p_modele.

Cote plancher = 1 / p_final: en dessous, l'edge est negatif et Kelly vaut 0.

Reglages: config/betting.json, STAKING.
"""
from __future__ import annotations

import betting_config

DEFAULTS = {"KELLY_FRACTION": 0.25, "MAX_BET_PCT": 1.5, "MAX_NIGHT_PCT": 3.0}


def settings() -> dict:
    s = dict(DEFAULTS)
    s.update({k: float(v) for k, v in (betting_config.load().get("STAKING") or {}).items()
              if not k.startswith("_")})
    return s


def kelly_pct(p: float, odds: float) -> float:
    """Mise en % du bankroll pour un pari isole (Kelly fractionne, plafonne)."""
    try:
        p, o = float(p), float(odds)
    except (TypeError, ValueError):
        return 0.0
    if o <= 1.0 or not (0.0 < p < 1.0):
        return 0.0
    f = (p * o - 1.0) / (o - 1.0)
    if f <= 0:
        return 0.0
    s = settings()
    return round(min(f * s["KELLY_FRACTION"] * 100.0, s["MAX_BET_PCT"]), 2)


def floor_odds(p: float) -> float:
    """Cote plancher: edge nul sur p_final."""
    return round(1.0 / p, 3) if p and p > 0 else 0.0


def plan_night(stakes: list, already: float = 0.0) -> tuple:
    """
    Reduit proportionnellement les mises d'un soir pour que l'exposition totale
    ne depasse pas MAX_NIGHT_PCT. `already` = mises deja placees ce soir (elles
    ne se reduisent plus). Retourne (mises ajustees, facteur applique).
    """
    cap = settings()["MAX_NIGHT_PCT"]
    room = max(cap - float(already or 0.0), 0.0)
    total = sum(max(float(x), 0.0) for x in stakes)
    if total <= room or total <= 0:
        return [round(max(float(x), 0.0), 2) for x in stakes], 1.0
    k = room / total
    return [round(max(float(x), 0.0) * k, 2) for x in stakes], round(k, 4)


def apply_night(bets: list, p_key: str = "p_final", odds_key: str = "odds",
                night_key: str = "date") -> list:
    """
    Mises d'une liste de paris « a miser » (dicts): Kelly plafonne puis plafond
    par soir. Ecrit stake_pct, stake_raw_pct et night_factor dans chaque pari.
    """
    by_night: dict = {}
    for b in bets:
        b["stake_raw_pct"] = kelly_pct(b.get(p_key), b.get(odds_key))
        by_night.setdefault(b.get(night_key, ""), []).append(b)
    for group in by_night.values():
        adj, k = plan_night([b["stake_raw_pct"] for b in group])
        for b, s in zip(group, adj):
            b["stake_pct"], b["night_factor"] = s, k
    return bets


def apply_to_signal(output: dict) -> int:
    """
    Plafond par soir sur les paris « a miser » du signal qui ont une vraie cote
    chez un book autorise (NFL a_miser, value bets LNH). Reecrit leur mise.
    Retourne le nombre de paris concernes. En pratique vide tant que bet365
    n'est pas dans le flux: la mise se decide alors dans la page, a la saisie.
    """
    try:
        import pytz
        from datetime import datetime
        et = pytz.timezone("America/Toronto")

        def night(ct):
            return datetime.fromisoformat(ct.replace("Z", "+00:00")).astimezone(et).strftime("%Y-%m-%d")
    except Exception:          # pragma: no cover
        def night(ct):
            return (ct or "")[:10]
    items = []
    for g in (output.get("nfl_analysis") or {}).get("games") or []:
        for s in g.get("signals") or []:
            if s.get("statut") == "a_miser" and s.get("my_odds"):
                items.append((s, "stake_units", s["prob"] / 100.0, s["my_odds"], night(g.get("commence", ""))))
    ct_by_game = {f"{sg['game']['away_team']} @ {sg['game']['home_team']}": sg["game"].get("commence_time", "")
                  for sg in output.get("signals") or [] if sg.get("game")}
    for b in output.get("value_bets") or []:
        if b.get("b365_odds"):
            items.append((b, "kelly_fraction", (b.get("our_prob") or 0) / 100.0, b["b365_odds"],
                          night(ct_by_game.get(b.get("game", ""), "") or "")))
    bets = [{"p_final": p, "odds": o, "date": d} for _, _, p, o, d in items]
    apply_night(bets)
    for (obj, key, *_), b in zip(items, bets):
        obj[key] = b["stake_pct"]
        obj["stake_night_factor"] = b["night_factor"]
        obj["floor_odds"] = floor_odds(b["p_final"])
    return len(items)
