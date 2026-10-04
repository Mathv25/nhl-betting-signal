"""
Calibration OFFLINE des props NFL a ligne ajustee (verges de passe, de
reception, au sol). Donnees gratuites: nflverse, stats hebdo par joueur
(release GitHub publique), saison reguliere seulement.

    python3 src/nfl_calibration.py            # telecharge (cache), calibre, valide

Methode
  - Joueur-saison avec >= MIN_GAMES matchs pour le marche.
  - ratio = verges du match / mediane du joueur sur ses AUTRES matchs de la
    saison. La mediane « tous matchs » inclurait le match lui-meme et
    resserrerait artificiellement la distribution autour de 1.
  - Ratios regroupes par marche et par tranche de mediane; on garde
    N_QUANTILES quantiles fins (zeros compris).
  - Validation hors echantillon: calibre sur les 2 premieres saisons, teste
    sur la 3e. Pour des seuils 0.8x, 0.9x, 1.1x, 1.2x la mediane: P predite
    vs frequence observee, par tranche.
  - Validation croisee par saison (3 plis) pour decider quelles tranches sont
    « validees » (MAX_ERR_VALID); les autres restent informatives.
  - Le fichier de PRODUCTION est calibre sur les 3 saisons.

Sorties: docs/nfl_prop_calibration.json (production) et
docs/nfl_calibration_report.json (validation, affichee dans Performance).

Pour ajouter un marche (receptions, passes completees): une entree dans
MARKETS — colonne nflverse, positions, filtre de match et tranches.
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import sys
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_prop_model as M  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, "..")
CACHE = os.path.join(ROOT, ".cache", "nflverse")
URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{y}.csv"

SEASONS = [2023, 2024, 2025]
MIN_GAMES = 6
N_QUANTILES = 200          # 201 points: pas de 0.5 %
THRESHOLDS = [0.8, 0.9, 1.1, 1.2]
# Une tranche n'est « validee » (peut etre A MISER) que si, en validation
# croisee par saison (chaque saison testee a son tour, calibree sur les deux
# autres), l'erreur moyenne |observe - predit| aux seuils 0.9x et 1.1x — la
# zone ou tombent les ecarts de ligne reels — reste sous MAX_ERR_VALID.
# Sinon: « informatif ». Meme regle que les barreaux K (2026-09-23).
MAX_ERR_VALID = 0.03
ZONE_UTILE = (0.9, 1.1)

# col: colonne nflverse; pos: positions retenues; keep: le match compte-t-il
# (un QB remplacant qui entre pour 2 passes n'a pas de prop ce jour-la).
# Tranches choisies en validation croisee (2026-10-04). Les tranches fines
# (0-25/25-50/50-75/75+, 200/235/265) echouaient: peu de joueurs par tranche,
# erreur hors echantillon jusqu'a 9 pts (passe) et 12 pts (sol 75+). Plus
# larges, toutes passent sous 3 pts. Trois decoupages testes par marche.
MARKETS = {
    "nfl_prop_pass_yds": {
        "label": "verges de passe", "col": "passing_yards", "pos": {"QB"},
        "keep": lambda r: _f(r, "attempts") >= 10,
        "buckets": [0, 230, 1e9],
    },
    "nfl_prop_reception_yds": {
        "label": "verges de reception", "col": "receiving_yards", "pos": {"WR", "TE", "RB"},
        "keep": lambda r: True,
        "buckets": [0, 25, 50, 1e9],
    },
    "nfl_prop_rush_yds": {
        "label": "verges au sol", "col": "rushing_yards", "pos": {"RB", "QB"},
        "keep": lambda r: _f(r, "carries") >= 1,
        "buckets": [0, 40, 1e9],
    },
}


def _f(r: dict, k: str) -> float:
    try:
        return float(r.get(k) or 0)
    except ValueError:
        return 0.0


def download(season: int) -> str:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"stats_player_week_{season}.csv")
    if not os.path.exists(path):
        print(f"  telechargement nflverse {season}...")
        urllib.request.urlretrieve(URL.format(y=season), path)
    return path


def load_rows(season: int) -> list:
    with open(download(season), encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("season_type") == "REG"]


def samples(rows: list, market: str) -> list:
    """[(mediane_LOO, verges)] pour un marche, sur une saison."""
    spec = MARKETS[market]
    per_player: dict = {}
    for r in rows:
        if r.get("position") not in spec["pos"] or not spec["keep"](r):
            continue
        per_player.setdefault(r["player_id"], []).append(_f(r, spec["col"]))
    out = []
    for ys in per_player.values():
        if len(ys) < MIN_GAMES:
            continue
        for i, y in enumerate(ys):
            m = statistics.median(ys[:i] + ys[i + 1:])
            if m > 0:
                out.append((m, y))
    return out


def _bucket_edges(market: str) -> list:
    e = MARKETS[market]["buckets"]
    return list(zip(e[:-1], e[1:]))


def fit(market: str, data: list) -> dict:
    """Quantiles du ratio par tranche de mediane."""
    buckets = []
    for lo, hi in _bucket_edges(market):
        ratios = sorted(y / m for m, y in data if lo <= m < hi)
        if len(ratios) < 50:
            continue
        n = len(ratios)
        q = []
        for k in range(N_QUANTILES + 1):
            x = k / N_QUANTILES * (n - 1)
            i = int(x)
            j = min(i + 1, n - 1)
            q.append(round(ratios[i] + (x - i) * (ratios[j] - ratios[i]), 5))
        buckets.append({"lo": lo, "hi": hi if hi < 1e8 else 1e9, "n": n,
                        "p_zero": round(sum(1 for r in ratios if r <= 0) / n, 4),
                        "q": q})
    return {"label": MARKETS[market]["label"], "buckets": buckets}


def validate(market: str, cal: dict, test: list) -> list:
    """P predite vs frequence observee, par tranche et par seuil."""
    out = []
    for b in cal["buckets"]:
        sub = [(m, y) for m, y in test if b["lo"] <= m < b["hi"]]
        if not sub:
            continue
        for k in THRESHOLDS:
            pred = sum(M.survival(b, k) for _ in sub) / len(sub)
            obs = sum(1 for m, y in sub if y > k * m) / len(sub)
            se = (obs * (1 - obs) / len(sub)) ** 0.5
            out.append({"tranche": f"{b['lo']:g}-{b['hi']:g}" if b["hi"] < 1e8 else f"{b['lo']:g}+",
                        "seuil": k, "n": len(sub), "p_predite": round(pred, 4),
                        "freq_observee": round(obs, 4), "ecart": round(obs - pred, 4),
                        "ic95": round(1.96 * se, 4)})
    return out


def cross_validate(market: str, per: dict) -> dict:
    """Erreur moyenne par tranche sur ZONE_UTILE, chaque saison testee a son tour."""
    errs: dict = {}
    for test_s in SEASONS:
        cal = fit(market, [x for s in SEASONS if s != test_s for x in per[s]])
        for l in validate(market, cal, per[test_s]):
            if l["seuil"] in ZONE_UTILE:
                errs.setdefault(l["tranche"], []).append(abs(l["ecart"]))
    return {t: round(sum(v) / len(v), 4) for t, v in errs.items()}


def _tranche(b: dict) -> str:
    return f"{b['lo']:g}-{b['hi']:g}" if b["hi"] < 1e8 else f"{b['lo']:g}+"


def run() -> dict:
    rows = {s: load_rows(s) for s in SEASONS}
    train_s, test_s = SEASONS[:-1], SEASONS[-1]
    prod, report = {}, {}
    for market in MARKETS:
        per = {s: samples(rows[s], market) for s in SEASONS}
        train = [x for s in train_s for x in per[s]]
        cal_train = fit(market, train)
        lignes = validate(market, cal_train, per[test_s])
        cv = cross_validate(market, per)
        worst = max((abs(l["ecart"]) for l in lignes), default=0.0)
        hors_ic = sum(1 for l in lignes if abs(l["ecart"]) > l["ic95"])
        prod[market] = fit(market, [x for s in SEASONS for x in per[s]])
        for b in prod[market]["buckets"]:
            t = _tranche(b)
            b["erreur_cv"] = cv.get(t)
            b["valide"] = cv.get(t) is not None and cv[t] <= MAX_ERR_VALID
        report[market] = {"label": MARKETS[market]["label"], "n_train": len(train),
                          "n_test": len(per[test_s]), "lignes": lignes,
                          "ecart_max": round(worst, 4), "hors_ic95": hors_ic,
                          "tranches": [{"tranche": _tranche(b), "n": b["n"],
                                        "erreur_cv": b["erreur_cv"], "valide": b["valide"]}
                                       for b in prod[market]["buckets"]]}
        ok = [t["tranche"] for t in report[market]["tranches"] if t["valide"]]
        print(f"  {market}: train {len(train)} / test {len(per[test_s])} — "
              f"ecart max {worst * 100:.1f} pts, {hors_ic}/{len(lignes)} hors IC95; "
              f"tranches validees: {', '.join(ok) or 'aucune'}")
    now = datetime.now(timezone.utc).isoformat()
    meta = {"generated_at": now, "source": "nflverse stats_player_week (REG)",
            "saisons": SEASONS, "min_matchs": MIN_GAMES,
            "mediane": "mediane des autres matchs du joueur dans la saison",
            "validation": f"plis par saison, erreur moyenne a {ZONE_UTILE[0]}x/{ZONE_UTILE[1]}x "
                          f"<= {MAX_ERR_VALID * 100:g} pts"}
    cal = {"meta": meta, "markets": prod}
    rep = {"meta": dict(meta, calibration=train_s, test=test_s,
                        seuils=THRESHOLDS), "markets": report}
    with open(os.path.join(ROOT, "docs", "nfl_prop_calibration.json"), "w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(ROOT, "docs", "nfl_calibration_report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    return rep


if __name__ == "__main__":
    run()
