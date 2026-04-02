"""
NHL Betting Signal — Script principal
Bookmaker: bet365 exclusivement
"""

import json
import os
import sys
from datetime import datetime, timezone
import pytz

from odds_fetcher import OddsFetcher
from lineup_checker import LineupChecker
from edge_calculator import EdgeCalculator
from report_generator import ReportGenerator


def main():
    tz = pytz.timezone("America/Toronto")
    now_et = datetime.now(tz)

    print("=" * 65)
    print("🏒  NHL BETTING SIGNAL — bet365")
    print(f"📅  {now_et.strftime('%A %d %B %Y, %H:%M ET')}")
    print("=" * 65)

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("\n❌  ERREUR: Variable ODDS_API_KEY manquante.")
        print("    → Settings > Secrets > Actions > ODDS_API_KEY")
        sys.exit(1)

    fetcher    = OddsFetcher(api_key)
    checker    = LineupChecker()
    calculator = EdgeCalculator()
    reporter   = ReportGenerator()

    # ── 1. Cotes bet365 ───────────────────────────────────────────────────
    print("\n📡  Récupération des cotes bet365 NHL...")
    games = fetcher.get_nhl_games_b365()

    if not games:
        print("\n⚠️   Aucun match NHL avec cotes bet365 aujourd'hui.")
        reporter.generate_empty_report()
        sys.exit(0)

    print(f"✅  {len(games)} match(s) trouvé(s)")

    # ── 2. Validation alignements ──────────────────────────────────────────
    print("\n🏥  Validation des alignements (NHL.com officiel)...")
    games = checker.validate_players(games)

    # ── 3. Calcul des edges ────────────────────────────────────────────────
    print("\n📊  Calcul des edges (Poisson + Kelly)...")
    signals = []
    for game in games:
        edges = calculator.calculate_all_edges(game)
        signals.append({"game": game, "edges": edges})
        n = len(edges)
        if n:
            print(f"  → {game['away_team']} @ {game['home_team']}: {n} edge(s) détecté(s)")

    # ── 4. Tri des value bets ──────────────────────────────────────────────
    value_bets = sorted(
        [edge for s in signals for edge in s["edges"]],
        key=lambda x: x["edge_pct"],
        reverse=True
    )

    print(f"\n🎯  {len(value_bets)} bet(s) avec edge ≥ 3%")

    # ── 5. Output ──────────────────────────────────────────────────────────
    output = {
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "date":            now_et.strftime("%Y-%m-%d"),
        "bookmaker":       "bet365",
        "total_games":     len(games),
        "total_value_bets": len(value_bets),
        "signals":         signals,
        "value_bets":      value_bets,
    }

    os.makedirs("docs", exist_ok=True)
    with open("docs/signal.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    reporter.generate_html(output)

    print("\n✅  Terminé → docs/index.html + docs/signal.json")
    print("=" * 65)


if __name__ == "__main__":
    main()
