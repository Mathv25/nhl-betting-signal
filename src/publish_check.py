"""
Validation AVANT publication (2026-10-06).

Le 2026-10-06, la page a affiche toute la journee les SOG de la veille sous la
date du jour, sans un mot. Regle depuis: chaque section du signal est
comparee aux calendriers officiels du jour (API LNH, API MLB) avant d'etre
publiee.

  - une donnee d'un AUTRE jour est retiree (jamais affichee comme actuelle);
  - un match du jour pas encore commence et absent d'une section = erreur;
  - une section vide alors que le calendrier a des matchs = erreur.

Le resultat va dans signal.json["validation"]; la page l'affiche en haut
(vert = tout est la, rouge = la liste exacte de ce qui manque). En CI,
`python publish_check.py --check` sort en 1 s'il reste une erreur: le
workflow relance alors la generation une fois avant de publier.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import pytz
import requests

TZ = pytz.timezone("America/Toronto")
_HERE = os.path.dirname(os.path.abspath(__file__))
SIGNAL = os.path.join(_HERE, "..", "docs", "signal.json")


def _dt(s: str):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _day_et(s: str) -> str:
    d = _dt(s)
    return d.astimezone(TZ).strftime("%Y-%m-%d") if d else ""


# ── Calendriers officiels ──────────────────────────────────────────────────

def nhl_schedule(day: str) -> list | None:
    """[{away, home (abbrev), start, upcoming}] du jour ET, None si l'API ne repond pas."""
    try:
        d = requests.get(f"https://api-web.nhle.com/v1/schedule/{day}", timeout=15).json()
    except Exception:
        return None
    out = []
    for w in d.get("gameWeek") or []:
        for g in w.get("games") or []:
            if g.get("gameType") not in (2, 3) or _day_et(g.get("startTimeUTC")) != day:
                continue
            out.append({"away": g["awayTeam"]["abbrev"], "home": g["homeTeam"]["abbrev"],
                        "start": g.get("startTimeUTC", ""),
                        "upcoming": g.get("gameState") in ("FUT", "PRE")})
    return out


def mlb_schedule(day: str) -> list | None:
    try:
        d = requests.get("https://statsapi.mlb.com/api/v1/schedule",
                         params={"sportId": 1, "date": day}, timeout=15).json()
    except Exception:
        return None
    out = []
    for de in d.get("dates") or []:
        for g in de.get("games") or []:
            t = g.get("teams") or {}
            out.append({"away": t.get("away", {}).get("team", {}).get("name", ""),
                        "home": t.get("home", {}).get("team", {}).get("name", ""),
                        "start": g.get("gameDate", ""),
                        "upcoming": g.get("status", {}).get("abstractGameState") == "Preview"})
    return out


def _abbr(name: str) -> str:
    try:
        from edge_calculator import TEAM_ABBR
        return TEAM_ABBR.get(name, name)
    except Exception:
        return name


# ── Validation ─────────────────────────────────────────────────────────────

def _section(name: str) -> dict:
    return {"nom": name, "erreurs": [], "avertissements": [], "detail": ""}


FETCH = object()     # calendrier a lire sur l'API (defaut); None = injoignable


