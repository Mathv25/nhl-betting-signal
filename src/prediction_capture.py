"""
Ecrit dans data/predictions.csv toutes les predictions d'un run du signal,
misees ou non (les courbes K sont ecrites a part par mlb_props_analyzer, au
moment ou le partant est confirme).

  MLB moneyline / -1.5  : chaque issue modelisee, retenue (🟢🟡🔥💎) ou non (🔴)
  LNH                   : lignes du modele (ML, -1.5/+1.5, totaux 5.5/6.5)
  NFL                   : chaque prix de reference, seulement quand le releve
                          est frais (pas l'etat relu d'une fenetre precedente)
  Props K selectionnees : le barreau recommande est marque selectionne=1

Seules les predictions AVANT le debut du match sont ecrites: un match en
cours a des cotes en direct, pas des cotes d'avant-match (vu le 23 septembre:
Tigers ML a 10.0 en plein match).
"""
from __future__ import annotations

from datetime import datetime, timezone

import predictions_log as PL

try:
    import pytz
    _ET = pytz.timezone("America/Toronto")
except Exception:          # pragma: no cover
    _ET = None


def _dt(ct: str):
    try:
        return datetime.fromisoformat((ct or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _day(ct: str, fallback: str) -> str:
    d = _dt(ct)
    if d is None or _ET is None:
        return fallback
    return d.astimezone(_ET).strftime("%Y-%m-%d")


def _future(ct: str, now: datetime) -> bool:
    d = _dt(ct)
    return d is not None and d > now


def _row(day, sport, marche, selection, prob, ct, match, event_id, **kw) -> dict:
    r = {
        "id": PL.make_id(day, sport, marche, selection),
        "date": day, "sport": sport, "marche": marche, "selection": selection,
        "prob_modele": round(prob, 4),
        "cote_juste": round(1.0 / prob, 3) if prob > 0 else "",
        "commence_time": ct, "match": match, "event_id": event_id,
        "mise_u": 0,
    }
    r.update(kw)
    return r


def mlb_ml_rows(mlb_ml_analysis: list, today: str, now: datetime) -> list:
    rows = []
    for g in mlb_ml_analysis or []:
        ct = g.get("commence", "")
        if not _future(ct, now):
            continue
        day = _day(ct, today)
        match = f"{g.get('away_team', '')} @ {g.get('home_team', '')}"
        pm = g.get("prob_marche") or {}
        for b in g.get("bets", []):
            team = b.get("equipe", "")
            if b.get("marche") == "moneyline":
                marche, sel = "mlb_ml", f"{team} ML"
                side = "home_ml" if team == g.get("home_team") else "away_ml"
                p_mkt = pm.get(side)
            else:
                marche, sel = "mlb_rl", f"{team} -1.5"
                p_mkt = (b.get("prob_marche") or 0) / 100.0 or None
            p = (b.get("probabilite") or 0) / 100.0          # p_final (melange)
            p_mod = (b.get("prob_modele") or 0) / 100.0      # modele seul
            if p <= 0 or p_mod <= 0:
                continue
            rows.append(_row(
                day, "mlb", marche, sel, p_mod, ct, match, g.get("event_id", ""),
                prob_finale=round(p, 4), cote_juste=round(1.0 / p, 3),
                prob_marche_novig=round(p_mkt, 4) if p_mkt else "",
                cote_reference=b.get("cote") or "",
                selectionne=0 if b.get("tier") == "🔴" else 1,
                statut="a_saisir",
                source=f"{b.get('tier', '')} {b.get('label', '')}".strip(),
            ))
    return rows


def nhl_rows(signals: list, today: str, now: datetime) -> list:
    rows = []
    for sg in signals or []:
        g = sg.get("game") or {}
        ct = g.get("commence_time", "")
        if not _future(ct, now):
            continue
        day = _day(ct, today)
        match = f"{g.get('away_team', '')} @ {g.get('home_team', '')}"
        for ln in g.get("model_lines") or []:
            rows.append(_row(
                day, "nhl", ln["marche"], ln["selection"], ln.get("prob_modele", ln["prob"]),
                ct, match, g.get("id", ""), statut="a_saisir",
                prob_finale=ln["prob"], cote_juste=ln.get("fair_odds", ""),
                prob_marche_novig=ln.get("prob_marche") or "",
                source=ln.get("blend_source", "lignes du modele"),
            ))
    return rows


def nfl_rows(nfl_state: dict, today: str, now: datetime) -> list:
    st = nfl_state or {}
    if st.get("stale"):
        return []
    rows = []
    for g in st.get("games") or []:
        ct = g.get("commence", "")
        if not _future(ct, now):
            continue
        day = _day(ct, today)
        match = f"{g.get('away_team', '')} @ {g.get('home_team', '')}"
        for label, px in (g.get("prices") or {}).items():
            p = (px.get("prob") or 0) / 100.0
            if p <= 0:
                continue
            # Pas de modele maison en NFL: la prediction EST la reference.
            rows.append(_row(
                day, "nfl", px.get("market", ""), label, p, ct, match, g.get("event_id", ""),
                prob_marche_novig=round(p, 4), prob_finale=round(p, 4),
                statut=px.get("statut", "a_saisir"),
                source=px.get("source", ""),
            ))
    return rows


def k_selected_rows(mlb_analysis: list, today: str, now: datetime) -> list:
    """Marque le barreau recommande de chaque carte K (selectionne=1)."""
    rows = []
    for g in mlb_analysis or []:
        ct = g.get("commence_time", "")
        if not _future(ct, now):
            continue
        day = _day(ct, today)
        for b in g.get("bets", []):
            if b.get("player_type") != "pitcher" or b.get("line") is None:
                continue
            k = int(float(b["line"])) + 1
            sel = f"{b['player']} Over {k - 0.5} K"
            rows.append({"id": PL.make_id(day, "mlb", "props_k", sel), "date": day,
                         "sport": "mlb", "marche": "props_k", "selection": sel,
                         "joueur": b["player"], "k": k, "ligne": k - 0.5,
                         "prob_modele": round((b.get("our_prob") or 0) / 100.0, 4),
                         "commence_time": ct, "selectionne": 1,
                         "statut": b.get("statut", "informatif"),
                         "cote_reference": b.get("est_odds") or "",
                         "book_reference": b.get("dk_book") or ""})
    return rows


def log_all(output: dict, now: datetime = None) -> dict:
    now = now or datetime.now(timezone.utc)
    today = output.get("date", "")
    rows = (mlb_ml_rows(output.get("mlb_ml_analysis"), today, now)
            + nhl_rows(output.get("signals"), today, now)
            + nfl_rows(output.get("nfl_analysis"), today, now)
            + k_selected_rows(output.get("mlb_analysis"), today, now))
    if not rows:
        return {"added": 0, "updated": 0, "frozen": 0}
    return PL.upsert(rows, now=now)
