"""
Projection des tirs au but (SOG) d'un joueur LNH pour un match.

    lambda = conv x [ r5 x TOI5 x f_adv5  +  rPP x TOIpp x f_advPP  +  autre ]
                    x f_domicile x f_b2b_joueur x f_b2b_adv x f_rythme

  r5, rPP  tentatives individuelles (iCF) par heure, a 5v5 et en avantage,
           ponderees saison / 10 derniers matchs (W_SEASON, defaut 60/40).
           Saison = saison en cours RETRECIE vers le taux de la saison
           precedente du joueur (sinon moyenne de sa position), avec un
           poids equivalent a PRIOR_GAMES matchs: en debut de saison, 3
           matchs ne disent presque rien d'un taux de tir.
  TOI5, TOIpp  temps de glace projete = moyenne des TOI_WINDOW derniers
           matchs (egalite pour 5v5, voir nhl_sog_data). Un ecart de plus de
           20% entre les 3 derniers matchs et les 10 precedents leve un
           drapeau « role change » (trio ou vague d'avantage).
  f_adv5   tentatives accordees a 5v5 par match par l'adversaire / ligue,
           retrecies vers 1 (ADV_PRIOR_GAMES).
  f_advPP  temps d'avantage concede par match par l'adversaire / ligue
           (proxy des minutes de penalite: plus il se penalise, plus le
           joueur passe de temps en avantage).
  autre    tentatives en 4v4, 3v3, desavantage, filet desert: moyenne par
           match, faible.
  conv     tirs cadres / tentatives du joueur (bloques et rates retires),
           retreci vers sa position (CONV_PRIOR_ATTEMPTS tentatives).
  f_*      facteurs de contexte ESTIMES sur la saison precedente (fit_context),
           jamais sur la saison testee: domicile, back-to-back du joueur et de
           l'adversaire, rythme = total de buts projete du match / ligue.

Distribution: binomiale negative (moyenne lambda, variance lambda + lambda^2/r)
ou Poisson, choisie par backtest (nhl_sog_backtest). r est estime par maximum
de vraisemblance sur la saison precedente.

INCERTITUDES connues, dites plutot que cachees:
  - Pas de trios officiels avant le match: le « role change » se lit dans le
    temps de glace, a posteriori. Un joueur promu ce matin n'est pas vu.
  - TOI 5v5 approxime par le TOI a egalite (inclut 4v4).
  - Le total de buts projete vient des moyennes de buts des deux equipes
    (walk-forward), pas du modele Dixon-Coles ni du marche.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import date

# ── Reglages (configurables) ────────────────────────────────────────────────
W_SEASON = 0.60            # poids saison vs 10 derniers matchs
LAST_N = 10
TOI_WINDOW = 7
PRIOR_GAMES = 20           # retrecissement des taux vers le prior
PP_PRIOR_MIN = 60.0        # minutes d'avantage equivalentes pour le prior PP
CONV_PRIOR_ATTEMPTS = 150
ADV_PRIOR_GAMES = 10
ROLE_CHANGE = 0.20

# Univers (configurable): joueurs a gros volume.
MIN_SOG_PG = 3.0
MIN_ICF_PG = 5.5
MIN_GP = 10
# Le seuil de matchs et de volume se lit sur la saison en cours COMPLETEE par
# la saison precedente tant que la saison en cours a moins de MIN_GP matchs.
# Sans cela, l'onglet serait vide les trois premieres semaines de la saison.
GP_INCLUDE_PREV = True

LINES = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5]


class History:
    """
    Etat walk-forward: on y AJOUTE les matchs au fil du calendrier, et on ne
    projette un match qu'avec ce qui a ete ajoute avant lui. C'est ce qui
    garantit l'absence de fuite dans le backtest.
    """

    def __init__(self, prev_players: list = (), prev_teams: list = ()):
        self.games = defaultdict(list)            # playerId -> lignes (saison en cours)
        self.team_games = defaultdict(list)       # team -> lignes equipe (saison en cours)
        self.team_dates = defaultdict(set)        # team -> dates jouees (toutes saisons)
        self.prev = {}                            # playerId -> taux saison precedente
        self.prev_rows = defaultdict(list)
        self._league_prev = None
        self.league = _league(prev_players, prev_teams) if prev_players else None
        for r in prev_players:
            self.prev_rows[r["playerId"]].append(r)
        for pid, rows in self.prev_rows.items():
            self.prev[pid] = _rates(rows)
        for t in prev_teams:
            self.team_dates[t["team"]].add(t["gameDate"])
        self._cur_league_rows = []

    def add_game(self, player_rows: list, team_rows: list) -> None:
        for r in player_rows:
            self.games[r["playerId"]].append(r)
            self._cur_league_rows.append(r)
        for t in team_rows:
            self.team_games[t["team"]].append(t)
            self.team_dates[t["team"]].add(t["gameDate"])

    # ── reference ligue ──
    def league_ref(self) -> dict:
        """
        Moyennes ligue: celles de la saison precedente tant que la saison en
        cours compte moins de ~8000 lignes joueur-match (environ 220 matchs),
        ensuite celles de la saison en cours. Recalculees au plus une fois
        par jour de calendrier (cache), c'est le poste le plus couteux.
        """
        n = len(self._cur_league_rows)
        if self.league is not None and n <= 8000:
            return self.league
        key = self._cur_league_rows[-1]["gameDate"] if n else ""
        if getattr(self, "_lg_key", None) != key:
            self._lg_cache = _league(self._cur_league_rows,
                                     [t for ts in self.team_games.values() for t in ts])
            self._lg_key = key
        return self._lg_cache


def _rates(rows: list) -> dict:
    """Taux bruts d'un joueur sur un ensemble de matchs."""
    s = lambda k: sum(r[k] for r in rows)
    ev_h, pp_h = s("toi_ev") / 3600.0, s("toi_pp") / 3600.0
    n = len(rows)
    other = s("icf") - s("icf_5v5") - s("icf_pp")
    return {
        "gp": n, "sog": s("sog"), "icf": s("icf"), "icf5": s("icf_5v5"), "icfpp": s("icf_pp"),
        "ev_h": ev_h, "pp_h": pp_h,
        "r5": s("icf_5v5") / ev_h if ev_h > 0 else None,
        "rpp": s("icf_pp") / pp_h if pp_h > 0 else None,
        "other_pg": max(other, 0) / n if n else 0.0,
        "conv": s("sog") / s("icf") if s("icf") > 0 else None,
        "sog_pg": s("sog") / n if n else 0.0, "icf_pg": s("icf") / n if n else 0.0,
    }


