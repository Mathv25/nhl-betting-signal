"""
Suivi des paris reellement pris — docs/bets.json.

A ne pas confondre avec docs/results.json, qui enregistre ce que le MODELE a
propose (via backtester.py). Ce module-ci enregistre ce qui a ete MISE: la
cote obtenue, chez quel book, pour combien, et la cote de fermeture. C'est la
seule source qui permette de mesurer un yield reel et un CLV de prix.

Pourquoi JSON et non SQLite: le dashboard est une page statique servie par
GitHub Pages qui lit ses donnees par fetch(). Un fichier SQLite ne se lit pas
depuis le navigateur sans embarquer un moteur, et son binaire ne diffe pas en
git — or tout l'etat de ce projet traverse les executions par le depot.

Les statistiques sont recalculees a CHAQUE ecriture et stockees dans le meme
fichier: le dashboard n'a alors qu'a afficher, et les chiffres ne peuvent pas
divergerentre le CLI et la page.

Conventions de reglement:
  win   -> profit = stake x (cote - 1)
  loss  -> profit = -stake
  push  -> mise remboursee: profit 0, ET la mise sort du denominateur du yield
           (rien n'a ete risque au reglement; la compter diluerait le yield).
           Le nombre de push reste affiche pour que rien ne disparaisse.
  pending -> pas encore regle, exclu de tout calcul de rendement.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))

RESULTS  = ("win", "loss", "push", "pending")
SETTLED  = ("win", "loss", "push")
COUNTING = ("win", "loss")      # ce qui compte dans le WR et le yield

# Largeur des tranches de calibration, en points de probabilite.
BUCKET_WIDTH = 5

# 1.96 ecarts-types = intervalle bilateral a 95% (approximation normale).
Z95 = 1.959964


def bets_path() -> str:
    return os.environ.get("BETS_PATH") or os.path.join(_HERE, "..", "docs", "bets.json")


# ── Entrees/sorties ─────────────────────────────────────────────────────────

def load(path: str = None) -> dict:
    """Contenu du fichier, ou une structure vide s'il n'existe pas encore."""
    try:
        with open(path or bets_path(), "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        data = {}
    data.setdefault("bets", [])
    return data


def save(data: dict, path: str = None) -> dict:
    """Ecrit le fichier avec des stats fraiches. Ecriture atomique."""
    data["stats"]      = compute_stats(data.get("bets", []))
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    p = path or bets_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return data


# ── Ecriture d'un pari ──────────────────────────────────────────────────────

def make_id(bet: dict, existing: list) -> str:
    """
    Identifiant lisible et stable. Un suffixe est ajoute en cas de collision:
    deux paris identiques le meme jour a des cotes differentes sont deux paris,
    pas un doublon a ecraser.
    """
    base = "|".join([bet.get("date", ""), bet.get("sport", ""),
                     bet.get("market", ""), bet.get("selection", "")])
    taken = {b.get("id") for b in existing}
    if base not in taken:
        return base
    n = 2
    while f"{base}#{n}" in taken:
        n += 1
    return f"{base}#{n}"


def _num(value, name: str, minimum=None):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name}: nombre attendu, recu {value!r}")
    if minimum is not None and v < minimum:
        raise ValueError(f"{name}: doit etre >= {minimum} (recu {v})")
    return v


def add_bet(date: str, sport: str, market: str, selection: str,
            model_prob: float, odds_taken: float, book: str,
            stake: float = 1.0, closing_odds=None, result: str = "pending",
            note: str = "", path: str = None) -> dict:
    """
    Enregistre un pari pris. Valide a l'entree plutot qu'a l'affichage: une
    cote a 0 ou une probabilite en fraction (0.55 au lieu de 55) fausse
    silencieusement tous les agregats en aval.
    """
    result = (result or "pending").lower()
    if result not in RESULTS:
        raise ValueError(f"result: attendu {'/'.join(RESULTS)}, recu {result!r}")
    prob = _num(model_prob, "model_prob", 0)
    if prob <= 1:
        raise ValueError(f"model_prob attendu en POURCENTAGE (55 et non 0.55), recu {prob}")
    if prob > 100:
        raise ValueError(f"model_prob: {prob} > 100")
    odds = _num(odds_taken, "odds_taken", 1.01)
    stk  = _num(stake, "stake", 0.01)
    close = None if closing_odds in (None, "", 0) else _num(closing_odds, "closing_odds", 1.01)
    if not (date and sport and market and selection):
        raise ValueError("date, sport, market et selection sont obligatoires")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"date: format AAAA-MM-JJ attendu, recu {date!r}")

    data = load(path)
    bet = {
        "date":         date,
        "sport":        sport.lower().strip(),
        "market":       market.lower().strip(),
        "selection":    selection.strip(),
        "model_prob":   round(prob, 2),
        "odds_taken":   round(odds, 3),
        "book":         (book or "").lower().strip(),
        "stake":        round(stk, 3),
        "closing_odds": round(close, 3) if close else None,
        "result":       result,
        "note":         note.strip(),
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }
    bet["id"] = make_id(bet, data["bets"])
    data["bets"].append(bet)
    save(data, path)
    return bet


def close_bet(bet_id: str, closing_odds=None, result: str = None,
              path: str = None) -> dict:
    """
    Renseigne la cote de fermeture et/ou le resultat d'un pari existant.
    Les deux sont independants: la cote de fermeture se releve avant le match,
    le resultat apres.
    """
    data = load(path)
    bet = next((b for b in data["bets"] if b.get("id") == bet_id), None)
    if bet is None:
        raise KeyError(f"aucun pari avec l'id {bet_id!r}")
    if closing_odds not in (None, ""):
        bet["closing_odds"] = round(_num(closing_odds, "closing_odds", 1.01), 3)
    if result:
        r = result.lower()
        if r not in RESULTS:
            raise ValueError(f"result: attendu {'/'.join(RESULTS)}, recu {result!r}")
        bet["result"] = r
        bet["closed_at"] = datetime.now(timezone.utc).isoformat()
    save(data, path)
    return bet


def pending(bets: list) -> list:
    return [b for b in bets if b.get("result", "pending") == "pending"]


def missing_closing(bets: list) -> list:
    return [b for b in bets if not b.get("closing_odds")]


# ── Statistiques ────────────────────────────────────────────────────────────

def profit(bet: dict):
    """Profit en unites de mise. None si le pari n'est pas regle."""
    r = bet.get("result", "pending")
    if r not in SETTLED:
        return None
    stake = float(bet.get("stake") or 0)
    if r == "push":
        return 0.0
    if r == "win":
        return stake * (float(bet.get("odds_taken") or 0) - 1.0)
    return -stake


