"""
Module NFL — signaux top-down sur les marches principaux.

v1 SANS modele maison. On ne pretend donc pas savoir qui va gagner: on cherche
seulement des ecarts entre books. La probabilite de reference est celle du
marche efficient (Pinnacle deviggee, sinon la mediane des books deviggees), et
on signale quand un autre book offre un prix qui bat cette reference d'au moins
NFL_MIN_EDGE pour cent.

    edge = prob_reference x meilleure_cote - 1

C'est une esperance, pas un ecart relatif de probabilites: la grandeur
`edge_pct` du MLB (filtree entre 15 et 35%) mesure autre chose et ses seuils
n'ont aucun sens ici. Battre une ligne efficiente de 15% n'arrive pas; 2 a 5%
est l'ordre de grandeur reel du shopping entre books.

CADENCE. Le quota Odds API sert d'abord au MLB et au NHL, qui jouent tous les
jours. La NFL joue jeudi, dimanche et lundi: on ne paie donc des cotes que
trois fois par semaine (voir should_fetch), et le dashboard affiche entre-temps
le dernier etat connu, lu dans docs/nfl_signals.json.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import odds_api

SPORT   = "americanfootball_nfl"
MARKETS = ["h2h", "spreads", "totals"]

_HERE = os.path.dirname(os.path.abspath(__file__))

# Libelles de marche utilises dans le tracker et le dashboard.
MARKET_KEYS = {"h2h": "nfl_ml", "spreads": "nfl_spread", "totals": "nfl_total"}


def signals_path() -> str:
    return os.environ.get("NFL_SIGNALS_PATH") or os.path.join(
        _HERE, "..", "docs", "nfl_signals.json")


def min_books() -> int:
    """
    Nombre minimal de books pour qu'un signal soit emis.

    Une "mediane" calculee sur deux books n'est pas un consensus, c'est une
    moyenne de deux avis. Le premier run l'a montre: sur 18 signaux, 10
    reposaient sur 2 ou 3 books, et les matchs de decembre affichaient des
    50.0%/50.0% — un seul book cotant les deux faces au meme prix, ce qui n'est
    pas un marche mais un remplissage. Ces lignes lointaines produisent des
    ecarts enormes qui n'existent pas.
    """
    try:
        return int(os.environ.get("NFL_MIN_BOOKS", "") or 4)
    except ValueError:
        return 4


def min_edge() -> float:
    """Seuil d'esperance en %, au-dela duquel un ecart entre books est signale."""
    try:
        return float(os.environ.get("NFL_MIN_EDGE", "") or 3.0)
    except ValueError:
        return 3.0


# ── Cadence ─────────────────────────────────────────────────────────────────

def now_et() -> datetime:
    """Heure ET approchee (UTC-4). Suffisant pour choisir un jour et une heure."""
    return datetime.now(timezone.utc) - timedelta(hours=4)


def should_fetch(when: datetime = None) -> tuple:
    """
    Faut-il payer des cotes NFL maintenant ? Retourne (bool, motif).

    Trois fenetres par semaine, choisies pour ce qu'elles apprennent:
      mardi          — ouverture des lignes, c'est la que les ecarts entre
                       books sont les plus larges;
      vendredi       — mouvement de mi-semaine, apres les rapports de blessures;
      dimanche 9-12h — lignes quasi finales, et c'est le moment de relever les
                       cotes de fermeture pour le CLV.

    Le reste du temps on ne depense rien: le MLB et le NHL jouent tous les
    jours et ont besoin du quota.
    """
    d = when or now_et()
    wd = d.weekday()          # 0 = lundi
    if wd == 1:
        return True, "mardi — ouverture des lignes"
    if wd == 4:
        return True, "vendredi — mouvement de mi-semaine"
    if wd == 6 and 9 <= d.hour < 12:
        return True, "dimanche matin — lignes finales et cotes de fermeture"
    return False, f"hors fenetre NFL ({d:%A %Hh} ET)"


def window_id(when: datetime = None) -> str:
    """
    Identifiant de la fenetre de releve en cours, ou None hors fenetre.

    Sert a ne payer les cotes qu'UNE fois par fenetre. Sans lui, le mardi
    signifierait 24 releves — signal.py tourne toutes les heures et
    should_fetch repondrait oui a chacune. La fenetre du dimanche matin est
    traitee comme un bloc unique de 9h a 12h.
    """
    d = when or now_et()
    go, _ = should_fetch(d)
    if not go:
        return None
    if d.weekday() == 6:
        return f"{d:%Y-%m-%d}|dimanche-matin"
    return f"{d:%Y-%m-%d}|{'mardi' if d.weekday() == 1 else 'vendredi'}"


