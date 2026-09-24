"""
Journal unique des predictions — data/predictions.csv.

Une ligne par prediction, misee ou non. C'est la base de la calibration par
barreau des props K (k_calibration.py), du CLV (close_and_settle.py) et de
l'onglet Performance (docs/performance.json).

Pourquoi un CSV et pas docs/results.json:
  - results.json ne garde que ce que le modele a SELECTIONNE (une ligne par
    lanceur, choisie parce qu'elle semblait +EV). Calibrer la-dessus mesure le
    modele la ou il croyait avoir raison: biais de selection. Ici on journalise
    aussi les barreaux non mises.
  - Le CSV vit hors de docs/: il n'est pas servi par Pages. L'onglet
    Performance lit docs/performance.json, calcule a partir du CSV.

Conventions:
  - probabilites en fraction [0, 1] (pas en %), cotes decimales;
  - `id` = date|sport|marche|selection: une prediction mise a jour par un
    refresh plus tardif garde le meme id (derniere valeur AVANT le match);
  - apres le debut du match, ou une fois `resultat` rempli, la ligne ne bouge
    plus que par close_and_settle.py (fermeture, resultat, CLV).
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))

COLUMNS = [
    # Demandees explicitement
    "timestamp", "sport", "marche", "selection",
    "prob_modele", "prob_marche_novig", "cote_prise", "book", "edge", "mise_u",
    "cote_fermeture", "resultat", "version_modele",
    # Necessaires pour relier, fermer et calibrer
    "id", "date", "event_id", "match", "commence_time", "joueur", "ligne", "k",
    "prob_brute", "prob_calibree", "statut", "cote_juste",
    "fermeture_novig", "clv", "source",
    # Prix vu a la prediction chez un AUTRE book que bet365 (reference, pas
    # jouable), si la prediction a ete retenue par le modele, et le CLV de ce
    # prix de reference (« CLV papier »), distinct du CLV reel sur cote_prise.
    "cote_reference", "book_reference", "selectionne", "clv_reference",
]

# Champs que la prediction suivante (meme id, avant le match) a le droit de
# reecrire. Le reste appartient a close_and_settle.py ou a l'utilisateur.
PREDICTION_FIELDS = {
    "timestamp", "prob_modele", "prob_marche_novig", "edge", "prob_brute",
    "prob_calibree", "statut", "cote_juste", "version_modele", "ligne",
    "commence_time", "event_id", "match", "source",
    "cote_reference", "book_reference", "selectionne",
}


def path() -> str:
    return os.environ.get("PREDICTIONS_PATH") or os.path.join(_HERE, "..", "data", "predictions.csv")


def current_version() -> str:
    import model_version
    return model_version.MODEL_VERSION


def make_id(date: str, sport: str, marche: str, selection: str) -> str:
    return f"{date}|{sport}|{marche}|{selection}"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load(p: str = None) -> list:
    p = p or path()
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]


def save(rows: list, p: str = None) -> None:
    p = p or path()
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: _fmt(r.get(c, "")) for c in COLUMNS})
    os.replace(tmp, p)


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    return v


def _started(row: dict, now: datetime) -> bool:
    ct = row.get("commence_time") or ""
    if not ct:
        return False
    try:
        return datetime.fromisoformat(ct.replace("Z", "+00:00")) <= now
    except ValueError:
        return False


def upsert(new_rows: list, p: str = None, now: datetime = None) -> dict:
    """
    Ajoute ou met a jour des predictions. Retourne {"added", "updated", "frozen"}.

    Une ligne existante est gelee (non reecrite) si son match a commence ou si
    son resultat est connu: la prediction qui compte est la derniere AVANT le
    debut, et un refresh en cours de match ne doit pas l'ecraser.
    """
    now = now or datetime.now(timezone.utc)
    rows = load(p)
    index = {r.get("id"): i for i, r in enumerate(rows)}
    stats = {"added": 0, "updated": 0, "frozen": 0}
    for nr in new_rows:
        nr = dict(nr)
        nr.setdefault("timestamp", now_iso())
        # Chaque prediction porte la version du modele qui l'a produite.
        nr["version_modele"] = current_version()
        rid = nr.get("id") or make_id(nr.get("date", ""), nr.get("sport", ""),
                                      nr.get("marche", ""), nr.get("selection", ""))
        nr["id"] = rid
        if rid in index:
            old = rows[index[rid]]
            if old.get("resultat") or _started(old, now):
                stats["frozen"] += 1
                continue
            for k in PREDICTION_FIELDS:
                if k in nr:
                    old[k] = nr[k]
            stats["updated"] += 1
        else:
            index[rid] = len(rows)
            rows.append(nr)
            stats["added"] += 1
    save(rows, p)
    return stats


# Colonnes dont chaque ecrivain est proprietaire. La fusion ne recopie que
# celles-la: un run du signal ne peut pas effacer une cote saisie, et une
# saisie ne peut pas effacer une fermeture.
OWNED = {
    "prediction": PREDICTION_FIELDS,
    "settle": {"cote_fermeture", "fermeture_novig", "clv", "clv_reference", "resultat"},
}


def merge_file(ours_path: str, base_path: str, owner: str = "prediction") -> dict:
    """
    Fusionne ligne par ligne `ours_path` (le CSV que ce run a produit) dans
    `base_path` (la derniere version de main). Pour une ligne connue, seules
    les colonnes de `owner` sont recopiees — et pour « prediction », seulement
    si la ligne de base n'est pas gelee. Une ligne inconnue est ajoutee telle
    quelle. Retourne {"added", "updated"}.
    """
    base = load(base_path)
    index = {r.get("id"): r for r in base}
    fields = OWNED[owner]
    now = datetime.now(timezone.utc)
    st = {"added": 0, "updated": 0}
    for r in load(ours_path):
        b = index.get(r.get("id"))
        if b is None:
            base.append(r)
            index[r.get("id")] = r
            st["added"] += 1
            continue
        if owner == "prediction" and (b.get("resultat") or _started(b, now)):
            continue
        changed = False
        for f in fields:
            if f in r and r[f] != b.get(f):
                b[f] = r[f]
                changed = True
        st["updated"] += changed
    save(base, base_path)
    return st


def to_float(v, default=None):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    # python3 predictions_log.py merge <ours.csv> <base.csv> [prediction|settle]
    import sys
    if len(sys.argv) >= 4 and sys.argv[1] == "merge":
        owner = sys.argv[4] if len(sys.argv) > 4 else "prediction"
        if not os.path.exists(sys.argv[2]):
            print("rien a fusionner")
            sys.exit(0)
        print(merge_file(sys.argv[2], sys.argv[3], owner))
    else:
        print(__doc__)
