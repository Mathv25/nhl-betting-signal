"""
Props joueurs NFL — signaux top-down, sous plafond de requetes.

La contrainte qui commande tout est le quota. Sur The Odds API, les props se
lisent sur l'endpoint evenement: UNE requete par match et par marche. Trois
marches sur seize matchs feraient 48 requetes pour une seule semaine, a
repeter chaque semaine, en concurrence avec le MLB et le NHL qui jouent tous
les jours. D'ou trois garde-fous cumulatifs:

  1. un plafond hebdomadaire dur (NFL_PROPS_MAX_REQUESTS, defaut 40), compte
     dans docs/odds_usage.json et donc partage entre les executions;
  2. une selection des matchs: seuls ceux dont le total depasse
     NFL_PROPS_MIN_TOTAL (defaut 47) sont scannes, six au maximum — les matchs
     a haut pointage concentrent le volume de verges, donc la valeur;
  3. une seule fenetre par semaine, le dimanche matin. Les lignes d'ouverture
     du mardi sont larges et bougent trop pour qu'un ecart y veuille dire
     quelque chose.

Le total de chaque match vient du releve de slate deja fait par nfl_analyzer:
il ne coute aucune requete supplementaire.

Methode identique au module principal: probabilite no-vig par book, Pinnacle
en reference sinon la mediane, signal quand la meilleure cote d'un autre book
bat cette reference d'au moins NFL_PROPS_MIN_EDGE.

S'y ajoute un second type de signal propre aux props: l'ECART DE LIGNE. Quand
un book affiche 67.5 verges et un autre 72.5, on peut prendre le Over a 67.5
et le Under a 72.5; tout resultat strictement compris entre les deux fait
gagner les deux paris. C'est un middle, et il ne se voit pas dans les
probabilites — seulement en comparant les lignes.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import odds_api
import nfl_analyzer as NFL

SPORT = "americanfootball_nfl"

# Ordre de priorite: si le budget serre, on scanne les premiers d'abord.
# Pas de "anytime TD" en v1: variance elevee, marge enorme, et une probabilite
# no-vig y est trop bruitee pour qu'un ecart de 3% veuille dire quoi que ce soit.
MARKETS = ["player_reception_yds", "player_rush_yds", "player_pass_yds"]

MARKET_LABELS = {
    "player_reception_yds": "verges de reception",
    "player_rush_yds":      "verges au sol",
    "player_pass_yds":      "verges de passe",
}


def max_requests() -> int:
    """Plafond DUR de requetes props par semaine."""
    try:
        return int(os.environ.get("NFL_PROPS_MAX_REQUESTS", "") or 40)
    except ValueError:
        return 40


def min_total() -> float:
    """Total (over/under) minimal d'un match pour qu'on scanne ses props."""
    try:
        return float(os.environ.get("NFL_PROPS_MIN_TOTAL", "") or 47.0)
    except ValueError:
        return 47.0


def max_games() -> int:
    try:
        return int(os.environ.get("NFL_PROPS_MAX_GAMES", "") or 6)
    except ValueError:
        return 6


def min_edge() -> float:
    try:
        return float(os.environ.get("NFL_PROPS_MIN_EDGE", "") or 3.0)
    except ValueError:
        return 3.0


def min_middle() -> float:
    """
    Fenetre minimale d'un middle, dans l'unite du marche (des verges ici).

    Une fenetre d'une verge demande au resultat de tomber exactement dessus.
    Sur le premier releve reel, la moitie des middles detectes etaient a une
    verge — vrais au sens ou les deux books divergent, mais sous le seuil de
    rentabilite une fois la marge payee des deux cotes.
    """
    try:
        return float(os.environ.get("NFL_PROPS_MIN_MIDDLE", "") or 2.0)
    except ValueError:
        return 2.0


def middle_breakeven(over_odds: float, under_odds: float) -> float:
    """
    Frequence a laquelle le resultat doit tomber DANS la fenetre pour que le
    middle soit rentable, en %.

    Une unite de chaque cote. Si le resultat tombe dans la fenetre, les deux
    paris gagnent: (cote_over - 1) + (cote_under - 1). Sinon un gagne et
    l'autre perd, ce qui laisse la difference — negative des que les deux cotes
    sont sous 2.00, c'est-a-dire toujours.

    On prend le pire des deux cas a un seul gagnant: annoncer la moyenne
    flatterait le pari.

    Ce chiffre se calcule sur les prix seuls. La probabilite REELLE que le
    resultat tombe dans la fenetre, elle, demanderait un modele de distribution
    des verges qu'on n'a pas — c'est au lecteur de juger, et c'est dit.
    """
    gain  = (over_odds - 1.0) + (under_odds - 1.0)
    perte = min(over_odds, under_odds) - 2.0      # negatif
    if gain <= perte:
        return 100.0
    return round(-perte / (gain - perte) * 100, 2)


def min_books() -> int:
    """Comme pour les marches principaux: deux books ne font pas un consensus."""
    try:
        return int(os.environ.get("NFL_PROPS_MIN_BOOKS", "") or 3)
    except ValueError:
        return 3


def should_run(when: datetime = None) -> tuple:
    """
    Une seule fenetre par semaine: le dimanche matin, quand les lignes sont
    mures et les blessures connues. Retourne (bool, motif).
    """
    d = when or NFL.now_et()
    if d.weekday() == 6 and 9 <= d.hour < 12:
        return True, "dimanche matin — lignes mures"
    return False, f"hors fenetre props NFL ({d:%A %Hh} ET)"


# ── Compteur hebdomadaire ───────────────────────────────────────────────────

def counter(client, week: str) -> dict:
    """
    Compteur de requetes props de la semaine, loge dans odds_usage.json pour
    survivre aux executions (en CI le disque est neuf a chaque run, le depot
    non). Repart a zero quand la semaine change.
    """
    st = client.usage()
    c  = st.get("nfl_props") or {}
    if c.get("week") != week:
        c = {"week": week, "requests": 0}
        st["nfl_props"] = c
    return c


def remaining_requests(client, week: str) -> int:
    return max(max_requests() - counter(client, week).get("requests", 0), 0)


# ── Selection des matchs ────────────────────────────────────────────────────

def game_total(game: dict):
    """
    Total du match, lu dans le releve de slate deja effectue. Quand plusieurs
    lignes de total existent (44 et 44.5), on prend celle qu'appuient le plus
    de books: c'est la ligne principale du marche.
    """
    totaux = [m for m in (game.get("markets") or [])
              if m.get("market") == "nfl_total" and m.get("point") is not None]
    if not totaux:
        return None
    return float(max(totaux, key=lambda m: m.get("n_books", 0))["point"])


def kickoff_in_hours(commence: str, when: datetime = None):
    """Heures avant le coup d'envoi; negatif si le match a commence."""
    if not commence:
        return None
    try:
        k = datetime.fromisoformat(commence.replace("Z", "+00:00"))
    except ValueError:
        return None
    ref = (when or NFL.now_et()).replace(tzinfo=None) + timedelta(hours=4)
    return (k.replace(tzinfo=None) - ref).total_seconds() / 3600.0


