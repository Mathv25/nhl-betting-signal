"""
NHL Betting Signal - Script principal
Bookmaker: bet365
"""
import json, os, sys, time
from datetime import datetime, timezone
import pytz
from odds_fetcher import OddsFetcher
from nba_odds_fetcher import NBAOddsFetcher
from nba_props_analyzer import NBAPropsAnalyzer
from mlb_odds_fetcher import MLBOddsFetcher
from mlb_props_analyzer import MLBPropsAnalyzer
from lineup_checker import LineupChecker
from lineup_fetcher import LineupFetcher
from edge_calculator import EdgeCalculator
from report_generator import ReportGenerator
from props_analyzer import PropsAnalyzer


def main():
    tz     = pytz.timezone("America/Toronto")
    now_et = datetime.now(tz)
    print("=" * 65)
    print("NHL + NBA BETTING SIGNAL")
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
        print("Aucun match NHL avec cotes DraftKings pour l'instant.")
        print("Le signal existant est conserve. DraftKings poste les cotes en cours de journee.")
        sys.exit(0)
    print(f"{len(games)} match(s) trouve(s)")

    # 2. Validation alignements NHL.com
    print("\nValidation des alignements NHL.com...")
    games = checker.validate_players(games)

    # Partage du cache roster entre tous les modules — evite les 429
    props_an._roster_cache   = checker._roster_cache
    lf_fetcher._roster_cache = checker._roster_cache

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

    # 5. Analyse props joueurs (top 8 matchs) — cotes DraftKings reelles
    time.sleep(10)
    print("\nAnalyse des props joueurs (top matchs)...")
    top_games = sorted(signals, key=lambda s: len(s["edges"]), reverse=True)[:8]
    props_by_game = []
    for s in top_games:
        g = s["game"]
        try:
            book = g.get("bookmaker", "draftkings")
            print(f"  Fetch props {book}: {g['away_team']} @ {g['home_team']}...")
            real_props = fetcher.get_nhl_player_props(g["id"], bookmaker=book)
            n_lines = sum(len(v) for v in real_props.values()) if real_props else 0
            print(f"    -> {n_lines} lignes props disponibles ({list(real_props.keys()) if real_props else 'aucune'})")
            analysis = props_an.analyze_game(g["home_team"], g["away_team"], real_props=real_props)
            if analysis.get("bets"):
                props_by_game.append(analysis)
        except Exception as e:
            print(f"  Props erreur {g['home_team']}: {e}")

    # 5b. NBA props
    time.sleep(5)
    print("\nAnalyse NBA props...")
    nba_fetcher  = NBAOddsFetcher(api_key)
    nba_analyzer = NBAPropsAnalyzer()
    nba_games    = nba_fetcher.get_nba_games()
    nba_analysis = []
    for ng in nba_games[:8]:
        props_by_market = {}
        for market in ["player_points", "player_rebounds", "player_assists",
                        "player_threes", "player_points_rebounds_assists"]:
            props = nba_fetcher.get_player_props(ng["event_id"], market)
            if props:
                props_by_market[market] = props
        if props_by_market:
            analysis = nba_analyzer.analyze_game(ng, props_by_market)
            if analysis.get("bets"):
                analysis["commence_time"] = ng.get("commence_time", "")
                nba_analysis.append(analysis)

    # 5c. MLB props
    time.sleep(5)
    print("\nAnalyse MLB props...")
    mlb_fetcher  = MLBOddsFetcher(api_key)
    mlb_analyzer = MLBPropsAnalyzer()
    mlb_games    = mlb_fetcher.get_mlb_games()
    mlb_analysis = []
    for mg in mlb_games[:10]:
        props_by_market = {}
        for market in ["pitcher_strikeouts", "batter_hits", "batter_total_bases", "batter_home_runs"]:
            props = mlb_fetcher.get_player_props(mg["event_id"], market)
            if props:
                props_by_market[market] = props
        analysis = mlb_analyzer.analyze_game(mg, props_by_market if props_by_market else None)
        if analysis.get("bets"):
            analysis["commence_time"] = mg.get("commence_time", "")
            mlb_analysis.append(analysis)

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
        "nba_analysis":     nba_analysis,
        "mlb_analysis":     mlb_analysis,
    }

    os.makedirs("../docs", exist_ok=True)
    with open("../docs/signal.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    reporter.generate_html(output)
    print("\nTermine -> docs/index.html + docs/signal.json")
    print("=" * 65)


if __name__ == "__main__":
    main()
