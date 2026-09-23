"""
Import unique de docs/results.json dans data/predictions.csv (2026-09-23).

Ces lignes sont etiquetees version_modele = "historique-results.json" et
restent a part dans l'onglet Performance, parce que:
  - ce sont des paris SELECTIONNES (biais de selection);
  - `our_prob` melange trois versions du modele K (brute, Platt du 6 aout,
    Platt du 19 aout): aucune `prob_brute`, donc aucune n'entre dans la
    calibration par barreau de k_calibration.py;
  - la « cote » etait celle d'un autre book que bet365, ou la cote FIXE 1.909
    supposee du 8 juin au 7 juillet — celle-ci est ignoree.
Les paris encore en attente ('?') ne sont pas importes.

    cd src && python3 import_results.py
"""
from __future__ import annotations

import json
import math
import os

import predictions_log as PL
from performance import HIST

_HERE = os.path.dirname(os.path.abspath(__file__))
PLACEHOLDER = 1.909


def convert(b: dict) -> dict | None:
    res = b.get("result")
    if res not in ("W", "L", "VOID", "P"):
        return None
    sport = b.get("sport", "")
    mt = b.get("market_type", "")
    name = b.get("name") or b.get("team") or ""
    if mt == "strikeouts":
        k = int(math.floor(float(b.get("line") or 0))) + 1
        marche, sel, extra = "props_k", f"{name} Over {k - 0.5} K", {"joueur": name, "k": k, "ligne": k - 0.5}
    elif mt == "moneyline":
        marche = f"{sport}_ml"
        sel = f"{b.get('team') or name} ML" if sport == "mlb" else b.get("bet", "")
        extra = {}
    elif mt in ("run_line_-1.5",):
        marche, sel, extra = "mlb_rl", f"{b.get('team') or name} -1.5", {}
    elif mt == "puck line":
        marche, sel, extra = "nhl_puck", b.get("bet", ""), {}
    elif mt == "total buts":
        marche, sel, extra = "nhl_total", b.get("bet", ""), {}
    else:
        marche, sel, extra = f"{sport}_{mt or 'autre'}", b.get("bet", ""), {}
    odds = float(b.get("b365_odds") or 0)
    ref = odds if odds > 1 and abs(odds - PLACEHOLDER) > 1e-6 else None
    row = {
        "id": PL.make_id(b.get("date", ""), sport, marche, sel) + "|hist",
        "timestamp": b.get("date", ""), "date": b.get("date", ""), "sport": sport,
        "marche": marche, "selection": sel, "match": b.get("game", ""),
        "prob_modele": round(float(b.get("our_prob") or 0) / 100.0, 4),
        "resultat": res, "mise_u": 0, "selectionne": 1,
        "cote_reference": ref or "",
        "version_modele": HIST, "source": "import results.json",
        **extra,
    }
    cn = b.get("closing_novig")
    if cn:
        p = float(cn) / 100.0
        if p > 0:
            row["fermeture_novig"] = round(p, 4)
            row["cote_fermeture"] = round(1.0 / p, 3)
            if ref:
                row["clv_reference"] = round(ref * p - 1.0, 4)
    return row


def main():
    with open(os.path.join(_HERE, "..", "docs", "results.json"), encoding="utf-8") as f:
        bets = json.load(f).get("bets", [])
    rows = PL.load()
    known = {r.get("id") for r in rows}
    new = [r for r in (convert(b) for b in bets) if r and r["id"] not in known]
    PL.save(rows + new)
    print(f"{len(new)} ligne(s) historique(s) importee(s) ({len(bets)} dans results.json)")


if __name__ == "__main__":
    main()
