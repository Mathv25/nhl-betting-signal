"""Journal des VRAIS paris bet365 (data/lite_bets.csv).

  add     lit un pari JSON dans $PAYLOAD (resaisie du meme pari = remplacement)
  grade   regle les paris en attente via api-web.nhle.com (gratuit)
  stats   ecrit docs/lite/bets.json
  pending code de sortie 0 s'il reste au moins un pari en attente, 1 sinon
"""
import csv
import hashlib
import json
import os
import sys
import unicodedata
from datetime import datetime, timezone

import requests

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CSV_PATH = os.path.join(ROOT, "data", "lite_bets.csv")
STATS_PATH = os.path.join(ROOT, "docs", "lite", "bets.json")
NHL = "https://api-web.nhle.com/v1"
MARKETS = ("ML", "Puck line", "Total", "SOG")
FIELDS = ["id", "logged_at", "date", "away", "home", "market", "selection", "line",
          "player", "odds", "stake", "p", "fair", "source", "status", "profit"]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().replace(".", " ").replace("-", " ").split())


def load(path=CSV_PATH):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(rows, path=CSV_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def validate(pl):
    """Retourne une ligne de journal propre, ou leve ValueError."""
    market = pl.get("market")
    if market not in MARKETS:
        raise ValueError("marche invalide: %r" % market)
    odds, stake = float(pl.get("odds", 0)), float(pl.get("stake", 0))
    if not 1.01 <= odds <= 50:
        raise ValueError("cote hors de 1.01-50: %s" % odds)
    if not 0 < stake <= 10:
        raise ValueError("mise hors de 0-10 u: %s" % stake)
    for f in ("date", "away", "home", "selection"):
        if not pl.get(f):
            raise ValueError("champ manquant: %s" % f)
    datetime.strptime(pl["date"], "%Y-%m-%d")
    line = pl.get("line")
    if market != "ML" and line in (None, ""):
        raise ValueError("ligne manquante")
    if market == "SOG" and not pl.get("player"):
        raise ValueError("joueur manquant")
    if market in ("Total", "SOG") and pl["selection"] not in ("Over", "Under"):
        raise ValueError("selection Over/Under attendue")
    p = float(pl.get("p") or 0)
    row = {"date": pl["date"], "away": pl["away"], "home": pl["home"], "market": market,
           "selection": pl["selection"], "line": "" if line in (None, "") else str(float(line)),
           "player": pl.get("player", "") if market == "SOG" else "",
           "odds": str(odds), "stake": str(stake),
           "p": str(round(p, 4)) if 0 < p < 1 else "",
           "fair": str(round(1 / p, 3)) if 0 < p < 1 else "",
           "source": pl.get("source", ""), "status": "pending", "profit": ""}
    key = "|".join(norm(row[k]) for k in ("date", "away", "home", "market", "selection", "line", "player"))
    row["id"] = hashlib.sha1(key.encode()).hexdigest()[:12]
    row["logged_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return row


def add(payload, path=CSV_PATH):
    row = validate(json.loads(payload))
    rows = [r for r in load(path) if r["id"] != row["id"]]
    rows.append(row)
    save(rows, path)
    return row


def team_match(nhl_name, my_name):
    """'Canadiens' (NHL) contre 'Montreal Canadiens' (Odds API): suffixe de mots."""
    a, b = norm(nhl_name).split(), norm(my_name).split()
    return bool(a) and b[-len(a):] == a


def find_game(games, away, home):
    for g in games:
        if team_match(g["awayTeam"]["name"]["default"], away) and \
                team_match(g["homeTeam"]["name"]["default"], home):
            return g
    return None


def find_sog(box, player):
    """Tirs du joueur (nom de famille + initiale), None s'il n'a pas joue."""
    parts = norm(player).split()
    if len(parts) < 2:
        return None
    initial, last = parts[0][0], " ".join(parts[1:])
    for side in ("awayTeam", "homeTeam"):
        team = box.get("playerByGameStats", {}).get(side, {})
        for p in team.get("forwards", []) + team.get("defense", []):
            n = norm(p["name"]["default"]).split()
            if len(n) >= 2 and n[0][0] == initial and " ".join(n[1:]) == last:
                return p.get("sog")
    return None


def settle(row, game, box=None):
    """win / loss / void selon le score final (prolongation et TB comprises)."""
    away_s, home_s = game["awayTeam"]["score"], game["homeTeam"]["score"]
    m, sel = row["market"], row["selection"]
    line = float(row["line"]) if row["line"] else 0.0
    if m in ("ML", "Puck line"):
        if team_match(game["awayTeam"]["name"]["default"], sel) or norm(sel) == norm(row["away"]):
            diff = away_s - home_s
        else:
            diff = home_s - away_s
        margin = diff + (line if m == "Puck line" else 0)
    else:
        if m == "Total":
            value = away_s + home_s
        else:
            value = find_sog(box or {}, row["player"])
            if value is None:
                return "void"
        margin = (value - line) if sel == "Over" else (line - value)
    return "win" if margin > 0 else "loss" if margin < 0 else "void"


def profit(row, result):
    stake, odds = float(row["stake"]), float(row["odds"])
    return round(stake * (odds - 1), 3) if result == "win" else -stake if result == "loss" else 0.0


def get_json(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def grade(path=CSV_PATH, fetch=get_json):
    rows = load(path)
    scores, n = {}, 0
    for row in rows:
        if row["status"] != "pending":
            continue
        if row["date"] not in scores:
            scores[row["date"]] = fetch("%s/score/%s" % (NHL, row["date"])).get("games", [])
        game = find_game(scores[row["date"]], row["away"], row["home"])
        if not game or game.get("gameState") not in ("OFF", "FINAL"):
            continue
        box = fetch("%s/gamecenter/%s/boxscore" % (NHL, game["id"])) if row["market"] == "SOG" else None
        result = settle(row, game, box)
        row["status"], row["profit"] = result, str(profit(row, result))
        n += 1
    save(rows, path)
    return n


def summarize(rows):
    done = [r for r in rows if r["status"] in ("win", "loss", "void")]
    decided = [r for r in done if r["status"] != "void"]
    wins = sum(r["status"] == "win" for r in decided)
    staked = sum(float(r["stake"]) for r in decided)
    pnl = sum(float(r["profit"] or 0) for r in done)
    edges = [float(r["odds"]) / float(r["fair"]) - 1 for r in rows if r.get("fair")]
    return {
        "n": len(rows), "pending": sum(r["status"] == "pending" for r in rows),
        "record": "%d-%d-%d" % (wins, len(decided) - wins, len(done) - len(decided)),
        "hit_rate": round(wins / len(decided), 4) if decided else None,
        "break_even": round(sum(1 / float(r["odds"]) for r in decided) / len(decided), 4) if decided else None,
        "profit": round(pnl, 3), "staked": round(staked, 3),
        "roi": round(pnl / staked, 4) if staked else None,
        "avg_edge": round(sum(edges) / len(edges), 4) if edges else None,
    }


def stats(path=CSV_PATH, out=STATS_PATH):
    rows = load(path)
    data = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total": summarize(rows),
            "by_market": {m: summarize([r for r in rows if r["market"] == m])
                          for m in MARKETS if any(r["market"] == m for r in rows)},
            "bets": sorted(rows, key=lambda r: r["logged_at"], reverse=True)[:200]}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return data


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "add":
        try:
            row = add(os.environ.get("PAYLOAD", ""))
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            sys.exit("saisie refusee: %s" % e)
        print("enregistre: %s %s %s @ %s" % (row["market"], row["selection"], row["line"], row["odds"]))
    elif cmd == "grade":
        print("%d paris regles" % grade())
    elif cmd == "stats":
        print(stats()["total"])
    elif cmd == "pending":
        sys.exit(0 if any(r["status"] == "pending" for r in load()) else 1)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