def _league(players: list, teams: list) -> dict:
    by_pos = defaultdict(list)
    for r in players:
        by_pos["D" if r.get("pos") == "D" else "F"].append(r)
    ref = {pos: _rates(rows) for pos, rows in by_pos.items() if rows}
    n_t = len(teams) or 1
    ref["icfa5_pg"] = sum(t["icf_against_5v5"] for t in teams) / n_t
    ref["pp_toi_pg"] = sum(t["pp_toi"] for t in teams) / n_t
    ref["goals_pg"] = sum(t["gf"] for t in teams) / n_t
    return ref


def _shrink(x_num, x_den, prior_rate, prior_den):
    if prior_rate is None:
        return x_num / x_den if x_den > 0 else None
    return (x_num + prior_rate * prior_den) / (x_den + prior_den)


def _team_factor(rows: list, key: str, league_val: float, k: int) -> float:
    """Ratio d'une stat d'equipe a la ligue, retreci vers 1 avec k matchs."""
    if not league_val:
        return 1.0
    n = len(rows)
    tot = sum(r[key] for r in rows)
    return ((tot + k * league_val) / (n + k)) / league_val


def _opp_pp_conceded(h: History, opp: str) -> list:
    """Temps d'avantage donne par `opp`: le pp_toi de ses adversaires."""
    out = []
    for t in h.team_games.get(opp, []):
        for u in h.team_games.get(t["opp"], []):
            if u["gameId"] == t["gameId"]:
                out.append({"pp_toi": u["pp_toi"]})
                break
    return out