def select_games(games: list, within_hours: float = None,
                 when: datetime = None) -> list:
    """
    Matchs dont les props valent une requete: total au-dessus du seuil, les
    plus hauts d'abord, dans la limite de max_games.

    `within_hours` restreint aux matchs qui commencent bientot. C'est le mode
    des matchs de semaine: un jeudi soir ne tombe dans aucune fenetre
    hebdomadaire, et scanner tout le calendrier pour lui depenserait des
    requetes sur des lignes de dimanche encore immatures.
    """
    avec = []
    for g in games or []:
        t = game_total(g)
        if t is None or t < min_total() or not g.get("event_id"):
            continue
        if within_hours is not None:
            h = kickoff_in_hours(g.get("commence", ""), when)
            if h is None or not (-2.0 <= h <= within_hours):
                continue
        avec.append((t, g))
    avec.sort(key=lambda x: -x[0])
    return [{**g, "_total": t} for t, g in avec[:max_games()]]


# ── Lecture d'un marche de props ────────────────────────────────────────────

def parse_market(data: dict, market: str) -> dict:
    """
    Reorganise la reponse en {joueur: {ligne: {book: {"Over": cote, "Under": cote}}}}.

    Les lignes sont conservees separement: un Over 67.5 et un Over 72.5 ne sont
    pas le meme pari, et c'est justement leur ecart qui revele un middle.
    """
    out: dict = {}
    for bm in (data or {}).get("bookmakers", []):
        book = bm.get("key", "")
        for mkt in bm.get("markets", []):
            if mkt.get("key") != market:
                continue
            for oc in mkt.get("outcomes", []):
                joueur = (oc.get("description") or "").strip()
                side   = oc.get("name", "")
                price  = oc.get("price")
                point  = oc.get("point")
                if not joueur or side not in ("Over", "Under") or not price or point is None:
                    continue
                out.setdefault(joueur, {}).setdefault(float(point), {}) \
                   .setdefault(book, {})[side] = float(price)
    return out