def yield_with_ci(counted: list) -> dict:
    """
    Yield = profit total / mise totale, avec son intervalle a 95%.

    L'intervalle vient de l'estimateur de ratio: le yield est un rapport de
    deux sommes, pas une moyenne simple, et les mises peuvent differer d'un
    pari a l'autre.

        Y  = Sp / Ss
        e_i = p_i - Y x s_i           (residu de chaque pari)
        SE = sqrt(Sum e_i^2) / Ss
        IC = Y +/- 1.96 x SE

    Quand toutes les mises sont egales, cela redonne l'erreur-type classique
    de la moyenne des rendements. L'approximation normale demande un
    echantillon: sous 30 paris regles, `reliable` est False et le dashboard
    doit le dire au lieu d'afficher un yield qui a l'air d'un resultat.
    """
    n = len(counted)
    staked = sum(float(b.get("stake") or 0) for b in counted)
    if not n or staked <= 0:
        return {"n": n, "staked": round(staked, 2), "profit": 0.0,
                "yield_pct": None, "ci_low": None, "ci_high": None,
                "se_pct": None, "reliable": False}

    total = sum(profit(b) or 0.0 for b in counted)
    y     = total / staked
    # A n = 1 le residu est nul par construction (le ratio passe exactement par
    # le point): l'intervalle sortirait [Y ; Y], donc une precision imaginaire.
    # On ne publie pas d'intervalle avant 2 paris.
    if n < 2:
        se = None
    else:
        resid = sum(((profit(b) or 0.0) - y * float(b.get("stake") or 0)) ** 2
                    for b in counted)
        se = math.sqrt(resid) / staked
    return {
        "n":         n,
        "staked":    round(staked, 2),
        "profit":    round(total, 3),
        "yield_pct": round(y * 100, 2),
        "se_pct":    round(se * 100, 2) if se is not None else None,
        "ci_low":    round((y - Z95 * se) * 100, 2) if se is not None else None,
        "ci_high":   round((y + Z95 * se) * 100, 2) if se is not None else None,
        # Deux conditions distinctes: assez de paris pour l'approximation
        # normale, et un intervalle qui ne contient pas 0.
        "reliable":  n >= 30,
        "excludes_zero": (se is not None and n >= 30
                          and ((y - Z95 * se) > 0 or (y + Z95 * se) < 0)),
    }