def is_closing_window(when: datetime = None) -> bool:
    """Le run du dimanche matin sert aussi a figer les cotes de fermeture."""
    d = when or now_et()
    return d.weekday() == 6 and 9 <= d.hour < 12


def week_end(when: datetime = None) -> datetime:
    """
    Fin de la semaine NFL courante: le mardi suivant a 6h ET, ce qui englobe le
    jeudi, le dimanche et le lundi soir sans deborder sur la semaine d'apres.
    """
    d = when or now_et()
    days = (1 - d.weekday()) % 7 or 7
    nxt  = (d + timedelta(days=days)).replace(hour=6, minute=0, second=0, microsecond=0)
    return nxt


def in_current_week(commence: str, when: datetime = None) -> bool:
    """
    Le match tombe-t-il dans la semaine en cours ?

    L'API renvoie TOUS les matchs a venir: le premier run en a ramene 270, de
    septembre a janvier. Analyser la saison entiere n'a pas de sens ici — les
    lignes lointaines ne sont cotees que par un ou deux books, et on
    enregistrait des paris papier sur des matchs de decembre.
    """
    if not commence:
        return False
    try:
        k = datetime.fromisoformat(commence.replace("Z", "+00:00")) - timedelta(hours=4)
        k = k.replace(tzinfo=None)
    except ValueError:
        return False
    d = when or now_et()
    return d.replace(tzinfo=None) - timedelta(hours=6) <= k <= week_end(d).replace(tzinfo=None)


def week_label(when: datetime = None) -> str:
    """
    Identifiant de la semaine NFL: le mardi qui l'ouvre. Sert de cle pour ne
    pas melanger deux semaines dans le dashboard ni dans le tracking.
    """
    d = when or now_et()
    return (d - timedelta(days=(d.weekday() - 1) % 7)).strftime("%Y-%m-%d")


# ── Devig ───────────────────────────────────────────────────────────────────

def devig_pair(per_book: dict, side_a: str, side_b: str) -> dict:
    """
    Probabilites no-vig d'un marche a deux issues, a partir des cotes par book.

    `per_book` = {book: {issue: cote}}. Retourne
        {side_a: prob, side_b: prob, source, best: {issue: (cote, book)}}
    avec side_a + side_b = 1 par construction — on devigge DANS un book
    (Pinnacle en priorite, sinon la mediane des books qui cotent les deux
    faces), jamais entre deux books: melanger deux marges penche la
    probabilite vers le book le plus genereux et s'attribue l'ecart comme un
    edge.

    Les prix aberrants (carnet d'echange mince, cotation perimee) sont ecartes
    par odds_api.best_playable avant de choisir la meilleure cote.
    """
    books = [{"book": bk, "over_odds": pr.get(side_a), "under_odds": pr.get(side_b)}
             for bk, pr in per_book.items()]
    agg_a = odds_api.summarize_two_way([b for b in books if b["over_odds"]])
    if not agg_a["best_over_odds"]:
        return {}

    p_a = agg_a["baseline_prob"] / 100.0
    if not agg_a["n_novig"]:
        # Aucun book ne cote les deux faces: la prob brute contient la vig, on
        # ne peut pas produire une paire qui somme a 1 honnetement.
        return {}

    best, chez_moi = {}, {}
    for side in (side_a, side_b):
        prices = [(bk, pr.get(side)) for bk, pr in per_book.items() if pr.get(side)]
        odds, book, _drop = odds_api.best_playable(prices)
        if odds:
            best[side] = (odds, book)
        # Le prix chez MES books: un edge chez un book ou je n'ai pas de
        # compte n'est pas un edge, c'est une information.
        m_odds, m_book = odds_api.best_at_my_books(prices)
        if m_odds:
            chez_moi[side] = (m_odds, m_book)

    return {
        side_a:   round(p_a, 6),
        side_b:   round(1.0 - p_a, 6),
        "source": agg_a["baseline_source"],
        "n_books": agg_a["n_books"],
        "best":   best,
        "mine":   chez_moi,
    }