def analyze_player(joueur: str, par_ligne: dict, market: str,
                   game: dict, threshold: float = None) -> list:
    """
    Signaux d'un joueur sur un marche. Deux natures distinctes:

      "cote"  — a ligne egale, un book paie mieux que la reference no-vig;
      "ligne" — deux books n'affichent pas la meme ligne, ce qui ouvre un
                middle. Ce signal-la n'apparait dans aucune probabilite.
    """
    thr  = min_edge() if threshold is None else threshold
    sigs = []

    # Detail par book, joint a chaque signal: sans lui le dashboard ne peut pas
    # montrer OU sont les lignes, ce qui est la moitie de l'information sur un
    # marche de props (deux books peuvent afficher deux lignes differentes).
    detail = sorted(
        ({"book": bk, "ligne": lg, "over": c.get("Over"), "under": c.get("Under")}
         for lg, par_book in par_ligne.items() for bk, c in par_book.items()),
        key=lambda d: (d["ligne"], d["book"]))

    # ── Ecarts de cote, ligne par ligne ─────────────────────────────────────
    for ligne, par_book in sorted(par_ligne.items()):
        pair = NFL.devig_pair(
            {bk: {"Over": c.get("Over"), "Under": c.get("Under")}
             for bk, c in par_book.items()},
            "Over", "Under")
        if not pair or pair["n_books"] < min_books():
            continue
        for side in ("Over", "Under"):
            if side not in pair["best"]:
                continue
            odds, book = pair["best"][side]
            ev = NFL.ev_pct(pair[side], odds)
            if ev >= thr:
                sigs.append({
                    "type":      "cote",
                    "joueur":    joueur,
                    "market":    market,
                    "marche_lbl": MARKET_LABELS.get(market, market),
                    "selection": f"{joueur} {side} {ligne:g}",
                    "side":      side,
                    "ligne":     ligne,
                    "prob":      round(pair[side] * 100, 2),
                    "odds":      round(odds, 3),
                    "book":      book,
                    "fair_odds": round(1.0 / pair[side], 3) if pair[side] > 0 else 0,
                    "min_odds":    odds_api.min_odds_for(pair[side] * 100, 0),
                    "target_odds": odds_api.min_odds_for(pair[side] * 100, thr),
                    "my_odds":     odds_api.best_at_my_books(
                        [(bk, c.get(side)) for bk, c in par_book.items()])[0],
                    "edge_pct":  ev,
                    "source":    pair["source"],
                    "n_books":   pair["n_books"],
                    "game":      f"{game.get('away_team','')} @ {game.get('home_team','')}",
                    "commence":  game.get("commence", ""),
                    "books":     detail,
                })

    # ── Ecart de ligne (middle) ─────────────────────────────────────────────
    # Un middle suppose que DEUX books ne voient pas le match pareil. Deux
    # pieges ecartes ici, vus sur des donnees reelles:
    #
    #   1. Un seul book des deux cotes n'est jamais un middle. Bovada publie
    #      une echelle de lignes alternatives (232.5, 242.5, ... 292.5) dont
    #      chaque barreau est correctement cote; prendre ses deux extremites
    #      fabriquait une "fenetre de 60 verges" qui n'existe pas — le book
    #      accepte volontiers les deux cotes a ces prix.
    #   2. Meme entre deux books, comparer un barreau d'echelle a une ligne
    #      principale revient au meme. On ne retient donc de chaque book que
    #      sa ligne PRINCIPALE: celle qu'il cote le plus pres du consensus.
    #
    # Sur le meme match, cette regle ramene la fenetre annoncee de 60 verges
    # fictives a l'ecart reel entre books: 258.5 chez l'un, 263.5 chez l'autre.
    lignes_par_book = {}
    for ligne, par_book in par_ligne.items():
        for bk, c in par_book.items():
            lignes_par_book.setdefault(bk, []).append((ligne, c))

    compte = {}
    for ligne, par_book in par_ligne.items():
        compte[ligne] = len(par_book)
    consensus = max(compte, key=lambda l: (compte[l], -abs(l)))

    principales = {}
    for bk, offres in lignes_par_book.items():
        ligne, c = min(offres, key=lambda x: abs(x[0] - consensus))
        principales[bk] = (ligne, c)

    meilleur_over = meilleur_under = None
    for bk, (ligne, c) in principales.items():
        if c.get("Over") and (meilleur_over is None or ligne < meilleur_over[0]):
            meilleur_over = (ligne, c["Over"], bk)
        if c.get("Under") and (meilleur_under is None or ligne > meilleur_under[0]):
            meilleur_under = (ligne, c["Under"], bk)

    if (meilleur_over and meilleur_under
            and meilleur_under[0] - meilleur_over[0] >= min_middle()
            and meilleur_under[2] != meilleur_over[2]):
        lo, o_odds, o_book = meilleur_over
        hi, u_odds, u_book = meilleur_under
        sigs.append({
            "type":       "ligne",
            "joueur":     joueur,
            "market":     market,
            "marche_lbl": MARKET_LABELS.get(market, market),
            "selection":  f"{joueur} middle {lo:g}-{hi:g}",
            "ligne":      lo,
            "ligne_haute": hi,
            "fenetre":    round(hi - lo, 1),
            "over":       {"ligne": lo, "odds": round(o_odds, 3), "book": o_book},
            "under":      {"ligne": hi, "odds": round(u_odds, 3), "book": u_book},
            "consensus":  consensus,
            "breakeven":  middle_breakeven(o_odds, u_odds),
            "odds":       round(o_odds, 3),
            "book":       o_book,
            "edge_pct":   0.0,
            "game":       f"{game.get('away_team','')} @ {game.get('home_team','')}",
            "commence":   game.get("commence", ""),
            "books":      detail,
        })
    return sigs


