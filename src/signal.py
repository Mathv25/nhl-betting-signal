"""
NHL Betting Signal - Script principal
Bookmaker: bet365
"""
import json, os, sys, time
from datetime import datetime, timezone
import pytz
from odds_fetcher import OddsFetcher
from lineup_checker import LineupChecker
from lineup_fetcher import LineupFetcher
from edge_calculator import EdgeCalculator
from report_generator import ReportGenerator
from props_analyzer import PropsAnalyzer


def main():
    tz     = pytz.timezone("America/Toronto")
    now_et = datetime.now(tz)
    print("=" * 65)
    print("NHL BETTING SIGNAL")
    print(now_et.strftime("%A %d %B %Y, %H:%M ET"))
    print("=" * 65)

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("ERREUR: Variable ODDS_API_KEY manquante.")
        sys.exit(1)

    fetcher    = OddsFetcher(api_key)
    checker    = LineupChecker()
    lf_fetcher = LineupFetcher()
    calc       = EdgeCalculator()
    reporter   = ReportGenerator()
    props_an   = PropsAnalyzer()
    props_an._lineup_fetcher = lf_fetcher

    # 1. Cotes DraftKings / bet365
    print("\nRecuperation des cotes NHL...")
    games = fetcher.get_nhl_games_b365()
    if not games:
        print("Aucun match NHL trouve.")
        reporter.generate_empty_report()
        sys.exit(0)
    print(f"{len(games)} match(s) trouve(s)")

    # 2. Validation alignements NHL.com
    print("\nValidation des alignements NHL.com...")
    games = checker.validate_players(games)
    props_an._roster_cache = checker._roster_cache

    # 3. Line combos Daily Faceoff (PP1/PP2/lignes)
    print("\nRecuperation des line combos Daily Faceoff...")
    teams_today = set()
    for game in games:
        teams_today.add(game["home_team"])
        teams_today.add(game["away_team"])
    for team in sorted(teams_today):
        lf_fetcher.get_lineup(team)
        time.sleep(1.0)

    # 4. Calcul des edges
    print("\nCalcul des edges...")
    signals = []
    for game in games:
        edges = calc.calculate_all_edges(game)
        signals.append({"game": game, "edges": edges})
        if edges:
            print(f"  {game['away_team']} @ {game['home_team']}: {len(edges)} edge(s)")

    # 5. Analyse props joueurs (top 8 matchs)
    time.sleep(10)
    print("\nAnalyse des props joueurs (top matchs)...")
    top_games = sorted(signals, key=lambda s: len(s["edges"]), reverse=True)[:8]
    props_by_game = []
    for s in top_games:
        g = s["game"]
        try:
            analysis = props_an.analyze_game(g["home_team"], g["away_team"])
            if analysis.get("bets"):
                props_by_game.append(analysis)
        except Exception as e:
            print(f"  Props erreur {g['home_team']}: {e}")

    # 6. Value bets — edge >= 5%, max 10
    value_bets = sorted(
        [e for s in signals for e in s["edges"] if e["edge_pct"] >= 5.0],
        key=lambda x: x["edge_pct"], reverse=True
    )[:10]
    print(f"\n{len(value_bets)} bet(s) avec edge >= 5% (top 10)")

    # 7. Output
    output = {
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "date":             now_et.strftime("%Y-%m-%d"),
        "bookmaker":        "bet365",
        "total_games":      len(games),
        "total_value_bets": len(value_bets),
        "signals":          signals,
        "value_bets":       value_bets,
        "props_analysis":   props_by_game,
    }

    os.makedirs("../docs", exist_ok=True)
    with open("../docs/signal.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    reporter.generate_html(output)
    print("\nTermine -> docs/index.html + docs/signal.json")
    print("=" * 65)


if __name__ == "__main__":
    main()