def validate(output: dict, now: datetime = None, nhl=FETCH, mlb=FETCH) -> dict:
    """
    Valide et NETTOIE `output` en place (retire les donnees d'un autre jour).
    nhl / mlb: calendriers injectables pour les tests (None = API injoignable).
    """
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(TZ).strftime("%Y-%m-%d")
    nhl = nhl_schedule(today) if nhl is FETCH else nhl
    mlb = mlb_schedule(today) if mlb is FETCH else mlb
    secs = []

    g = _section("Signal")
    if output.get("date") != today:
        g["erreurs"].append(f"signal date du {output.get('date')} au lieu du {today}")
    secs.append(g)

    # ── LNH: lignes du modele ───────────────────────────────────────────────
    s = _section("LNH")
    if nhl is None:
        s["avertissements"].append("calendrier LNH injoignable — non verifie")
    else:
        sigs = output.get("signals") or []
        kept = [x for x in sigs if _day_et((x.get("game") or {}).get("commence_time")) == today]
        if len(kept) < len(sigs):
            s["erreurs"].append(f"{len(sigs) - len(kept)} match(s) d'un autre jour retire(s)")
            output["signals"] = kept
        have = {(_abbr(x["game"].get("away_team")), _abbr(x["game"].get("home_team"))) for x in kept}
        manque = [f"{m['away']} @ {m['home']}" for m in nhl
                  if m["upcoming"] and (m["away"], m["home"]) not in have]
        if manque:
            s["erreurs"].append("manquant(s): " + ", ".join(manque))
        s["detail"] = f"{len(kept)}/{len(nhl)} matchs"
    secs.append(s)

    # ── SOG ─────────────────────────────────────────────────────────────────
    s = _section("SOG")
    sog = output.get("nhl_sog") or {}
    if nhl is None:
        s["avertissements"].append("calendrier LNH injoignable — non verifie")
    elif nhl:
        if sog.get("date") != today:
            s["erreurs"].append(f"donnees du {sog.get('date')} — retirees")
            sog["joueurs"] = []
        pairs = {f"{m['away']} @ {m['home']}" for m in nhl}
        js = sog.get("joueurs") or []
        kept = [j for j in js if j.get("match") in pairs and _day_et(j.get("commence")) == today]
        if len(kept) < len(js):
            s["erreurs"].append(f"{len(js) - len(kept)} joueur(s) d'un autre match/jour retire(s)")
            sog["joueurs"] = kept
        couverts = {j.get("match") for j in kept}
        sans = [f"{m['away']} @ {m['home']}" for m in nhl
                if m["upcoming"] and f"{m['away']} @ {m['home']}" not in couverts]
        if not kept and any(m["upcoming"] for m in nhl):
            s["erreurs"].append("aucun joueur alors que des matchs sont a venir")
        elif sans:
            s["avertissements"].append("aucun joueur a gros volume: " + ", ".join(sans))
        s["detail"] = f"{len(couverts)}/{len(nhl)} matchs, {len(kept)} joueurs"
        output["nhl_sog"] = sog
    secs.append(s)

    # ── MLB: moneyline / -1.5 et cartes K ──────────────────────────────────
    s = _section("MLB")
    if mlb is None:
        s["avertissements"].append("calendrier MLB injoignable — non verifie")
    elif mlb:
        for key, ck in (("mlb_ml_analysis", "commence"), ("mlb_analysis", "commence_time")):
            rows = output.get(key) or []
            kept = [r for r in rows if _day_et(r.get(ck) or r.get("commence") or r.get("commence_time")) == today]
            if len(kept) < len(rows):
                s["erreurs"].append(f"{key}: {len(rows) - len(kept)} match(s) d'un autre jour retire(s)")
                output[key] = kept
        have = {(r.get("away_team"), r.get("home_team")) for r in output.get("mlb_ml_analysis") or []}
        manque = [f"{m['away']} @ {m['home']}" for m in mlb
                  if m["upcoming"] and (m["away"], m["home"]) not in have]
        if manque:
            s["erreurs"].append("ML/-1.5 manquant(s): " + ", ".join(manque))
        n_k = sum(len(r.get("bets") or []) for r in output.get("mlb_analysis") or [])
        s["detail"] = f"{len(have)}/{len(mlb)} matchs ML, {n_k} carte(s) K"
    secs.append(s)

    n_err = sum(len(x["erreurs"]) for x in secs)
    return {"ok": n_err == 0, "verifie_a": now.isoformat(), "jour": today, "sections": secs}


def main() -> int:
    """
    --check: relit signal.json (deja valide par signal.py) et sort en 1 s'il
    reste une erreur — le workflow relance alors la generation une fois.
    Sans option: valide et reecrit signal.json (usage manuel).
    """
    with open(SIGNAL, encoding="utf-8") as f:
        out = json.load(f)
    if "--check" in sys.argv:
        v = out.get("validation") or {"ok": False, "sections": []}
    else:
        v = validate(out)
        out["validation"] = v
        with open(SIGNAL, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    for sec in v.get("sections") or []:
        etat = "OK " if not sec["erreurs"] else "ERR"
        print(f"  [{etat}] {sec['nom']}: {sec['detail']} {'; '.join(sec['erreurs'] + sec['avertissements'])}")
    print("Validation:", "tout est la" if v.get("ok") else "ERREURS")
    return 0 if v.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