def eligibility(h: History, pid: int) -> dict:
    """GP, SOG/match, iCF/match pour le filtre d'univers."""
    cur = h.games.get(pid, [])
    rows = list(cur)
    if GP_INCLUDE_PREV and len(cur) < MIN_GP:
        rows = h.prev_rows.get(pid, [])[-(MIN_GP * 3):] + rows
    r = _rates(rows) if rows else {"gp": 0, "sog_pg": 0, "icf_pg": 0}
    ok = r["gp"] >= MIN_GP and r["sog_pg"] >= MIN_SOG_PG and r["icf_pg"] >= MIN_ICF_PG
    return {"gp": r["gp"], "sog_pg": r["sog_pg"], "icf_pg": r["icf_pg"], "ok": ok,
            "gp_cur": len(cur)}


def project(h: History, pid: int, team: str, opp: str, home: int, gdate: str,
            ctx: dict = None) -> dict:
    """
    Projection d'un joueur pour un match, avec ce que `h` contient (rien du
    match lui-meme). Retourne {lam, detail..., flags} ou None si pas de donnees.
    """
    cur = h.games.get(pid, [])
    prev = h.prev.get(pid)
    if not cur and not prev:
        return None
    lg = h.league_ref()
    pos_rows = (cur or h.prev_rows.get(pid, []))
    pos = "D" if pos_rows and pos_rows[-1].get("pos") == "D" else "F"
    base = lg.get(pos) or lg.get("F")
    cs = _rates(cur) if cur else None

    # Prior = saison precedente du joueur (si 20+ matchs), sinon sa position.
    pr = prev if (prev and prev["gp"] >= 20) else base
    ev_prior_h = PRIOR_GAMES * (pr["ev_h"] / pr["gp"] if pr["gp"] else 0.25)
    r5_season = _shrink(cs["icf5"] if cs else 0, cs["ev_h"] if cs else 0, pr["r5"] or base["r5"], ev_prior_h)
    rpp_season = _shrink(cs["icfpp"] if cs else 0, cs["pp_h"] if cs else 0,
                         pr["rpp"] or base["rpp"], PP_PRIOR_MIN / 60.0)
    last = _rates(cur[-LAST_N:]) if len(cur) >= 3 else None
    r5 = r5_season if not last or last["r5"] is None else W_SEASON * r5_season + (1 - W_SEASON) * last["r5"]
    rpp = rpp_season if not last or last["rpp"] is None else W_SEASON * rpp_season + (1 - W_SEASON) * last["rpp"]

    # Temps de glace: derniers matchs (saison en cours, sinon fin de la precedente).
    recent = (h.prev_rows.get(pid, []) + cur)[-TOI_WINDOW:]
    toi5 = sum(r["toi_ev"] for r in recent) / len(recent) / 3600.0
    toipp = sum(r["toi_pp"] for r in recent) / len(recent) / 3600.0
    flags = []
    hist = (h.prev_rows.get(pid, []) + cur)
    if len(hist) >= 13:
        a3 = hist[-3:]
        b10 = hist[-13:-3]
        for key, lab in (("toi_ev", "TOI egalite"), ("toi_pp", "TOI avantage")):
            x = sum(r[key] for r in a3) / 3
            y = sum(r[key] for r in b10) / 10
            if y > 60 and abs(x - y) / y > ROLE_CHANGE:
                flags.append(f"{lab} {'+' if x > y else '-'}{abs(x - y) / y * 100:.0f}% (3 derniers)")

    conv_prior = pr["conv"] or base["conv"]
    conv = _shrink(cs["sog"] if cs else 0, cs["icf"] if cs else 0, conv_prior, CONV_PRIOR_ATTEMPTS)
    other = (cs["other_pg"] if cs and cs["gp"] >= 5 else (prev or base)["other_pg"])

    f5 = _team_factor(h.team_games.get(opp, []), "icf_against_5v5", lg["icfa5_pg"], ADV_PRIOR_GAMES)
    fpp = _team_factor(_opp_pp_conceded(h, opp), "pp_toi", lg["pp_toi_pg"], ADV_PRIOR_GAMES)

    attempts = r5 * toi5 * f5 + rpp * toipp * fpp + other
    lam0 = conv * attempts

    # Contexte
    ctx = ctx or {}
    d = date.fromisoformat(gdate)
    prev_day = (d.toordinal() - 1)
    b2b_me = any(date.fromisoformat(x).toordinal() == prev_day for x in h.team_dates.get(team, ()))
    b2b_opp = any(date.fromisoformat(x).toordinal() == prev_day for x in h.team_dates.get(opp, ()))
    gpg = lambda t, k: _team_factor(h.team_games.get(t, []), k, lg["goals_pg"], ADV_PRIOR_GAMES)
    pace = (gpg(team, "gf") * gpg(opp, "ga") + gpg(opp, "gf") * gpg(team, "ga")) / 2.0
    f = 1.0
    f *= ctx.get("home", {}).get(str(int(home)), 1.0)
    f *= ctx.get("b2b_me", {}).get(str(int(b2b_me)), 1.0)
    f *= ctx.get("b2b_opp", {}).get(str(int(b2b_opp)), 1.0)
    f *= pace ** ctx.get("pace_beta", 0.0)
    lam = lam0 * f
    return {
        "lam": round(lam, 4), "lam_base": round(lam0, 4), "r5": r5, "rpp": rpp,
        "toi5_min": toi5 * 60, "toipp_min": toipp * 60, "conv": conv, "f_adv5": f5,
        "f_advpp": fpp, "other": other, "home": int(home), "b2b_me": int(b2b_me),
        "b2b_opp": int(b2b_opp), "pace": pace, "f_ctx": f, "flags": flags,
    }