def _wr_and_odds(counted: list) -> dict:
    """
    Win rate ET cote moyenne, toujours ensemble: un WR de 53% est excellent a
    2.10 et ruineux a 1.60. La cote moyenne est ponderee par la mise, comme le
    yield, et on donne le seuil de rentabilite qui lui correspond.
    """
    n = len(counted)
    if not n:
        return {"n": 0, "wins": 0, "losses": 0, "win_rate": None,
                "avg_odds": None, "breakeven_wr": None, "wr_vs_breakeven": None}
    wins   = sum(1 for b in counted if b.get("result") == "win")
    staked = sum(float(b.get("stake") or 0) for b in counted) or 1.0
    avg_odds = sum(float(b.get("odds_taken") or 0) * float(b.get("stake") or 0)
                   for b in counted) / staked
    wr = wins / n * 100
    be = (100.0 / avg_odds) if avg_odds > 0 else None
    return {
        "n":              n,
        "wins":           wins,
        "losses":         n - wins,
        "win_rate":       round(wr, 2),
        "avg_odds":       round(avg_odds, 3),
        "breakeven_wr":   round(be, 2) if be else None,
        "wr_vs_breakeven": round(wr - be, 2) if be else None,
    }


def clv_stats(bets: list) -> dict:
    """
    CLV de prix: moyenne de (cote_prise / cote_fermeture - 1).

    > 0 = on a pris un meilleur prix que la fermeture, le marche est venu vers
    nous. C'est le meilleur indicateur precoce disponible: il se mesure sans
    attendre les resultats et il est bien moins bruite que le yield.

    Grandeur differente du champ `clv` de results.json, qui est un ecart de
    probabilites implicites en points. Les deux ne se comparent pas.
    """
    usable = [b for b in bets
              if b.get("closing_odds") and float(b.get("closing_odds")) > 1
              and b.get("odds_taken")]
    n = len(usable)
    if not n:
        return {"n": 0, "avg_clv_pct": None, "pct_positive": None,
                "beat_close": 0, "n_missing": len(missing_closing(bets))}
    vals = [float(b["odds_taken"]) / float(b["closing_odds"]) - 1.0 for b in usable]
    beat = sum(1 for v in vals if v > 0)
    return {
        "n":            n,
        "avg_clv_pct":  round(sum(vals) / n * 100, 2),
        "pct_positive": round(beat / n * 100, 1),
        "beat_close":   beat,
        "n_missing":    len(missing_closing(bets)),
    }


