"""
Estime les parametres de nhl_dixon_coles.py sur les saisons LNH passees.

Donnees (API LNH gratuite, cache ../.cache/nhl_dc/):
  - calendriers d'equipe (club-schedule-season): score final et type de fin
    (REG / OT / SO) de chaque match de saison reguliere;
  - play-by-play des matchs finis en temps reglementaire avec un ecart: buts
    marques dans un filet desert (situationCode: gardien adverse sorti).

Score en temps reglementaire:
  REG -> score final;   OT / SO -> egalite au score du perdant.
  Hors filet desert = temps reglementaire - buts dans un filet desert.

Estimations:
  1. force d'attaque / defense par equipe et par saison + avantage domicile
     (Poisson multiplicatif, ajustement iteratif — Maher 1982), sur les buts
     en temps reglementaire hors filet desert;
  2. RHO (Dixon-Coles) par maximum de vraisemblance a forces fixees;
  3. EN_Q[m] = P(but dans un filet desert de l'equipe qui menait par m),
     EN_Q2 = P(un second | un premier);
  4. P_OT = part des egalites tranchees en prolongation; OT_HOME, OT_K par
     maximum de vraisemblance (prime a la meilleure equipe); SO_HOME;
  5. REG_SHARE = buts hors filet desert en temps reglementaire / buts
     officiels par match (le lambda d'entree est un « buts par match »).
Validation: log-loss hors echantillon (saison la plus recente, forces de la
saison precedente) de la moneyline a deux issues et du total 5.5/6.5,
Dixon-Coles complet contre Poisson independant.

    cd src && python3 nhl_dc_fit.py        -> ../docs/nhl_dc_params.json
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

import requests

import nhl_dixon_coles as DC

API     = "https://api-web.nhle.com/v1"
SEASONS = os.environ.get("NHL_DC_SEASONS", "20232024,20242025,20252026").split(",")
_HERE   = os.path.dirname(os.path.abspath(__file__))
CACHE   = os.path.join(_HERE, "..", ".cache", "nhl_dc")
OUT     = os.path.join(_HERE, "..", "docs", "nhl_dc_params.json")
TEAMS   = ["ANA", "ARI", "BOS", "BUF", "CGY", "CAR", "CHI", "COL", "CBJ", "DAL", "DET",
           "EDM", "FLA", "LAK", "MIN", "MTL", "NSH", "NJD", "NYI", "NYR", "OTT", "PHI",
           "PIT", "SJS", "SEA", "STL", "TBL", "TOR", "UTA", "VAN", "VGK", "WSH", "WPG"]


# Une seule connexion reutilisee, sans parallelisme: l'API freine les
# connexions simultanees (8 fils: 0.7 appel/s; sequentiel: 5 appels/s).
_session = requests.Session()


def _get(path: str, key: str):
    os.makedirs(CACHE, exist_ok=True)
    fp = os.path.join(CACHE, key + ".json")
    if os.path.exists(fp):
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    for attempt in range(3):
        try:
            r = _session.get(f"{API}/{path}", timeout=20)
            if r.status_code == 200:
                d = r.json()
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(d, f)
                return d
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(1 + attempt)
    return None


def season_games(season: str) -> list:
    games = {}
    for t in TEAMS:
        d = _get(f"club-schedule-season/{t}/{season}", f"sched_{t}_{season}") or {}
        for g in d.get("games", []):
            if g.get("gameType") != 2 or g.get("gameState") not in ("OFF", "FINAL"):
                continue
            games[g["id"]] = {
                "id": g["id"], "season": season, "date": g.get("gameDate", ""),
                "home": g["homeTeam"]["abbrev"], "away": g["awayTeam"]["abbrev"],
                "home_id": g["homeTeam"].get("id"), "hs": g["homeTeam"].get("score"),
                "as": g["awayTeam"].get("score"),
                "end": (g.get("gameOutcome") or {}).get("lastPeriodType", "REG"),
            }
    return sorted(games.values(), key=lambda g: (g["date"], g["id"]))


def empty_net_goals(game: dict) -> tuple:
    """(buts dans un filet desert domicile, visiteur) en temps reglementaire."""
    d = _get(f"gamecenter/{game['id']}/play-by-play", f"pbp_{game['id']}") or {}
    home_id = d.get("homeTeam", {}).get("id", game.get("home_id"))
    en_h = en_a = 0
    for p in d.get("plays", []):
        if p.get("typeDescKey") != "goal":
            continue
        if (p.get("periodDescriptor") or {}).get("number", 1) > 3:
            continue
        sc = str(p.get("situationCode") or "")
        if len(sc) != 4:
            continue
        away_goalie_in, home_goalie_in = sc[0], sc[3]
        owner = (p.get("details") or {}).get("eventOwnerTeamId")
        if owner == home_id and away_goalie_in == "0":
            en_h += 1
        elif owner != home_id and home_goalie_in == "0":
            en_a += 1
    return en_h, en_a


def prepare(games: list) -> list:
    todo = [g for g in games if g["end"] == "REG" and g["hs"] != g["as"]]
    ens = []
    for i, g in enumerate(todo):
        ens.append(empty_net_goals(g))
        if (i + 1) % 250 == 0:
            print(f"    play-by-play {i + 1}/{len(todo)}", flush=True)
    en_by_id = {g["id"]: e for g, e in zip(todo, ens)}
    out = []
    for g in games:
        hs, as_ = g["hs"], g["as"]
        if hs is None or as_ is None:
            continue
        if g["end"] == "REG":
            rh, ra = hs, as_
        else:
            rh = ra = min(hs, as_)
        en_h, en_a = en_by_id.get(g["id"], (0, 0))
        out.append(dict(g, reg_h=rh, reg_a=ra, en_h=en_h, en_a=en_a,
                        pre_h=rh - en_h, pre_a=ra - en_a,
                        official=(hs + as_ - (1 if g["end"] == "SO" else 0))))
    return out


# ── Forces d'equipe (Maher, ajustement iteratif) ────────────────────────────

def team_strengths(games: list, iters: int = 60) -> dict:
    teams = sorted({g["home"] for g in games} | {g["away"] for g in games})
    att = {t: 1.0 for t in teams}
    dfn = {t: 1.0 for t in teams}
    home = 1.05
    for _ in range(iters):
        for t in teams:
            num = sum(g["pre_h"] for g in games if g["home"] == t) + sum(g["pre_a"] for g in games if g["away"] == t)
            den = sum(home * dfn[g["away"]] for g in games if g["home"] == t) + sum(dfn[g["home"]] for g in games if g["away"] == t)
            att[t] = num / den if den else 1.0
        for t in teams:
            num = sum(g["pre_a"] for g in games if g["home"] == t) + sum(g["pre_h"] for g in games if g["away"] == t)
            den = sum(att[g["away"]] for g in games if g["home"] == t) + sum(home * att[g["home"]] for g in games if g["away"] == t)
            dfn[t] = num / den if den else 1.0
        num = sum(g["pre_h"] for g in games)
        den = sum(att[g["home"]] * dfn[g["away"]] for g in games)
        home = num / den if den else 1.0
    return {"att": att, "def": dfn, "home": home}


def lambdas(g: dict, st: dict) -> tuple:
    return (st["home"] * st["att"].get(g["home"], 1.0) * st["def"].get(g["away"], 1.0),
            st["att"].get(g["away"], 1.0) * st["def"].get(g["home"], 1.0))


# ── Estimations ─────────────────────────────────────────────────────────────

def fit_rho(games: list, lam: dict) -> float:
    def nll(rho):
        tot = 0.0
        for g in games:
            lh, la = lam[g["id"]]
            t = DC.tau(g["pre_h"], g["pre_a"], lh, la, rho)
            if t <= 0:
                return float("inf")
            tot -= math.log(t)
        return tot
    grid = [i / 1000 for i in range(-200, 201, 2)]
    return min(grid, key=nll)


def fit_empty_net(games: list) -> tuple:
    q = {}
    for m in (1, 2):
        base = [g for g in games if abs(g["pre_h"] - g["pre_a"]) == m and g["end"] == "REG"]
        hit = [g for g in base if (g["en_h"] if g["pre_h"] > g["pre_a"] else g["en_a"]) >= 1]
        q[m] = len(hit) / len(base) if base else 0.0
    firsts = [g for g in games if (g["en_h"] + g["en_a"]) >= 1]
    q2 = sum(1 for g in firsts if (g["en_h"] + g["en_a"]) >= 2) / len(firsts) if firsts else 0.0
    return q, q2


def fit_overtime(games: list, lam: dict) -> dict:
    ties = [g for g in games if g["end"] in ("OT", "SO")]
    ot = [g for g in ties if g["end"] == "OT"]
    so = [g for g in ties if g["end"] == "SO"]
    p_ot = len(ot) / len(ties) if ties else DC.P_OT
    so_home = sum(1 for g in so if g["hs"] > g["as"]) / len(so) if so else 0.5

    def nll(b0, k):
        tot = 0.0
        for g in ot:
            lh, la = lam[g["id"]]
            d = (lh - la) / (lh + la)
            p = min(max(0.5 + b0 + k * d, 0.01), 0.99)
            tot -= math.log(p if g["hs"] > g["as"] else 1 - p)
        return tot
    best = min(((b0 / 100, k / 10) for b0 in range(-8, 9) for k in range(0, 31)),
               key=lambda x: nll(*x))
    return {"p_ot": p_ot, "so_home": so_home, "ot_home": best[0], "ot_k": best[1],
            "n_ties": len(ties), "n_ot": len(ot), "n_so": len(so)}


def evaluate(test: list, lam: dict, params: dict) -> dict:
    """Log-loss moneyline 2 issues et totaux, modele complet contre Poisson independant."""
    indep = {"rho": 0.0, "en_q": {1: 0.0, 2: 0.0}, "en_q2": 0.0,
             "p_ot": params["p_ot"], "ot_home": 0.0, "ot_k": 0.0, "so_home": 0.5,
             "reg_share": params["reg_share"]}
    res = {}
    for name, p in (("dixon_coles", params), ("poisson_independant", indep)):
        ll_ml = ll_55 = ll_65 = 0.0
        for g in test:
            lh, la = lam[g["id"]]
            gp = DC.game_probs(lh / params["reg_share"], la / params["reg_share"], p)
            home_win = g["hs"] > g["as"]
            q = min(max(gp["home_ml"], 1e-6), 1 - 1e-6)
            ll_ml -= math.log(q if home_win else 1 - q)
            for line, acc in ((5.5, "55"), (6.5, "65")):
                o = min(max(gp["over"](line), 1e-6), 1 - 1e-6)
                val = -math.log(o if g["official"] + (1 if g["end"] == "SO" else 0) > line else 1 - o)
                if acc == "55":
                    ll_55 += val
                else:
                    ll_65 += val
        n = len(test)
        res[name] = {"logloss_ml": ll_ml / n, "logloss_over55": ll_55 / n, "logloss_over65": ll_65 / n}
    res["n"] = len(test)
    return res


def walk_forward_lambdas(games: list, season: str, prev: list) -> dict:
    """
    Lambdas « comme en direct »: chaque mois de `season` est predit avec des
    forces estimees sur les matchs ANTERIEURS de la saison (la saison
    precedente tant qu'il y en a moins de 200).
    """
    cur = [g for g in games if g["season"] == season]
    lam = {}
    for m in sorted({g["date"][:7] for g in cur}):
        before = [g for g in cur if g["date"][:7] < m]
        st = team_strengths(before if len(before) >= 200 else prev + before)
        for g in cur:
            if g["date"][:7] == m:
                lam[g["id"]] = lambdas(g, st)
    return lam


def run():
    all_games = []
    for s in SEASONS:
        gs = prepare(season_games(s))
        print(f"  saison {s}: {len(gs)} matchs, "
              f"{sum(g['en_h'] + g['en_a'] for g in gs)} buts dans un filet desert")
        all_games.extend(gs)
    lam, strengths = {}, {}
    for s in SEASONS:
        gs = [g for g in all_games if g["season"] == s]
        if not gs:
            continue
        st = team_strengths(gs)
        strengths[s] = st
        for g in gs:
            lam[g["id"]] = lambdas(g, st)
    rho = fit_rho(all_games, lam)
    q, q2 = fit_empty_net(all_games)
    ot = fit_overtime(all_games, lam)
    ot["ot_k_en_echantillon"] = ot["ot_k"]
    reg_share = (sum(g["pre_h"] + g["pre_a"] for g in all_games)
                 / sum(g["official"] for g in all_games))
    params = {"rho": rho, "en_q": q, "en_q2": q2, "reg_share": round(reg_share, 4), **ot}

    # Prime en prolongation (OT_K) choisie en walk-forward, pas en echantillon:
    # estimee avec les forces de la meme saison, elle vaut ~0.4, mais en
    # prevision (forces connues AVANT le match) elle degrade la moneyline.
    wf = {}
    for s in SEASONS[1:]:
        prev = [g for g in all_games if g["season"] == SEASONS[SEASONS.index(s) - 1]]
        lam_wf = walk_forward_lambdas(all_games, s, prev)
        test = [g for g in all_games if g["season"] == s]
        wf[s] = {"test": test, "lam": lam_wf}
    if wf:
        grid = [i / 20 for i in range(0, 9)]
        score = {k: sum(evaluate(v["test"], v["lam"], dict(params, ot_k=k))["dixon_coles"]["logloss_ml"]
                        for v in wf.values()) for k in grid}
        params["ot_k"] = min(score, key=score.get)
        params["ot_k_walk_forward"] = {str(k): round(v / len(wf), 5) for k, v in score.items()}

    # Validation hors echantillon: derniere saison, forces de la saison precedente.
    last, prev = SEASONS[-1], SEASONS[-2] if len(SEASONS) > 1 else None
    val = {}
    if prev and prev in strengths:
        test = [g for g in all_games if g["season"] == last]
        lam_oos = {g["id"]: lambdas(g, strengths[prev]) for g in test}
        val = evaluate(test, lam_oos, params)
    league_ga60 = sum(g["official"] for g in all_games) / len(all_games) / 2.0 * 60 / 60.0
    val_wf = {s: evaluate(v["test"], v["lam"], params) for s, v in wf.items()}
    report = {"seasons": SEASONS, "n_games": len(all_games), "params": params,
              "league_goals_per_team_game": round(league_ga60, 3),
              "validation_saison_precedente": val, "validation_walk_forward": val_wf}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    return report


if __name__ == "__main__":
    rep = run()
    print(json.dumps({k: rep[k] for k in ("n_games", "params", "league_goals_per_team_game",
                                         "validation_saison_precedente", "validation_walk_forward")},
                     indent=2, default=str))
