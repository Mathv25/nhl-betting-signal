"""
NHL Betting Signal - Générateur principal
Cibles: bet365 uniquement
Bets: Moneyline, Puck Line, Total buts, Props joueurs
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
    print("=" * 60)
    print("🏒 NHL BETTING SIGNAL — bet365")
    print(f"📅 {datetime.now(pytz.timezone('America/Toronto')).strftime('%A %d %B %Y, %H:%M ET')}")
    print("=" * 60)

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("❌ ERREUR: Variable ODDS_API_KEY manquante.")
        print("   → Ajoute ta clé dans les GitHub Secrets (Settings > Secrets > Actions)")
        sys.exit(1)

    fetcher = OddsFetcher(api_key)
    checker = LineupChecker()
    calculator = EdgeCalculator()
    reporter = ReportGenerator()

    print("\n📡 Récupération des cotes bet365 NHL...")
    games = fetcher.get_nhl_games_b365()
    if not games:
        print("⚠️  Aucun match NHL trouvé pour aujourd'hui.")
        reporter.generate_empty_report()
        sys.exit(0)

    print(f"✅ {len(games)} match(s) trouvé(s)")

    print("\n🏥 Vérification des alignements et blessures...")
    games = checker.validate_players(games)

    print("\n📊 Calcul des edges (probabilités vs cotes b365)...")
    signals = []
    for game in games:
        edges = calculator.calculate_all_edges(game)
        if edges:
            signals.append({
                "game": game,
                "edges": edges
            })

    print(f"\n✅ {sum(len(s['edges']) for s in signals)} opportunités analysées")

    value_bets = [
        edge
        for s in signals
        for edge in s["edges"]
        if edge["edge_pct"] >= 3.0
    ]
    print(f"🎯 {len(value_bets)} bets avec edge ≥ 3%")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(pytz.timezone("America/Toronto")).strftime("%Y-%m-%d"),
        "bookmaker": "bet365",
        "total_games": len(games),
        "total_value_bets": len(value_bets),
        "signals": signals,
        "value_bets": sorted(value_bets, key=lambda x: x["edge_pct"], reverse=True)
    }

    with open("docs/signal.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    reporter.generate_html(output)

    print("\n✅ Signal généré → docs/index.html + docs/signal.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
