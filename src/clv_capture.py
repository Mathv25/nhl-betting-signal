"""
CLV Capture — Closing Line Value
Capte les cotes "de fermeture" (juste avant les matchs) pour chaque bet en attente.
Stocke closing_implied dans results.json pour permettre le calcul du CLV.

CLV = opening_implied - closing_implied
  > 0 : le marché a bougé dans notre sens (sharps d'accord avec nous) — vrai edge
  < 0 : le marché nous a fadés — notre modèle était wrong

Se lance via GitHub Actions à 23h00 UTC (7pm ET) avant les matchs.
"""

import json, os, sys, time, requests
from datetime import datetime, timezone

import odds_api

RESULTS_PATH = os.path.join(os.path.dirname(__file__), "../docs/results.json")
SIGNAL_PATH  = os.path.join(os.path.dirname(__file__), "../docs/signal.json")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

HEADERS = {"User-Agent": "Mozilla/5.0"}

# Mapping sport → clé The Odds API
SPORT_KEYS = {
    "nhl": "icehockey_nhl",
    "nba": "basketball_nba",
    "mlb": "baseball_mlb",
}

# Mapping stat_key → market The Odds API (props)
MARKET_MAP = {
    # NHL
    "shots":  "player_shots_on_goal",
    "points": "player_points",
    "goals":  "player_goal_scorer_anytime",
    # NBA
    "pts":  "player_points",
    "reb":  "player_rebounds",
    "ast":  "player_assists",
    "pra":  "player_points_rebounds_assists",
    # MLB
    "strikeouts":  "pitcher_strikeouts",
    "hits":        "batter_hits",
    "total_bases": "batter_total_bases",
    "home_runs":   "batter_home_runs",
}


def _n_regions() -> int:
    return max(len([r for r in odds_api.regions().split(",") if r.strip()]), 1)


def prop_closing_index(client, sport_key: str, event_id: str, market_key: str) -> dict:
    """
    Cotes de fermeture d'UN marche de props sur UN match, tous books confondus.

    Retourne {joueur_minuscule: {ligne: {novig, brute, cote, book, source}}}.

    Pourquoi un index et non un appel par bet: l'endpoint event coute 10 credits
    par (marche x region). L'ancienne version appelait une fois PAR BET, donc
    trois lanceurs du meme match coutaient trois fois le meme appel — 500
    credits/mois partaient en quelques jours. Ici un seul appel sert tous les
    bets du match, et le cache du client partage le rend gratuit si un autre
    module l'a deja demande dans la meme execution.
    """
    cost = odds_api.COST_PER_MARKET_REGION_PROP * _n_regions()
    data = client.get(f"sports/{sport_key}/events/{event_id}/odds", {
        "regions":    odds_api.regions(),
        "markets":    market_key,
        "oddsFormat": "decimal",
    }, cost=cost)
    if not data:
        return {}

    by_key = {}     # (joueur, ligne) -> [{book, over_odds, under_odds}]
    for bm in data.get("bookmakers", []):
        book  = bm.get("key", "")
        sides = {}
        for mkt in bm.get("markets", []):
            if mkt.get("key") != market_key:
                continue
            for oc in mkt.get("outcomes", []):
                player = oc.get("description", "")
                side   = oc.get("name", "")
                price  = oc.get("price")
                line   = oc.get("point")
                if not player or not side or not price:
                    continue
                sides.setdefault((player.lower().strip(), line), {})[side] = price
        for key, faces in sides.items():
            if "Over" not in faces:
                continue
            by_key.setdefault(key, []).append({
                "book":       book,
                "over_odds":  faces.get("Over"),
                "under_odds": faces.get("Under"),
            })

    out = {}
    for (player, line), books in by_key.items():
        agg = odds_api.summarize_two_way(books)
        if not agg["best_over_odds"]:
            continue
        out.setdefault(player, {})[line] = {
            "novig":  agg["baseline_prob"] if agg["n_novig"] else None,
            "brute":  round(odds_api.implied(agg["best_over_odds"]) * 100, 2),
            "cote":   agg["best_over_odds"],
            "book":   agg["best_over_book"],
            "source": agg["baseline_source"],
        }
    return out