# ── Distributions ───────────────────────────────────────────────────────────

def pois_cdf(k: int, lam: float) -> float:
    if k < 0:
        return 0.0
    term = math.exp(-lam)
    s = term
    for i in range(1, k + 1):
        term *= lam / i
        s += term
    return min(s, 1.0)


def nb_pmf(k: int, mu: float, r: float) -> float:
    p = r / (r + mu)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)
                    + r * math.log(p) + k * math.log(1 - p))


def nb_cdf(k: int, mu: float, r: float) -> float:
    return min(sum(nb_pmf(i, mu, r) for i in range(0, k + 1)), 1.0) if k >= 0 else 0.0


def p_over(line: float, lam: float, dist: str = "nb", r: float = None) -> float:
    """P(X > line) pour une ligne en .5."""
    k = int(math.floor(line))
    if dist == "nb" and r:
        return 1.0 - nb_cdf(k, lam, r)
    return 1.0 - pois_cdf(k, lam)


def fit_nb_r(pairs: list) -> float:
    """r par maximum de vraisemblance sur (y, lambda), recherche sur grille log."""
    best, best_ll = None, -1e18
    for i in range(0, 121):
        r = 10 ** (-0.5 + i * 0.03)          # 0.3 .. ~1260
        ll = 0.0
        for y, mu in pairs:
            ll += math.log(max(nb_pmf(int(y), max(mu, 1e-6), r), 1e-300))
        if ll > best_ll:
            best, best_ll = r, ll
    return best


def fit_context(records: list) -> dict:
    """
    Facteurs de contexte = ratio realise / projete (lam_base) par categorie,
    et exposant de rythme par moindres carres sur log(ratio) ~ log(pace).
    `records`: dicts {y, lam_base, home, b2b_me, b2b_opp, pace}.
    """
    def ratio(key):
        out = {}
        for v in (0, 1):
            sel = [x for x in records if x[key] == v]
            if len(sel) >= 200:
                out[str(v)] = sum(x["y"] for x in sel) / sum(x["lam_base"] for x in sel)
        # normalise pour que la moyenne ponderee vaille 1
        tot_y = sum(x["y"] for x in records)
        tot_l = sum(x["lam_base"] * out.get(str(x[key]), 1.0) for x in records)
        k = tot_y / tot_l if tot_l else 1.0
        return {kk: round(vv * k, 4) for kk, vv in out.items()}
    xs = [(math.log(x["pace"]), x["y"] / x["lam_base"]) for x in records
          if x["pace"] > 0 and x["lam_base"] > 0]
    mx = sum(a for a, _ in xs) / len(xs)
    my = sum(b for _, b in xs) / len(xs)
    cov = sum((a - mx) * (b - my) for a, b in xs)
    var = sum((a - mx) ** 2 for a, _ in xs)
    beta = cov / var / my if var else 0.0         # d(ratio)/d(log pace), normalise
    return {"home": ratio("home"), "b2b_me": ratio("b2b_me"),
            "b2b_opp": ratio("b2b_opp"), "pace_beta": round(max(min(beta, 1.5), -1.5), 4)}