# ── Execution ───────────────────────────────────────────────────────────────

def fetch_market(client, event_id: str, market: str) -> dict:
    """Une requete: un match, un marche. C'est l'unite que le plafond compte."""
    return client.get(f"sports/{SPORT}/events/{event_id}/odds", {
        "regions":    odds_api.regions(),
        "markets":    market,
        "oddsFormat": "decimal",
    }, cost=odds_api.COST_PER_MARKET_REGION_PROP)


def run(api_key: str = None, slate: dict = None, force: bool = False,
        within_hours: float = None) -> dict:
    """
    Releve des props de la semaine.

    `slate` est l'etat produit par nfl_analyzer (matchs et totaux): on s'en
    sert pour choisir les matchs sans depenser une requete de plus.
    """
    when = NFL.now_et()
    go, motif = (True, "force") if force else should_run(when)
    week = NFL.week_label(when)

    if not go:
        etat = load_props()
        etat["stale"] = True
        etat["reason"] = motif
        return etat

    games = select_games((slate or {}).get("games") or [], within_hours, when)
    if within_hours is not None:
        print(f"  [Props NFL] restreint aux matchs des {within_hours:g} prochaines heures")
    client = odds_api.get_client(api_key)
    if not client.healthy:
        etat = load_props()
        etat["stale"] = True
        etat["reason"] = "cotes indisponibles (cle ou quota)"
        return etat

    compteur = counter(client, week)
    budget   = remaining_requests(client, week)
    print(f"  [Props NFL] {len(games)} match(s) au-dessus de {min_total():g} points, "
          f"{budget}/{max_requests()} requete(s) restantes cette semaine")

    signaux, scannes, demandes = [], [], 0
    # Marche par marche plutot que match par match: si le budget s'epuise, il
    # reste couvert en priorite le marche le plus haut de la liste sur tous les
    # matchs, plutot qu'un seul match couvert sur trois marches.
    for market in MARKETS:
        for g in games:
            if demandes >= budget:
                break
            data = fetch_market(client, g["event_id"], market)
            demandes += 1
            compteur["requests"] = compteur.get("requests", 0) + 1
            if not data:
                continue
            joueurs = parse_market(data, market)
            if joueurs and g["event_id"] not in scannes:
                scannes.append(g["event_id"])
            for joueur, par_ligne in joueurs.items():
                signaux.extend(analyze_player(joueur, par_ligne, market, g))
        if demandes >= budget:
            print(f"  [Props NFL] plafond hebdomadaire atteint apres {market}")
            break

    signaux.sort(key=lambda s: (-s.get("edge_pct", 0), -s.get("fenetre", 0)))

    etat = {
        "week":         week,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reason":       motif,
        "stale":        False,
        "min_edge":     min_edge(),
        "min_total":    min_total(),
        "min_books":    min_books(),
        "n_games":      len(games),
        "within_hours": within_hours,
        "n_scanned":    len(scannes),
        "requests":     demandes,
        "requests_week": compteur.get("requests", 0),
        "max_requests": max_requests(),
        "games":        [{"event_id": g["event_id"],
                          "game": f"{g.get('away_team','')} @ {g.get('home_team','')}",
                          "total": g.get("_total"),
                          "commence": g.get("commence", "")} for g in games],
        "signals":      signaux,
        "n_signals":    len(signaux),
    }

    try:
        etat["paper_logged"] = log_paper(signaux, week)
        etat["closing_captured"] = capture_closing(signaux, week)
    except Exception as e:
        print(f"  [Props NFL] tracking papier indisponible: {e}")

    save_props(etat)
    client.persist_usage()
    print(f"  [Props NFL] {len(signaux)} signal(aux) sur {len(scannes)} match(s) scanne(s), "
          f"{demandes} requete(s) — {compteur.get('requests', 0)}/{max_requests()} cette semaine")
    return etat