def h2h_closing_index(client, sport_key: str) -> dict:
    """
    Cotes de fermeture moneyline de TOUT le calendrier, en un seul appel.

    Retourne {(away, home): {equipe: {novig, brute, cote, book, source}}}.

    L'endpoint /sports/{sport}/odds coute 1 credit par (marche x region), pas
    10: un slate complet de moneylines coute donc 1 ou 2 credits au total. Le
    devig se fait DANS un book (Pinnacle en priorite), jamais entre deux books.
    """
    cost = 1 * _n_regions()
    data = client.get(f"sports/{sport_key}/odds", {
        "regions":    odds_api.regions(),
        "markets":    "h2h",
        "oddsFormat": "decimal",
    }, cost=cost)
    if not data:
        return {}

    out = {}
    for event in data:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        if not home or not away:
            continue
        per_book = {}
        for bm in event.get("bookmakers", []):
            book = bm.get("key", "")
            for mkt in bm.get("markets", []):
                if mkt.get("key") != "h2h":
                    continue
                for oc in mkt.get("outcomes", []):
                    if oc.get("name") and oc.get("price"):
                        per_book.setdefault(book, {})[oc["name"]] = oc["price"]

        entry = {}
        for team, other in ((home, away), (away, home)):
            books = [{"book": bk, "over_odds": pr.get(team), "under_odds": pr.get(other)}
                     for bk, pr in per_book.items() if pr.get(team)]
            agg = odds_api.summarize_two_way(books)
            if not agg["best_over_odds"]:
                continue
            entry[team] = {
                "novig":  agg["baseline_prob"] if agg["n_novig"] else None,
                "brute":  round(odds_api.implied(agg["best_over_odds"]) * 100, 2),
                "cote":   agg["best_over_odds"],
                "book":   agg["best_over_book"],
                "source": agg["baseline_source"],
            }
        if entry:
            out[(away.lower(), home.lower())] = entry
    return out


def _match_player(index: dict, player_name: str) -> dict:
    """Retrouve un joueur dans l'index malgre les variantes de nom."""
    p = (player_name or "").lower().strip()
    if not p:
        return {}
    if p in index:
        return index[p]
    for name, lines in index.items():
        if p in name or name in p:
            return lines
    # Dernier recours: nom de famille, si non ambigu.
    last = p.split()[-1] if p.split() else ""
    if len(last) >= 4:
        hits = [lines for name, lines in index.items() if name.split()[-1:] == [last]]
        if len(hits) == 1:
            return hits[0]
    return {}


def _pick_line(lines: dict, want_line):
    """Cote de fermeture a la ligne du bet; sinon la ligne la plus proche."""
    if not lines:
        return None
    try:
        want = float(want_line)
    except (TypeError, ValueError):
        want = None
    if want is not None:
        for ln, v in lines.items():
            if ln is not None and abs(float(ln) - want) < 0.01:
                return v
        # La ligne a bouge (ex: 5.5 -> 6.5): la fermeture d'une AUTRE ligne
        # n'est pas comparable a notre ouverture, on ne l'utilise pas.
        return None
    return next(iter(lines.values()), None)


