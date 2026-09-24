"""
Enregistre une cote saisie a la main (bouton « Enregistrer » du dashboard).

bet365 n'est pas dans The Odds API: la cote se lit chez bet365, se saisit sur
la page, et le bouton declenche le workflow record_prediction.yml, qui appelle
ce script avec la saisie en JSON dans la variable d'environnement PAYLOAD
(jamais interpolee dans le shell).

    PAYLOAD='{"sport":"mlb","marche":"props_k","selection":"X Over 5.5 K",
              "prob_modele":0.52,"cote_prise":2.05,"mise_u":1,...}' \
        python3 src/record_prediction.py

La ligne existante (meme id: date|sport|marche|selection) est completee;
sinon une ligne est creee. Le statut est recalcule ici, pas cru sur parole:
  - props K sur un barreau non calibre -> « informatif », quelle que soit la cote;
  - edge > SUSPECT_EDGE_PCT (8%)       -> « a_verifier »;
  - edge >= seuil du sport              -> « a_miser »;
  - sinon                               -> « sous_seuil ».
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import betting_config           # noqa: E402
import predictions_log as PL     # noqa: E402

# Seuil d'edge (esperance, %) par sport pour « a miser ».
THRESHOLDS = {"nfl": 3.0, "mlb": 3.0, "nhl": 15.0}


def _num(payload, key, lo=None, hi=None, required=False):
    v = PL.to_float(payload.get(key))
    if v is None:
        if required:
            raise ValueError(f"champ requis manquant: {key}")
        return None
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ValueError(f"{key} hors bornes: {v}")
    return v


def status_for(payload: dict, edge_pct: float) -> str:
    if payload.get("marche") == "props_k" and str(payload.get("calibre", "")).lower() not in ("1", "true"):
        return "informatif"
    if edge_pct > betting_config.suspect_edge_pct():
        return "a_verifier"
    if edge_pct >= THRESHOLDS.get(payload.get("sport", ""), 3.0):
        return "a_miser"
    return "sous_seuil"


def record(payload: dict, path: str = None) -> dict:
    for key in ("sport", "marche", "selection", "date"):
        if not str(payload.get(key, "")).strip():
            raise ValueError(f"champ requis manquant: {key}")
    # L'edge se calcule sur p_final (blend.py); p_modele seul en repli.
    prob = _num(payload, "prob_finale", 0.0, 1.0) or _num(payload, "prob_modele", 0.0, 1.0, required=True)
    odds = _num(payload, "cote_prise", 1.01, 1000.0, required=True)
    stake = _num(payload, "mise_u", 0.0, 100.0) or 0.0
    book = (payload.get("book") or betting_config.allowed_books()[0]).lower()
    if book not in betting_config.allowed_books():
        raise ValueError(f"book {book} hors ALLOWED_BOOKS {betting_config.allowed_books()}")

    edge = round((prob * odds - 1.0) * 100, 2)
    statut = status_for(payload, edge)
    rid = PL.make_id(payload["date"], payload["sport"], payload["marche"], payload["selection"])

    rows = PL.load(path)
    row = next((r for r in rows if r.get("id") == rid), None)
    if row is None:
        row = {"id": rid, "timestamp": PL.now_iso(), "source": "saisie manuelle",
               "version_modele": PL.current_version()}
        for k in ("date", "sport", "marche", "selection", "joueur", "ligne", "k",
                  "match", "commence_time", "event_id", "prob_brute", "prob_calibree",
                  "prob_marche_novig"):
            if payload.get(k) not in (None, ""):
                row[k] = payload[k]
        row["prob_modele"] = _num(payload, "prob_modele", 0.0, 1.0) or prob
        row["prob_finale"] = prob
        rows.append(row)
    elif row.get("resultat"):
        raise ValueError(f"prediction deja reglee ({row['resultat']}): {rid}")
    row.update({
        "cote_prise": odds, "book": book, "mise_u": stake, "edge": edge,
        "statut": statut, "cote_juste": round(1.0 / prob, 3) if prob > 0 else "",
    })
    PL.save(rows, path)
    return row


if __name__ == "__main__":
    try:
        payload = json.loads(os.environ.get("PAYLOAD") or (sys.argv[1] if len(sys.argv) > 1 else "{}"))
        row = record(payload)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"Refuse: {e}")
        sys.exit(1)
    print(f"Enregistre: {row['selection']} @ {row['cote_prise']} ({row['book']}) — "
          f"edge {row['edge']:+.1f}% → {row['statut']}, mise {row['mise_u']} u")
