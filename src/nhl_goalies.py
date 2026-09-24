"""
Gardien partant LNH: qualite (GSAx/60) et statut de confirmation.

Qualite — MoneyPuck (seasonSummary goalies.csv, situation "all"):
    GSAx = xGoals - goals, sur la saison precedente + la saison en cours
    (additionnees, donc ponderees par le temps de glace), puis
    nhl_dixon_coles.goalie_multiplier (retreci vers 0 pour un petit echantillon).
Repli si MoneyPuck est injoignable — % d'arrets ajuste (API stats LNH):
    sv_adj = (arrets + K x sv_ligue) / (tirs + K),  mult = (1 - sv_adj) / (1 - sv_ligue)

Statut — Daily Faceoff (champ *NewsStrengthName): « Confirmed » seulement.
« Likely », « Unconfirmed » ou absent = non confirme -> le match reste « en
attente » et ne produit aucun signal (edge_calculator).
"""
from __future__ import annotations

import csv
import io
import unicodedata
from datetime import date

import requests

import nhl_dixon_coles as DC

MONEYPUCK = "https://moneypuck.com/moneypuck/playerData/seasonSummary/{y}/regular/goalies.csv"
NHL_STATS = "https://api.nhle.com/stats/rest/en/goalie/summary"
SV_SHRINK_SHOTS = 1000.0

_mp_cache: dict = {}
_sv_cache: dict = {}


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace(".", " ").replace("-", " ").split())


def _season_start_years(today: date = None) -> list:
    """MoneyPuck indexe une saison par son annee de debut (2025 = 2025-26)."""
    today = today or date.today()
    cur = today.year if today.month >= 9 else today.year - 1
    return [cur - 1, cur]


def _moneypuck(year: int) -> dict:
    if year in _mp_cache:
        return _mp_cache[year]
    out = {}
    try:
        r = requests.get(MONEYPUCK.format(y=year), timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            for row in csv.DictReader(io.StringIO(r.text)):
                if row.get("situation") != "all":
                    continue
                out[_norm(row.get("name", ""))] = {
                    "xg": float(row.get("xGoals") or 0), "g": float(row.get("goals") or 0),
                    "ice": float(row.get("icetime") or 0), "games": int(float(row.get("games_played") or 0)),
                }
    except Exception:
        out = {}
    _mp_cache[year] = out
    return out


def gsax(name: str, today: date = None):
    """(GSAx, temps de glace en s, source) sur saison precedente + en cours, ou None."""
    key = _norm(name)
    xg = g = ice = 0.0
    found = []
    for y in _season_start_years(today):
        row = _moneypuck(y).get(key)
        if row:
            xg, g, ice = xg + row["xg"], g + row["g"], ice + row["ice"]
            found.append(str(y))
    if not found:
        return None
    return xg - g, ice, "MoneyPuck " + "+".join(found)


def _sv_summary(season_id: str) -> dict:
    if season_id in _sv_cache:
        return _sv_cache[season_id]
    out = {}
    try:
        r = requests.get(NHL_STATS, timeout=15, params={
            "limit": -1, "cayenneExp": f"seasonId={season_id} and gameTypeId=2"})
        if r.status_code == 200:
            for row in r.json().get("data", []):
                out[_norm(row.get("goalieFullName", ""))] = {
                    "saves": float(row.get("saves") or 0),
                    "shots": float(row.get("shotsAgainst") or 0)}
    except Exception:
        out = {}
    _sv_cache[season_id] = out
    return out


def sv_multiplier(name: str, today: date = None):
    """Repli: multiplicateur par % d'arrets retreci vers la ligue, ou None."""
    ys = _season_start_years(today)
    saves = shots = lg_saves = lg_shots = 0.0
    for y in ys:
        tab = _sv_summary(f"{y}{y + 1}")
        lg_saves += sum(v["saves"] for v in tab.values())
        lg_shots += sum(v["shots"] for v in tab.values())
        row = tab.get(_norm(name))
        if row:
            saves, shots = saves + row["saves"], shots + row["shots"]
    if lg_shots <= 0:
        return None
    lg = lg_saves / lg_shots
    sv_adj = (saves + SV_SHRINK_SHOTS * lg) / (shots + SV_SHRINK_SHOTS)
    return round(min(max((1 - sv_adj) / (1 - lg), 0.80), 1.20), 4), f"% arrets ajuste ({int(shots)} tirs)"


def multiplier(name: str, today: date = None) -> tuple:
    """(multiplicateur du lambda adverse, detail). 1.0 si gardien inconnu."""
    if not name:
        return 1.0, "gardien inconnu"
    got = gsax(name, today)
    if got:
        gx, ice, src = got
        m = DC.goalie_multiplier(gx, ice)
        return m, f"{src}: GSAx {gx:+.1f} en {ice / 3600:.0f} h"
    sv = sv_multiplier(name, today)
    if sv:
        return sv
    return 1.0, "aucune stat"


def is_confirmed(status: str) -> bool:
    s = (status or "").strip().lower()
    return "confirm" in s and "unconfirm" not in s and "not confirm" not in s