# ── Persistance ─────────────────────────────────────────────────────────────

def props_path() -> str:
    return os.environ.get("NFL_PROPS_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "docs", "nfl_props.json")


def load_props() -> dict:
    import json
    try:
        with open(props_path(), "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def save_props(etat: dict) -> None:
    import json
    p = props_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


# ── Tracking papier ─────────────────────────────────────────────────────────

def bet_id(week: str, sig: dict) -> str:
    return f"{week}|nfl|nfl_prop_{sig['market'].replace('player_', '')}|{sig['selection']}"


def log_paper(signaux: list, week: str) -> int:
    """
    Enregistre chaque signal en papier. Les middles sont exclus: ce sont deux
    paris a deux prix chez deux books, que le tracker — concu pour un pari, une
    cote — representerait mal. Ils restent affiches au dashboard.
    """
    import bet_tracker as bt

    existants = {b.get("id") for b in bt.load().get("bets", [])}
    n = 0
    for sig in signaux:
        if sig.get("type") != "cote":
            continue
        bid = bet_id(week, sig)
        if bid in existants:
            continue
        try:
            bt.add_bet(
                date=week, sport="nfl",
                market="nfl_prop_" + sig["market"].replace("player_", ""),
                selection=sig["selection"], model_prob=sig["prob"],
                odds_taken=sig["odds"], book=sig["book"], stake=1.0, paper=True,
                note=(f"top-down {sig['edge_pct']:+.1f}% vs {sig['source']} "
                      f"({sig['n_books']} books) — {sig['game']}"),
            )
            existants.add(bid)
            n += 1
        except ValueError as e:
            print(f"  [Props NFL] non enregistre ({sig['selection']}): {e}")
    return n


def capture_closing(signaux: list, week: str) -> int:
    """
    Fige la cote de fermeture au meme run. Le releve etant hebdomadaire, la
    prise et la fermeture coincident souvent; le CLV mesure alors le mouvement
    d'un book a l'autre plutot que dans le temps. Un pari deja ferme n'est
    jamais reecrit, donc un run ulterieur peut completer ce qui manquait.
    """
    import bet_tracker as bt

    index = {b.get("id"): b for b in bt.load().get("bets", [])}
    n = 0
    for sig in signaux:
        if sig.get("type") != "cote":
            continue
        bet = index.get(bet_id(week, sig))
        if bet is None or bet.get("closing_odds"):
            continue
        try:
            bt.close_bet(bet["id"], closing_odds=sig["odds"])
            n += 1
        except (KeyError, ValueError):
            continue
    return n
