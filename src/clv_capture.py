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


def _get(url, params=None):
    try:
        r = requests.get(url, params=params or {}, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return r.json()
        print(f"  API {r.status_code}: {url[:60]}")
    except Exception as e:
        print(f"  Erreur: {e}")
    return None


def fetch_closing_implied(api_key, event_id, sport_key, player_name, market_key, bookmaker="draftkings"):
    """
    Fetch l'implied probability actuelle pour un joueur/marché depuis The Odds API.
    Retourne float (implied en %) ou None si introuvable.
    """
    data = _get(f"{ODDS_API_BASE}/sports/{sport_key}/events/{event_id}/odds", {
        "apiKey":    api_key,
        "markets":   market_key,
        "bookmakers": bookmaker,
        "oddsFormat": "decimal",
    })
    if not data:
        return None

    player_l = player_name.lower().strip()
    for bm in data.get("bookmakers", []):
        for market in bm.get("markets", []):
            for outcome in market.get("outcomes", []):
                name = outcome.get("description", outcome.get("name", "")).lower()
                if player_l in name or name in player_l:
                    if "over" in outcome.get("name", "").lower() or outcome.get("point") is not None:
                        price = outcome.get("price", 0)
                        if price > 1:
                            return round(1 / price * 100, 2)
    return None


def capture_clv(api_key: str, target_date: str = None):
    """
    Pour chaque bet en attente (result == '?') du jour cible,
    fetch les cotes actuelles et stocke closing_implied.
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

    # Construire un index event_id par match (ex: "Buffalo Sabres @ Montréal Canadiens" → event_id)
    event_index = {}  # "away @ home" (lower) -> event_id
    for game_data in signal.get("props_analysis", []):
        key = f"{game_data.get('away_team','')} @ {game_data.get('home_team','')}".lower()
        eid = game_data.get("event_id", "")
        if eid:
            event_index[key] = ("nhl", eid)

    for game_data in signal.get("nba_analysis", []):
        key = f"{game_data.get('away_team','')} @ {game_data.get('home_team','')}".lower()
        eid = game_data.get("event_id", "")
        if eid:
            event_index[key] = ("nba", eid)

    for game_data in signal.get("mlb_analysis", []):
        key = f"{game_data.get('away_team','')} @ {game_data.get('home_team','')}".lower()
        eid = game_data.get("event_id", "")
        if eid:
            event_index[key] = ("mlb", eid)

    captured = 0
    for bet in pending:
        player  = bet.get("name", "")
        game    = bet.get("game", "")
        sport   = bet.get("sport", "nhl")
        mtype   = bet.get("market_type", "")
        opening = bet.get("b365_implied", bet.get("dk_implied", 0))

        if not player or not opening:
            continue

        game_key = game.lower()
        event_info = event_index.get(game_key)
        if not event_info:
            continue

        sport_key  = SPORT_KEYS.get(event_info[0], "")
        event_id   = event_info[1]
        market_key = MARKET_MAP.get(mtype, "")

        if not sport_key or not event_id or not market_key:
            continue

        closing = fetch_closing_implied(api_key, event_id, sport_key, player, market_key)
        if closing:
            clv = round(opening - closing, 2)
            bet["closing_implied"] = closing
            bet["clv"] = clv
            captured += 1
            direction = "✅" if clv >= 0 else "❌"
            print(f"  {direction} {player}: opening={opening:.1f}% → closing={closing:.1f}% | CLV={clv:+.1f}%")
        time.sleep(0.3)

    print(f"\n{captured}/{len(pending)} bets avec CLV capté")

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
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("ERREUR: ODDS_API_KEY manquante")
        sys.exit(1)
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    capture_clv(key, date_arg)
