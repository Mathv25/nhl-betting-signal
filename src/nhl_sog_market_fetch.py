"""
Historique des cotes de tirs au but (The Odds API, endpoint historical) pour
un ECHANTILLON de matchs 2025-26 — le vrai test du module SOG.

    ODDS_API_KEY=... python3 nhl_sog_market_fetch.py [n_matchs=300]

Cout: 1 credit par jour (liste des matchs) + 10 credits par match (un marche,
region us, un releve 60 minutes avant la mise au jeu). Garde-fou: arret si
le solde passe sous MIN_REMAINING (le dashboard en a besoin).

bet365 n'est pas dans ces donnees: ce sont DraftKings, FanDuel, BetMGM,
BetRivers, Caesars, Bovada, BetOnline. Le test mesure donc l'edge contre le
MARCHE, pas contre bet365 — c'est la limite restante, et elle est dite.

Sortie: data/nhl_sog/market_20252026.json.gz
  {gameId: {"event_id", "snapshot", "commence",
            "players": {nom_norm: {ligne: {book: {"Over": cote, "Under": cote}}}}}}
Reprise: les matchs deja releves ne sont jamais repayes.
"""
from __future__ import annotations

import gzip
import json
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests                  # noqa: E402

import nhl_sog_data as D         # noqa: E402
import nhl_sog_backtest as B     # noqa: E402
import nhl_sog_lineup as LU      # noqa: E402

BASE = "https://api.the-odds-api.com/v4/historical/sports/icehockey_nhl"
MIN_REMAINING = 9000
SNAP_BEFORE_MIN = 60
SEED = 20260930
SEASON = "20252026"


def out_path() -> str:
    return os.path.join(D.cache_dir(), f"market_{SEASON}.json.gz")


def load() -> dict:
    p = out_path()
    if not os.path.exists(p):
        return {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def save(d: dict) -> None:
    p = out_path()
    tmp = p + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, p)


def sample_games(n: int) -> list:
    """
    Matchs ou joue au moins un joueur de l'univers, tires au hasard (graine
    fixe) apres le 1er novembre: avant, la saison en cours pese peu dans la
    projection et le test mesurerait surtout le prior.
    """
    p24, t24 = D.load("20242025")
    p25, t25 = D.load(SEASON)
    recs = B.walk(p25, t25, p24, t24)
    games = sorted({(x["gameId"], x["date"]) for x in recs if x["date"] >= "2025-11-01"})
    rnd = random.Random(SEED)
    pick = sorted(rnd.sample(games, min(n, len(games))))
    teams = defaultdict(dict)
    for t in t25:
        teams[t["gameId"]][t["home"]] = t["team"]
    return [{"gameId": g, "date": d, "home": teams[g].get(1), "away": teams[g].get(0)} for g, d in pick]


def _names() -> dict:
    import nhl_stats
    return {v: k for k, v in nhl_stats.TEAM_ABBR.items()}


def run(n: int = 300, key: str = None) -> dict:
    key = key or os.environ.get("ODDS_API_KEY")
    if not key:
        raise SystemExit("ODDS_API_KEY manquante")
    have = load()
    todo = [g for g in sample_games(n) if str(g["gameId"]) not in have]
    print(f"  [SOG marche] {len(todo)} match(s) a relever ({len(have)} deja en cache)")
    names = _names()
    s = requests.Session()
    remaining = None
    events_by_day: dict = {}

    def get(url, params):
        nonlocal remaining
        r = s.get(url, params=dict(params, apiKey=key), timeout=30)
        remaining = int(r.headers.get("x-requests-remaining", remaining or 0))
        return r.json() if r.status_code == 200 else None

    for i, g in enumerate(todo, 1):
        if remaining is not None and remaining < MIN_REMAINING:
            print(f"  [SOG marche] arret: {remaining} credits < {MIN_REMAINING}")
            break
        day = g["date"]
        if day not in events_by_day:
            ev = get(f"{BASE}/events", {"date": f"{day}T15:00:00Z"}) or {}
            events_by_day[day] = ev.get("data") or []
        hn, an = LU.norm(names.get(g["home"], "")), LU.norm(names.get(g["away"], ""))
        ev = next((e for e in events_by_day[day] if LU.norm(e["home_team"]) == hn
                   and LU.norm(e["away_team"]) == an and e["commence_time"][:10] in
                   (day, (datetime.fromisoformat(day) + timedelta(days=1)).strftime("%Y-%m-%d"))), None)
        if not ev:
            have[str(g["gameId"])] = {"event_id": None, "players": {}, "note": "evenement introuvable"}
            continue
        ct = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        snap = (ct - timedelta(minutes=SNAP_BEFORE_MIN)).strftime("%Y-%m-%dT%H:%M:%SZ")
        od = get(f"{BASE}/events/{ev['id']}/odds", {"date": snap, "regions": "us",
                                                   "markets": "player_shots_on_goal",
                                                   "oddsFormat": "decimal"}) or {}
        players: dict = {}
        for bm in (od.get("data") or {}).get("bookmakers", []):
            for mk in bm.get("markets", []):
                for oc in mk.get("outcomes", []):
                    if oc.get("point") is None or oc.get("name") not in ("Over", "Under"):
                        continue
                    players.setdefault(LU.norm(oc.get("description", "")), {}) \
                        .setdefault(f"{float(oc['point']):g}", {}) \
                        .setdefault(bm["key"], {})[oc["name"]] = oc["price"]
        have[str(g["gameId"])] = {"event_id": ev["id"], "snapshot": od.get("timestamp"),
                                  "commence": ev["commence_time"], "players": players}
        if i % 20 == 0:
            save(have)
            print(f"  [SOG marche] {i}/{len(todo)} — {remaining} credits restants", flush=True)
    save(have)
    print(f"  [SOG marche] termine: {len(have)} match(s) en cache, {remaining} credits restants")
    return have


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