def ev_pct(prob: float, odds: float) -> float:
    """Esperance en % de la mise: prob x cote - 1."""
    return round((prob * odds - 1.0) * 100, 2)


# ── Lecture d'un evenement ──────────────────────────────────────────────────

def _collect(event: dict) -> dict:
    """
    Reorganise les cotes d'un evenement en {marche: {cle: {book: cote}}}.

    `cle` identifie une paire comparable: pour h2h le nom de l'equipe, pour
    spreads et totals le point (on ne compare jamais un -3 a un -3.5, ce sont
    deux paris differents).
    """
    out = {"h2h": {}, "spreads": {}, "totals": {}}
    for bm in event.get("bookmakers", []):
        book = bm.get("key", "")
        for mkt in bm.get("markets", []):
            key = mkt.get("key")
            if key not in out:
                continue
            for oc in mkt.get("outcomes", []):
                name  = oc.get("name", "")
                price = oc.get("price")
                point = oc.get("point")
                if not name or not price:
                    continue
                if key == "h2h":
                    out["h2h"].setdefault(book, {})[name] = price
                else:
                    if point is None:
                        continue
                    # Les deux faces d'un spread portent des points opposes
                    # (-3.5 et +3.5): on les regroupe sous la valeur absolue
                    # pour les apparier, en gardant le point signe de chaque
                    # equipe — c'est lui qui dit qui est favori.
                    grp = abs(float(point)) if key == "spreads" else float(point)
                    slot = out[key].setdefault(grp, {"prices": {}, "points": {}})
                    slot["prices"].setdefault(book, {})[name] = price
                    slot["points"][name] = float(point)
    return out


def analyze_event(event: dict, threshold: float = None) -> dict:
    """Signaux d'un match. Retourne {game, commence, signals: [...]}."""
    thr   = min_edge() if threshold is None else threshold
    home  = event.get("home_team", "")
    away  = event.get("away_team", "")
    data  = _collect(event)
    out   = {
        "event_id":  event.get("id", ""),
        "home_team": home,
        "away_team": away,
        "commence":  event.get("commence_time", ""),
        "signals":   [],
        "markets":   [],
        # Meilleur prix de CHAQUE issue, signal ou non. Indispensable pour la
        # cote de fermeture: un pari repere mardi n'est presque jamais encore
        # un signal le dimanche — l'ecart s'est referme, c'est le cas normal.
        # Sans ces prix, aucun pari papier n'aurait jamais de CLV.
        "prices":    {},
    }

    def consider(market_key, side_a, side_b, per_book, label_a, label_b, point=None):
        pair = devig_pair(per_book, side_a, side_b)
        if not pair:
            return
        out["markets"].append({
            "market": MARKET_KEYS[market_key], "point": point,
            "prob_a": round(pair[side_a] * 100, 2),
            "prob_b": round(pair[side_b] * 100, 2),
            "source": pair["source"], "n_books": pair["n_books"],
        })
        for side, label in ((side_a, label_a), (side_b, label_b)):
            if side not in pair["best"]:
                continue
            odds, book = pair["best"][side]
            ev = ev_pct(pair[side], odds)
            m_odds, m_book = pair["mine"].get(side, (0.0, ""))
            m_ev  = ev_pct(pair[side], m_odds) if m_odds else None
            out["prices"][label] = {
                "market": MARKET_KEYS[market_key], "odds": round(odds, 3),
                "book": book, "prob": round(pair[side] * 100, 2), "edge_pct": ev,
                "my_odds": round(m_odds, 3) if m_odds else 0,
                "my_book": m_book, "my_edge_pct": m_ev,
                "stake_units": (odds_api.kelly_units(pair[side] * 100, m_odds)
                                if m_odds else 0),
            }
            # Le seuil s'applique au prix JOUABLE quand on en a un; sinon au
            # meilleur du marche, en signalant que le pari n'est pas prenable.
            juge = m_ev if m_ev is not None else ev
            if juge >= thr and pair["n_books"] >= min_books():
                out["signals"].append({
                    "market":      MARKET_KEYS[market_key],
                    "selection":   label,
                    "point":       point,
                    "prob":        round(pair[side] * 100, 2),
                    "odds":        round(odds, 3),
                    "book":        book,
                    "edge_pct":    ev,
                    "my_odds":     round(m_odds, 3) if m_odds else 0,
                    "my_book":     m_book,
                    "my_edge_pct": m_ev,
                    "playable":    bool(m_odds),
                    # Ce qu'il faut exiger chez son propre book, qui n'est pas
                    # forcement dans le flux: en dessous du prix juste on parie
                    # a perte, en dessous de la cible on n'a pas le seuil.
                    "min_odds":    odds_api.min_odds_for(pair[side] * 100, 0),
                    "target_odds": odds_api.min_odds_for(pair[side] * 100, thr),
                    "stake_units": (odds_api.kelly_units(pair[side] * 100, m_odds)
                                    if m_odds else 0),
                    "fair_odds":   round(1.0 / pair[side], 3) if pair[side] > 0 else 0,
                    "source":      pair["source"],
                    "n_books":     pair["n_books"],
                })

    # Moneyline
    if data["h2h"]:
        consider("h2h", home, away, data["h2h"], f"{home} ML", f"{away} ML")

    # Spreads: une paire par valeur de point, le libelle reprend le point signe
    # de chaque equipe (le favori porte le point negatif).
    for grp, slot in sorted(data["spreads"].items()):
        pts = slot["points"]
        if len(pts) != 2:
            continue
        a, b = (home, away) if {home, away} == set(pts) else tuple(sorted(pts))
        consider("spreads", a, b, slot["prices"],
                 f"{a} {pts.get(a, 0):+g}", f"{b} {pts.get(b, 0):+g}", point=grp)

    # Totals
    for point, slot in sorted(data["totals"].items()):
        consider("totals", "Over", "Under", slot["prices"],
                 f"Over {point:g}", f"Under {point:g}", point=point)

    out["signals"].sort(key=lambda s: -s["edge_pct"])
    return out


