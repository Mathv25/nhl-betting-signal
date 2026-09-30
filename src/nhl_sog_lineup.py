"""
Alignements LNH pour le module SOG — Daily Faceoff (trios, paires, vagues
d'avantage numerique) croise avec l'effectif de l'API LNH (identifiants).

Ce qu'on appelle « confirme » ici, et ses limites:
  - le joueur figure dans un trio (f1-f4) ou une paire (d1-d3) de la page
    line-combinations de Daily Faceoff, sans statut de blessure ni « decision
    de derniere minute »;
  - la page indique sa source (« Last Game », entrainement matinal, etc.) et
    son heure de mise a jour: on les affiche. Ce n'est PAS l'alignement
    officiel, publie par la ligue seulement autour de la mise au jeu.
bet365 annule un pari de tirs si le joueur ne joue pas: le risque d'un
alignement faux est un pari rembourse, pas un pari perdu.
"""
from __future__ import annotations

import json
import re
import unicodedata

import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
LINE_GROUPS = {"f1", "f2", "f3", "f4", "d1", "d2", "d3"}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", " ", s)
    return " ".join(s.split())


# L'API LNH abrege parfois la ville (« NY Islanders »): on force ces slugs.
SLUG_OVERRIDE = {"ny islanders islanders": "new-york-islanders", "ny islanders": "new-york-islanders",
                 "ny rangers rangers": "new-york-rangers", "ny rangers": "new-york-rangers"}


def slug(team_name: str) -> str:
    """'Montréal Canadiens' -> 'montreal-canadiens', 'St. Louis Blues' -> 'st-louis-blues'."""
    n = norm(team_name)
    return SLUG_OVERRIDE.get(n) or "-".join(n.split())


def dfo_lines(team_name: str, session=None) -> dict:
    """
    {"source", "updated", "players": {nom_norm: {name, line, pp, injury, gtd}}}
    ou {} si la page est illisible.
    """
    s = session or requests
    try:
        r = s.get(f"https://www.dailyfaceoff.com/teams/{slug(team_name)}/line-combinations",
                  headers=UA, timeout=20)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        comb = json.loads(m.group(1))["props"]["pageProps"]["combinations"]
    except Exception:
        return {}
    players: dict = {}
    for p in comb.get("players") or []:
        k = norm(p.get("name", ""))
        e = players.setdefault(k, {"name": p.get("name", ""), "line": None, "pp": None,
                                   "injury": None, "gtd": False})
        g = p.get("groupIdentifier")
        if g in LINE_GROUPS:
            e["line"] = g
        elif g in ("pp1", "pp2"):
            e["pp"] = g
        e["injury"] = e["injury"] or p.get("injuryStatus")
        e["gtd"] = e["gtd"] or bool(p.get("gameTimeDecision"))
    return {"source": comb.get("sourceName", ""), "updated": comb.get("updatedAt", ""),
            "players": players}


def status(entry: dict) -> str:
    """'confirme', 'incertain' (blessure / derniere minute) ou 'absent'."""
    if not entry or not entry.get("line"):
        return "absent"
    if entry.get("injury") or entry.get("gtd"):
        return "incertain"
    return "confirme"