def bucket_label(prob: float) -> str:
    lo = int(prob // BUCKET_WIDTH) * BUCKET_WIDTH
    return f"{lo}-{lo + BUCKET_WIDTH}"


def calibration(bets: list) -> list:
    """
    Courbe de calibration: on regroupe les paris par tranche de probabilite du
    modele et on compare la probabilite annoncee au taux de reussite observe.

    C'est ce qui distingue un modele juste d'un modele optimiste: un modele qui
    dit 60% et gagne 52% du temps n'a pas un probleme de chance, il a un
    probleme d'echelle. `gap` est l'ecart observe - annonce, en points.

    Seules les tranches non vides sont retournees, triees par probabilite. Les
    push sont exclus (aucune issue a comparer).
    """
    counted = [b for b in bets if b.get("result") in COUNTING]
    groups: dict = {}
    for b in counted:
        try:
            p = float(b.get("model_prob"))
        except (TypeError, ValueError):
            continue
        groups.setdefault(bucket_label(p), []).append((p, b))

    out = []
    for label, items in groups.items():
        n     = len(items)
        wins  = sum(1 for _, b in items if b.get("result") == "win")
        exp   = sum(p for p, _ in items) / n
        obs   = wins / n * 100
        staked = sum(float(b.get("stake") or 0) for _, b in items) or 1.0
        out.append({
            "bucket":     label,
            "low":        int(label.split("-")[0]),
            "n":          n,
            "wins":       wins,
            "expected":   round(exp, 2),
            "observed":   round(obs, 2),
            "gap":        round(obs - exp, 2),
            "avg_odds":   round(sum(float(b.get("odds_taken") or 0) * float(b.get("stake") or 0)
                                    for _, b in items) / staked, 3),
            "profit":     round(sum(profit(b) or 0.0 for _, b in items), 3),
            # Sous 20 paris une tranche ne dit presque rien: +/-11 points
            # d'ecart-type sur un taux a 50%.
            "thin":       n < 20,
        })
    return sorted(out, key=lambda r: r["low"])


def by_market(bets: list) -> list:
    """ROI par marche, avec WR et cote moyenne — jamais le ROI seul."""
    groups: dict = {}
    for b in bets:
        if b.get("result") in COUNTING:
            groups.setdefault(b.get("market", "?"), []).append(b)
    out = []
    for market, items in groups.items():
        y = yield_with_ci(items)
        w = _wr_and_odds(items)
        out.append({
            "market":     market,
            "n":          y["n"],
            "staked":     y["staked"],
            "profit":     y["profit"],
            "roi_pct":    y["yield_pct"],
            "ci_low":     y["ci_low"],
            "ci_high":    y["ci_high"],
            "reliable":   y["reliable"],
            "win_rate":   w["win_rate"],
            "avg_odds":   w["avg_odds"],
            "breakeven_wr": w["breakeven_wr"],
        })
    return sorted(out, key=lambda r: -(r["n"] or 0))


def by_sport(bets: list) -> list:
    groups: dict = {}
    for b in bets:
        if b.get("result") in COUNTING:
            groups.setdefault(b.get("sport", "?"), []).append(b)
    out = []
    for sport, items in groups.items():
        y = yield_with_ci(items)
        w = _wr_and_odds(items)
        out.append({"sport": sport, "n": y["n"], "profit": y["profit"],
                    "roi_pct": y["yield_pct"], "win_rate": w["win_rate"],
                    "avg_odds": w["avg_odds"], "reliable": y["reliable"]})
    return sorted(out, key=lambda r: -(r["n"] or 0))


def compute_stats(bets: list) -> dict:
    """Tout ce que l'onglet Performance affiche, calcule une seule fois ici."""
    counted = [b for b in bets if b.get("result") in COUNTING]
    y = yield_with_ci(counted)
    return {
        "n_bets":      len(bets),
        "n_settled":   sum(1 for b in bets if b.get("result") in SETTLED),
        "n_counted":   len(counted),
        "n_push":      sum(1 for b in bets if b.get("result") == "push"),
        "n_pending":   len(pending(bets)),
        "yield":       y,
        "record":      _wr_and_odds(counted),
        "clv":         clv_stats(bets),
        "calibration": calibration(bets),
        "by_market":   by_market(bets),
        "by_sport":    by_sport(bets),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