# ── Persistance ─────────────────────────────────────────────────────────────

def load_signals() -> dict:
    """
    Dernier etat connu. Le dashboard s'en sert les jours ou on ne paie pas de
    cotes: mieux vaut afficher les signaux de mardi avec leur horodatage que
    de vider l'onglet quatre jours sur sept.
    """
    try:
        with open(signals_path(), "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_signals(state: dict) -> None:
    p = signals_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


# ── Tracking papier ─────────────────────────────────────────────────────────

def log_paper_bets(games: list, week: str) -> int:
    """
    Enregistre chaque signal comme pari PAPIER dans le tracker (1 unite, la
    meilleure cote, `paper=True`).

    Sans modele maison, ces signaux ne sont pas des recommandations: ils
    servent a mesurer si le shopping entre books produit du CLV. Les noter en
    papier permet de le savoir dans quelques semaines sans risquer un dollar.

    Idempotent: un meme signal repere mardi puis revendredi n'est enregistre
    qu'une fois, a son premier prix. C'est voulu — le CLV se mesure contre le
    prix qu'on aurait pris, pas contre le dernier vu.
    """
    import bet_tracker as bt

    existing = {b.get("id") for b in bt.load().get("bets", [])}
    added = 0
    for g in games:
        for sig in g.get("signals", []):
            bet_id = f"{week}|nfl|{sig['market']}|{sig['selection']}"
            if bet_id in existing:
                continue
            try:
                bt.add_bet(
                    date=week, sport="nfl", market=sig["market"],
                    selection=sig["selection"], model_prob=sig["prob"],
                    odds_taken=sig["odds"], book=sig["book"], stake=1.0,
                    paper=True,
                    note=(f"top-down {sig['edge_pct']:+.1f}% vs {sig['source']} "
                          f"({sig['n_books']} books) — {g['away_team']} @ {g['home_team']}"),
                )
                existing.add(bet_id)
                added += 1
            except ValueError as e:
                print(f"  [NFL] signal non enregistre ({sig['selection']}): {e}")
    return added


def capture_closing(games: list, week: str) -> int:
    """
    Fige la cote de fermeture des paris papier de la semaine, au run du
    dimanche matin. C'est ce qui rend le CLV calculable: sans elle, un pari
    papier ne dit rien du tout.
    """
    import bet_tracker as bt

    data  = bt.load()
    index = {b.get("id"): b for b in data.get("bets", [])}
    # On lit `prices`, pas `signals`: le pari a fermer n'est generalement plus
    # un signal au moment de la fermeture.
    now   = {}
    for g in games:
        for label, px in (g.get("prices") or {}).items():
            now[f"{week}|nfl|{px['market']}|{label}"] = px["odds"]

    n = 0
    for bet_id, odds in now.items():
        bet = index.get(bet_id)
        if bet is None or bet.get("closing_odds"):
            continue
        try:
            bt.close_bet(bet_id, closing_odds=odds)
            n += 1
        except (KeyError, ValueError):
            continue
    return n


# ── Point d'entree ──────────────────────────────────────────────────────────

def run(api_key: str = None, force: bool = False,
        props_within: float = None) -> dict:
    """
    Produit l'etat NFL pour le dashboard.

    Hors des trois fenetres hebdomadaires, aucune requete n'est faite: on
    renvoie le dernier etat connu, marque comme tel. `force=True` court-circuite
    la cadence (utile en local et pour un declenchement manuel).
    """
    when = now_et()
    go, motif = (True, "force") if force else should_fetch(when)
    week = week_label(when)
    wid  = "force-" + when.strftime("%Y-%m-%dT%H") if force else window_id(when)

    if not go:
        state = load_signals()
        state["stale"] = True
        state["reason"] = motif
        try:
            import nfl_props
            state["props"] = {**nfl_props.load_props(), "stale": True}
        except Exception:
            pass
        print(f"  [NFL] {motif} — aucun credit depense, dernier etat conserve")
        return state

    cached = load_signals()
    if not force and cached.get("window_id") == wid:
        # Deja releve dans cette fenetre. signal.py tourne toutes les heures:
        # sans ce garde-fou, un mardi coute 24 releves au lieu d'une.
        cached["stale"] = False
        cached["reason"] = motif + " (deja releve dans cette fenetre)"
        print(f"  [NFL] {motif}: releve deja faite, aucun credit depense")
        return cached

    client = odds_api.get_client(api_key)
    if not client.healthy:
        state = load_signals()
        state["stale"] = True
        state["reason"] = "cotes indisponibles (cle ou quota)"
        return state

    cost = len(MARKETS) * max(len(
        [r for r in odds_api.regions().split(",") if r.strip()]), 1)
    data = client.get(f"sports/{SPORT}/odds", {
        "regions":    odds_api.regions(),
        "markets":    ",".join(MARKETS),
        "oddsFormat": "decimal",
    }, cost=cost)

    if not data:
        state = load_signals()
        state["stale"] = True
        state["reason"] = "aucune reponse de l'API"
        return state

    horizon = [ev for ev in data if in_current_week(ev.get("commence_time", ""), when)]
    games = [analyze_event(ev) for ev in horizon]
    games = [g for g in games if g.get("markets")]
    if len(data) != len(horizon):
        print(f"  [NFL] {len(data)} match(s) renvoyes par l'API, "
              f"{len(horizon)} dans la semaine en cours")
    games.sort(key=lambda g: (-(g["signals"][0]["edge_pct"] if g["signals"] else -99),
                              g.get("commence", "")))
    n_sig = sum(len(g["signals"]) for g in games)

    state = {
        "week":         week,
        "window_id":    wid,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reason":       motif,
        "stale":        False,
        "min_edge":     min_edge(),
        "min_books":    min_books(),
        "n_games":      len(games),
        "n_signals":    n_sig,
        "games":        games,
    }

    try:
        state["paper_logged"] = log_paper_bets(games, week)
        if is_closing_window(when) and not force:
            state["closing_captured"] = capture_closing(games, week)
    except Exception as e:
        print(f"  [NFL] tracking papier indisponible: {e}")

    # Props joueurs: une seule fenetre par semaine, le dimanche matin. Importe
    # ici et non en tete de fichier — nfl_props importe ce module.
    try:
        import nfl_props
        if force or nfl_props.should_run(when)[0]:
            state["props"] = nfl_props.run(api_key, state, force=force,
                                           within_hours=props_within)
        else:
            state["props"] = nfl_props.load_props()
            state["props"]["stale"] = True
    except Exception as e:
        print(f"  [Props NFL] erreur: {e}")
        try:
            import nfl_props
            state["props"] = nfl_props.load_props()
        except Exception:
            state["props"] = {}

    save_signals(state)
    print(f"  [NFL] {motif}: {len(games)} match(s), {n_sig} signal(aux) "
          f"au-dessus de {min_edge()}% "
          f"({state.get('paper_logged', 0)} nouveau(x) en papier)")
    return state
