"""NHL lite: Pinnacle sans marge comme reference, aucun modele maison.

Un appel aux lignes principales (Pinnacle, ~3 credits), puis un appel SOG par
match pas encore commence (~1 credit chacun, LITE_SOG=0 pour couper). Chaque
marche a 2 issues est debarrasse de sa marge par la methode puissance. On
publie p, la cote juste 1/p et la cote a exiger chez bet365 (1 + MIN_EDGE)/p
dans docs/lite/data.json.
"""
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

API = "https://api.the-odds-api.com/v4/sports/icehockey_nhl"
ET = ZoneInfo("America/Toronto")
SOG_BOOKS = "pinnacle,draftkings,fanduel,betmgm,williamhill_us,betrivers,espnbet"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "lite", "data.json")
MARKET_NAMES = {"h2h": "ML", "spreads": "Puck line", "totals": "Total"}


def devig_power(odds):
    """Probabilites sans marge: p_i = (1/o_i)^k, k choisi pour que la somme = 1."""
    implied = [1.0 / o for o in odds]
    if abs(sum(implied) - 1.0) < 1e-12:
        return implied
    lo, hi = 0.01, 100.0
    for _ in range(200):
        k = (lo + hi) / 2
        s = sum(q ** k for q in implied)
        # q < 1, donc la somme decroit quand k augmente
        if s > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    return [q ** k for q in implied]


def min_edge():
    return float(os.environ.get("LITE_MIN_EDGE", "0.03"))


def price_row(p, edge):
    return {"p": round(p, 4), "fair": round(1 / p, 3), "need": round((1 + edge) / p, 3)}


def et_date(commence_iso):
    t = datetime.fromisoformat(commence_iso.replace("Z", "+00:00"))
    return t.astimezone(ET).strftime("%Y-%m-%d")


def parse_main(events, edge, now=None):
    """Lignes Pinnacle h2h / spreads / totals des matchs pas encore commences."""
    now = now or datetime.now(timezone.utc)
    games = []
    for ev in events:
        start = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
        if start <= now:
            continue
        g = {"id": ev["id"], "commence_time": ev["commence_time"],
             "date": et_date(ev["commence_time"]), "away": ev["away_team"],
             "home": ev["home_team"], "lines": []}
        book = next((b for b in ev.get("bookmakers", []) if b["key"] == "pinnacle"), None)
        for m in (book or {}).get("markets", []):
            outs = m.get("outcomes", [])
            if m["key"] not in MARKET_NAMES or len(outs) != 2:
                continue
            probs = devig_power([o["price"] for o in outs])
            for o, p in zip(outs, probs):
                g["lines"].append(dict(
                    market=MARKET_NAMES[m["key"]], selection=o["name"],
                    line=o.get("point"), pinnacle=o["price"], source="Pinnacle",
                    **price_row(p, edge)))
        games.append(g)
    return games


def parse_sog(event, edge):
    """Une ligne par (joueur, seuil, cote). Pinnacle si le seuil exact existe,
    sinon mediane des p sans marge des books qui affichent Over ET Under."""
    per_book = {}  # (joueur, seuil) -> {book: p_over}
    for b in event.get("bookmakers", []):
        for m in b.get("markets", []):
            if m["key"] != "player_shots_on_goal":
                continue
            sides = {}
            for o in m.get("outcomes", []):
                key = (o.get("description"), o.get("point"))
                sides.setdefault(key, {})[o["name"]] = o["price"]
            for key, s in sides.items():
                if "Over" in s and "Under" in s and key[0] and key[1] is not None:
                    p_over = devig_power([s["Over"], s["Under"]])[0]
                    per_book.setdefault(key, {})[b["key"]] = p_over
    rows = []
    for (player, line), books in sorted(per_book.items()):
        if "pinnacle" in books:
            p_over, source = books["pinnacle"], "Pinnacle"
        else:
            p_over = statistics.median(books.values())
            source = "consensus %d books" % len(books)
        for side, p in (("Over", p_over), ("Under", 1 - p_over)):
            if 0 < p < 1:
                rows.append(dict(market="SOG", player=player, selection=side,
                                 line=line, source=source, **price_row(p, edge)))
    return rows


class Credits:
    def __init__(self):
        self.spent, self.remaining = 0, None

    def read(self, resp):
        try:
            self.spent += int(float(resp.headers.get("x-requests-last", 0)))
        except ValueError:
            pass
        rem = resp.headers.get("x-requests-remaining")
        if rem is not None:
            self.remaining = int(float(rem))


def fetch(url, params, credits):
    r = requests.get(url, params=params, timeout=30)
    credits.read(r)
    r.raise_for_status()
    return r.json()


def commence_time_to(now=None):
    """6 h ET le lendemain, en UTC ISO (format exige par l'API)."""
    now_et = (now or datetime.now(timezone.utc)).astimezone(ET)
    lim = (now_et + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    return lim.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        sys.exit("ODDS_API_KEY manquant")
    edge = min_edge()
    credits = Credits()
    events = fetch(API + "/odds", {
        "apiKey": key, "bookmakers": "pinnacle", "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal", "commenceTimeTo": commence_time_to()}, credits)
    games = parse_main(events, edge)
    sog = []
    if os.environ.get("LITE_SOG", "1") != "0":
        for g in games:
            try:
                ev = fetch("%s/events/%s/odds" % (API, g["id"]), {
                    "apiKey": key, "bookmakers": SOG_BOOKS,
                    "markets": "player_shots_on_goal", "oddsFormat": "decimal"}, credits)
            except requests.RequestException as e:
                print("SOG %s @ %s: %s" % (g["away"], g["home"], e))
                continue
            for row in parse_sog(ev, edge):
                row.update(event_id=g["id"], date=g["date"], away=g["away"], home=g["home"],
                           commence_time=g["commence_time"])
                sog.append(row)
    out = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "min_edge": edge, "credits": {"spent": credits.spent, "remaining": credits.remaining},
           "games": games, "sog": sog}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("%d matchs, %d lignes SOG, credits: %d depenses, %s restants"
          % (len(games), len(sog), credits.spent, credits.remaining))


if __name__ == "__main__":
    main()
