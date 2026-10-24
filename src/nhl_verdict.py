"""
Verdict par match LNH: une ligne a verifier chez bet365, ou « passer ».

Depuis 2026-10-24 le poids du modele LNH est 0 (config BLEND_W): la
probabilite d'une ligne est celle de Pinnacle sans marge (Shin), la cote a
exiger chez bet365 est (1 + 3 %) / p. bet365 n'est pas dans le flux; on
regarde donc les books recreatifs (PROXY_BOOKS: DraftKings, FanDuel, William
Hill...), qui ont les memes marges et les memes retards:

  - un book recreatif paie >= la cote a exiger -> « a verifier »: bet365 est
    peut-etre decale lui aussi, la ligne vaut la peine d'etre regardee;
  - sinon -> « passer »: bet365 prend en general ~4 % de marge sous la cote
    juste, la cote a exiger n'a pratiquement aucune chance d'y etre.

Le modele Dixon-Coles reste affiche pour information seulement.
Match « en attente » (gardien non confirme): provisoire, jamais « a verifier ».
"""
from __future__ import annotations

from datetime import date

MARCHE_TXT = {"nhl_ml": "ML", "nhl_puck": "puck line", "nhl_total": "total"}


def verdict(game: dict, today: date = None) -> dict:
    """Verdict du match; provisoire tant qu'un gardien n'est pas confirme."""
    v = _verdict(game)
    if game.get("statut") == "en_attente":
        goalies = game.get("goalies") or {}
        manque = [(goalies.get(s) or {}).get("name") or "?" for s in ("away", "home")
                  if not (goalies.get(s) or {}).get("confirmed")]
        v["titre"] = ("Provisoire (gardien non confirmé: " + ", ".join(manque) + ") — "
                      + v["titre"])
        v["decision"] = "attente"
    return v


def _gardiens(game: dict) -> str:
    goalies = game.get("goalies") or {}
    return "Gardiens: " + " · ".join(
        f"{(goalies.get(s) or {}).get('name') or '?'} "
        f"({(goalies.get(s) or {}).get('detail') or 'aucune stat'})" for s in ("away", "home"))


def _verdict(game: dict) -> dict:
    lines = [ln for ln in game.get("model_lines") or [] if ln.get("prob_marche") and ln.get("prob")]
    if not lines:
        return {"decision": "passer", "titre": "Passer — pas de prix Pinnacle pour comparer",
                "raisons": [_gardiens(game)]}

    def ev(ln):
        return ln["prob"] * ln["proxy_odds"] - 1 if ln.get("proxy_odds") else -1.0

    best = max(lines, key=ev)
    sel, mk = best["selection"], MARCHE_TXT.get(best["marche"], best["marche"])
    raisons = []
    if best.get("proxy_odds"):
        raisons.append(f"{sel} ({mk}): Pinnacle juste {best['fair_odds']:.2f}, exiger "
                       f"{best['min_odds']:.2f} — meilleur book récréatif {best['proxy_odds']:.2f} "
                       f"({best.get('proxy_book', '')})")
    raisons.append(f"Modèle maison {best.get('prob_modele', 0) * 100:.0f} % vs Pinnacle "
                   f"{best['prob_marche'] * 100:.0f} % — information seulement (poids 0)")
    raisons.append(_gardiens(game))

    out = {"selection": sel, "marche": best["marche"], "exiger": best["min_odds"],
           "attendu": best.get("proxy_odds"), "prob": round(best["prob"], 4), "raisons": raisons}
    if best.get("a_verifier"):
        out.update(decision="regarder",
                   titre=(f"À vérifier: {sel} — exiger ≥ {best['min_odds']:.2f} chez bet365 "
                          f"({best.get('proxy_book', '')} paie {best['proxy_odds']:.2f})"))
    else:
        out.update(decision="passer",
                   titre="Passer — aucun book ne paie au-dessus de Pinnacle + 3 %")
    return out
