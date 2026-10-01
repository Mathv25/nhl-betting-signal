"""
Verdict par match LNH: une equipe/un marche (ou « passer »), la cote bet365 a
exiger et les raisons, pour que le tableau de 80 lignes ne soit pas a trier a
la main.

Regles:
  - seules les lignes avec un prix de marche (Pinnacle Shin / mediane) sont
    candidates: un modele seul n'est pas assez fiable pour etre joue;
  - chaque drapeau de credibilite divise par deux le poids restant du modele
    sur p_final (gardien sans donnees, debut de saison, ecart enorme);
  - cote a exiger = (1 + MANUAL_EDGE_PCT) / p_verdict, au moins le plancher de
    la ligne (1.70 en moneyline);
  - match « en attente » (gardien non confirme): meme calcul, marque
    provisoire, jamais « a regarder »;
  - prix bet365 attendu = juste marche / (1 + B365_OVERROUND): si l'attendu
    atteint la cote a exiger -> « a regarder », sinon « passer ».
"""
from __future__ import annotations

from datetime import date, datetime

B365_OVERROUND = 0.045        # marge bet365 typique LNH (ML / puck line)
MANUAL_EDGE = 0.03            # +3% d'esperance, comme model_lines
BIG_GAP = 0.10                # ecart modele-marche au-dela duquel on doute du modele
EARLY_SEASON_END = (11, 15)   # avant le 15 nov.: forces d'equipe = saison passee

MARCHE_TXT = {"nhl_ml": "ML", "nhl_puck": "puck line", "nhl_total": "total"}


def _no_data(detail: str) -> bool:
    d = (detail or "").lower()
    return "(0 tirs)" in d or "aucune stat" in d or "inconnu" in d


def _early_season(today: date) -> bool:
    return today.month == 10 or (today.month == 11 and today.day < EARLY_SEASON_END[1])


def _short(team: str) -> str:
    return team.split()[-1] if team else team


def verdict(game: dict, today: date = None) -> dict:
    """Verdict du match; provisoire tant qu'un gardien n'est pas confirme."""
    v = _verdict(game, today)
    if game.get("statut") == "en_attente":
        goalies = game.get("goalies") or {}
        manque = [(goalies.get(s) or {}).get("name") or "?" for s in ("away", "home")
                  if not (goalies.get(s) or {}).get("confirmed")]
        v["titre"] = ("Provisoire (gardien non confirmé: " + ", ".join(manque) + ") — "
                      + v["titre"])
        v["decision"] = "attente"
    return v


def _verdict(game: dict, today: date = None) -> dict:
    today = today or datetime.now().date()
    goalies = game.get("goalies") or {}
    lines = game.get("model_lines") or []

    flags = []
    for side in ("away", "home"):
        gl = goalies.get(side) or {}
        if _no_data(gl.get("detail", "")):
            flags.append(f"Gardien {gl.get('name') or '?'}: aucune donnée récente — "
                         f"le modèle le traite comme un gardien moyen")
    if _early_season(today):
        flags.append("Début de saison: forces d'équipe de l'an passé (au backtest, moins "
                     "bonnes qu'un simple taux domicile) — poids du modèle réduit")

    gl_txt = []
    for side in ("away", "home"):
        gl = goalies.get(side) or {}
        gl_txt.append(f"{gl.get('name') or '?'} ({gl.get('detail') or 'aucune stat'})")

    best = None
    for ln in lines:
        p_mkt = ln.get("prob_marche")
        p, p_mod = ln.get("prob"), ln.get("prob_modele")
        if not p_mkt or not p or p_mod is None:
            continue
        gap = p_mod - p_mkt
        n_flags = len(flags) + (1 if abs(gap) > BIG_GAP else 0)
        p_v = p_mkt + (p - p_mkt) * (0.5 ** n_flags)
        floor = ln.get("min_odds", 0) if ln.get("marche") == "nhl_ml" else 0
        exiger = round(max((1 + MANUAL_EDGE) / p_v, min(floor, 1.70)), 2)
        attendu = round(1.0 / (p_mkt * (1 + B365_OVERROUND)), 2)
        ev = p_v * attendu - 1
        cand = {"ln": ln, "gap": gap, "p_v": p_v, "exiger": exiger,
                "attendu": attendu, "ev": ev, "big": abs(gap) > BIG_GAP}
        if best is None or ev > best["ev"]:
            best = cand

    if best is None:
        return {"decision": "passer", "titre": "Passer — pas de prix de marché pour comparer",
                "raisons": ["Gardiens: " + " · ".join(gl_txt)] + flags}

    ln = best["ln"]
    sel = ln["selection"]
    mk = MARCHE_TXT.get(ln["marche"], ln["marche"])
    raisons = [f"{sel} ({mk}): modèle {ln['prob_modele'] * 100:.0f} % vs marché "
               f"{ln['prob_marche'] * 100:.0f} % (écart {best['gap'] * 100:+.0f} pts) → "
               f"retenu {best['p_v'] * 100:.1f} %"]
    if best["big"]:
        raisons.append(f"Écart de {abs(best['gap']) * 100:.0f} pts: le marché a probablement "
                       f"une info que le modèle n'a pas — poids du modèle réduit")
    raisons += flags
    raisons.append("Gardiens: " + " · ".join(gl_txt))

    if best["attendu"] >= best["exiger"]:
        titre = (f"À regarder: {sel} — exiger ≥ {best['exiger']:.2f} chez bet365 "
                 f"(prix normal ≈ {best['attendu']:.2f})")
        decision = "regarder"
    else:
        titre = (f"Passer, sauf si bet365 offre ≥ {best['exiger']:.2f} sur {sel} "
                 f"(prix normal ≈ {best['attendu']:.2f})")
        decision = "passer"
    return {"decision": decision, "titre": titre, "selection": sel, "marche": ln["marche"],
            "exiger": best["exiger"], "attendu": best["attendu"],
            "prob": round(best["p_v"], 4), "raisons": raisons}