def capture_clv(api_key: str, target_date: str = None):
    """
    Pour chaque bet en attente (result == '?') du jour cible, capte la cote de
    fermeture et stocke closing_implied / clv.

    Deux principes, appris de la panne precedente (0 CLV capte sur 1267 bets):

      1. Le CLV compare deux probabilites de la MEME base. L'ouverture d'un
         prop passe maintenant par un devig no-vig, celle d'un moneyline reste
         brute (1/cote). On enregistre les deux fermetures et on soustrait
         celle qui correspond, via `opening_basis`.
      2. Un appel par (match x marche), pas un par bet. Voir prop_closing_index.
    """
    if not target_date:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"\n{'='*55}")
    print(f"CLV CAPTURE — {target_date}")
    print(f"{'='*55}")

    # Charger results
    if not os.path.exists(RESULTS_PATH):
        print("Aucun results.json trouvé.")
        return

    with open(RESULTS_PATH) as f:
        results = json.load(f)

    pending = [
        b for b in results["bets"]
        if b.get("date") == target_date and b.get("result") == "?"
    ]

    if not pending:
        print(f"Aucun bet en attente pour {target_date}.")
        return

    print(f"{len(pending)} bets en attente — capture CLV...")

    # Charger le signal pour trouver les event_ids
    signal = {}
    if os.path.exists(SIGNAL_PATH):
        with open(SIGNAL_PATH) as f:
            signal = json.load(f)

    # Index "away @ home" (minuscules) -> (sport, event_id).
    # mlb_ml_analysis est inclus: les paris moneyline etaient purement absents
    # de cet index, donc jamais captes.
    event_index = {}
    for key_name, sport in (("props_analysis", "nhl"), ("nba_analysis", "nba"),
                            ("mlb_analysis", "mlb"), ("mlb_ml_analysis", "mlb")):
        for game_data in signal.get(key_name) or []:
            key = f"{game_data.get('away_team','')} @ {game_data.get('home_team','')}".lower()
            eid = game_data.get("event_id", "")
            if eid and key not in event_index:
                event_index[key] = (sport, eid)

    if not event_index:
        print("  Aucun event_id dans signal.json — les props ne peuvent pas etre "
              "captees (le moneyline passe quand meme par le calendrier).")

    client = odds_api.get_client(api_key)

    prop_cache = {}   # (sport_key, event_id, market_key) -> index
    h2h_cache  = {}   # sport_key -> index
    prop_events = 0   # plafond de quota sur les appels event (10 credits chacun)

    captured = skipped_no_event = skipped_no_odds = 0
    for bet in pending:
        player  = bet.get("name", "")
        game    = bet.get("game", "")
        sport   = bet.get("sport", "nhl")
        mtype   = bet.get("market_type", "")
        opening = bet.get("b365_implied", bet.get("dk_implied", 0))
        basis   = bet.get("opening_basis", "brute")

        if not player or not opening:
            continue

        sport_key = SPORT_KEYS.get(sport, "")
        if not sport_key:
            continue

        game_key = game.lower()
        closing  = None

        if bet.get("bet_type") == "team" and mtype.startswith("moneyline"):
            # Marche de match: un seul appel couvre tout le calendrier.
            if sport_key not in h2h_cache:
                h2h_cache[sport_key] = h2h_closing_index(client, sport_key)
            idx = h2h_cache[sport_key]
            teams = idx.get(tuple(t.strip() for t in game_key.split(" @ "))) if " @ " in game_key else None
            if teams is None:
                # Repli: apparier sur le nom d'equipe seul.
                for _k, v in idx.items():
                    if any(player.lower() == t.lower() for t in v):
                        teams = v
                        break
            if teams:
                closing = next((v for t, v in teams.items()
                                if t.lower() == player.lower()), None)
        elif mtype in ("run_line_-1.5", "puck line", "total buts"):
            # Pas encore couvert: le spread demande la ligne exacte et un
            # appariement de point, a faire quand ces marches reprendront du
            # volume. Mieux vaut ne rien ecrire que d'ecrire un CLV faux.
            continue
        else:
            market_key = MARKET_MAP.get(mtype, "")
            event_info = event_index.get(game_key)
            if not market_key:
                continue
            if not event_info:
                skipped_no_event += 1
                continue
            ck = (sport_key, event_info[1], market_key)
            if ck not in prop_cache:
                cost = odds_api.COST_PER_MARKET_REGION_PROP * _n_regions()
                if prop_events >= odds_api.max_prop_events():
                    print(f"  [CLV] plafond ODDS_MAX_PROP_EVENTS={odds_api.max_prop_events()} "
                          f"atteint — {player} non capte")
                    continue
                if not client.can_spend_props(cost):
                    print(f"  [CLV] budget du jour atteint "
                          f"({client.spent_today() + client.prop_credits}/"
                          f"{client.day_budget()} credits) — {player} non capte")
                    continue
                client.note_props(cost)
                prop_cache[ck] = prop_closing_index(client, sport_key,
                                                    event_info[1], market_key)
                prop_events += 1
                time.sleep(0.3)
            lines = _match_player(prop_cache[ck], player)
            closing = _pick_line(lines, bet.get("line"))

        if not closing:
            skipped_no_odds += 1
            continue

        # Soustraire une fermeture de la meme base que l'ouverture.
        matched = closing["novig"] if (basis == "novig" and closing["novig"]) else closing["brute"]
        clv = round(opening - matched, 2)
        bet["closing_implied"] = closing["brute"]
        bet["closing_novig"]   = closing["novig"]
        bet["closing_odds"]    = closing["cote"]
        bet["closing_book"]    = closing["book"]
        bet["clv"]             = clv
        bet["clv_basis"]       = "novig" if matched == closing["novig"] else "brute"
        captured += 1
        direction = "✅" if clv >= 0 else "❌"
        print(f"  {direction} {player}: ouverture={opening:.1f}% → fermeture={matched:.1f}% "
              f"({bet['clv_basis']}, {closing['book']} @ {closing['cote']:.2f}) | CLV={clv:+.1f}%")

    print(f"\n{captured}/{len(pending)} bets avec CLV capte "
          f"({skipped_no_event} sans event_id, {skipped_no_odds} sans cote au marche)")
    client.log_status("CLV — ")
    client.persist_usage()   # la capture partage le budget du jour avec signal.py

    # Sauvegarder
    if captured > 0:
        with open(RESULTS_PATH, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print("results.json mis à jour avec CLV.")


# ── Ajout CLV au résumé (appelé par backtester) ──────────────────────────────

def compute_clv_summary(bets: list) -> dict:
    """
    Calcule les statistiques CLV sur les bets résolus qui ont un closing_implied.
    Retourne un dict de stats CLV.
    """
    resolved_with_clv = [
        b for b in bets
        if b.get("result") in ("W", "L") and b.get("clv") is not None
    ]

    if not resolved_with_clv:
        return {}

    clvs = [b["clv"] for b in resolved_with_clv]
    avg_clv = round(sum(clvs) / len(clvs), 2)
    positive_clv = sum(1 for c in clvs if c > 0)
    pct_positive = round(positive_clv / len(clvs) * 100, 1)

    # CLV par sport
    by_sport = {}
    for b in resolved_with_clv:
        sp = b.get("sport", "nhl")
        by_sport.setdefault(sp, []).append(b["clv"])

    by_sport_summary = {
        sp: {
            "n":       len(vals),
            "avg_clv": round(sum(vals) / len(vals), 2),
            "pct_pos": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
        }
        for sp, vals in by_sport.items()
    }

    return {
        "n":            len(resolved_with_clv),
        "avg_clv":      avg_clv,
        "pct_positive": pct_positive,
        "by_sport":     by_sport_summary,
    }


if __name__ == "__main__":
    from env_file import load_env
    load_env()
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("ERREUR: ODDS_API_KEY manquante (.env a la racine ou export)")
        sys.exit(1)
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    capture_clv(key, date_arg)
