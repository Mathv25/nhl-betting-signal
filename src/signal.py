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
from ai_analyst import run_analysis


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

    today_et = now_et.strftime("%Y-%m-%d")
    def is_today(ct):
        try:
            from datetime import timezone as _tz
            dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            return dt.astimezone(tz).strftime("%Y-%m-%d") == today_et
        except Exception:
            return True

    fetcher    = OddsFetcher(api_key)
    checker    = LineupChecker()
    lf_fetcher = LineupFetcher()
    calc       = EdgeCalculator()
    reporter   = ReportGenerator()
    props_an   = PropsAnalyzer()
    props_an._lineup_fetcher = lf_fetcher

    # ── 1. NHL ────────────────────────────────────────────────────────────────
    print("\nRecuperation des cotes NHL...")
    games_raw  = fetcher.get_nhl_games_b365()
    games      = []
    signals    = []
    props_by_game = []

    if not games_raw:
        print("Aucun match NHL avec cotes pour l'instant — passage au MLB/NBA.")
    else:
        games_all = games_raw
        games = [g for g in games_raw if is_today(g.get("commence_time", ""))]
        if len(games) < len(games_all):
            print(f"  Filtrage: {len(games_all)} matchs recus -> {len(games)} aujourd'hui ({today_et})")
        if not games:
            print("Aucun match NHL aujourd'hui — passage au MLB/NBA.")
        else:
            print(f"{len(games)} match(s) trouve(s)")

            # 2. Validation alignements
            print("\nValidation des alignements NHL.com...")
            games = checker.validate_players(games)
            props_an._roster_cache   = checker._roster_cache
            lf_fetcher._roster_cache = checker._roster_cache

            # 3. Line combos Daily Faceoff
            print("\nRecuperation des line combos Daily Faceoff...")
            teams_today = set()
            for game in games:
                teams_today.add(game["home_team"])
                teams_today.add(game["away_team"])
            for team in sorted(teams_today):
                lf_fetcher.get_lineup(team)
                time.sleep(1.0)

            # 4. Edges
            print("\nCalcul des edges...")
            for game in games:
                edges = calc.calculate_all_edges(game)
                signals.append({"game": game, "edges": edges})
                if edges:
                    print(f"  {game['away_team']} @ {game['home_team']}: {len(edges)} edge(s)")

            # 5. Props NHL
            time.sleep(10)
            print("\nAnalyse des props joueurs (top matchs)...")
            top_games = sorted(signals, key=lambda s: len(s["edges"]), reverse=True)[:8]
            for s in top_games:
                g = s["game"]
                try:
                    book = g.get("bookmaker", "draftkings")
                    print(f"  Fetch props {book}: {g['away_team']} @ {g['home_team']}...")
                    real_props = fetcher.get_nhl_player_props(g["id"], bookmaker=book)
                    n_lines = sum(len(v) for v in real_props.values()) if real_props else 0
                    print(f"    -> {n_lines} lignes props disponibles")
                    # Si props pas encore publiées (playoffs soir), fallback mode synthétique
                    if n_lines == 0:
                        print(f"    -> Props non disponibles — mode synthétique (modèle stat)")
                        real_props = None
                    game_total = g.get("markets", {}).get("totals", {}).get("over", {}).get("line")
                    analysis = props_an.analyze_game(g["home_team"], g["away_team"],
                                                     real_props=real_props, game_total=game_total)
                    if analysis.get("bets"):
                        props_by_game.append(analysis)
                except Exception as e:
                    print(f"  Props erreur {g['home_team']}: {e}")

    # ── 5b. NBA props ─────────────────────────────────────────────────────────
    time.sleep(5)
    print("\nAnalyse NBA props...")
    nba_fetcher  = NBAOddsFetcher(api_key)
    nba_analyzer = NBAPropsAnalyzer()
    nba_games    = [g for g in nba_fetcher.get_nba_games() if is_today(g.get("commence_time", ""))]
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

    # ── 5c. MLB props ─────────────────────────────────────────────────────────
    time.sleep(5)
    print("\nAnalyse MLB props...")
    mlb_fetcher  = MLBOddsFetcher(api_key)
    mlb_analyzer = MLBPropsAnalyzer()
    mlb_games    = [g for g in mlb_fetcher.get_mlb_games() if is_today(g.get("commence_time", ""))]
    mlb_analysis = []
    print(f"  {len(mlb_games)} partie(s) MLB aujourd'hui ({today_et})")
    for mg in mlb_games[:10]:
        props_by_market = {}
        for market in ["pitcher_strikeouts", "batter_hits", "batter_total_bases", "batter_home_runs", "batter_runs_scored"]:
            props = mlb_fetcher.get_player_props(mg["event_id"], market)
            if props:
                props_by_market[market] = props
        analysis = mlb_analyzer.analyze_game(mg, props_by_market if props_by_market else None)
        if analysis.get("bets"):
            analysis["commence_time"] = mg.get("commence_time", "")
            mlb_analysis.append(analysis)

    # Récupérer les bets des matchs commencés récemment (≤4h) depuis le signal précédent
    try:
        with open("../docs/signal.json", encoding="utf-8") as f:
            prev = json.load(f)
        now_utc = datetime.now(timezone.utc)
        already = {(g.get("home_team"), g.get("away_team")) for g in mlb_analysis}
        for pg in prev.get("mlb_analysis", []):
            ct = pg.get("commence_time", "")
            if not ct:
                continue
            game_dt   = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            hours_ago = (now_utc - game_dt).total_seconds() / 3600
            key = (pg.get("home_team"), pg.get("away_team"))
            if 0 < hours_ago <= 4 and key not in already and pg.get("bets"):
                for b in pg["bets"]:
                    b["status"] = "started"
                pg["status"] = "started"
                mlb_analysis.append(pg)
                print(f"  [Conservé] {pg.get('away_team')} @ {pg.get('home_team')} (débuté il y a {hours_ago:.1f}h)")
    except Exception:
        pass

    # ── 6. Vérification: au moins un sport a du contenu ───────────────────────
    has_content = games or nba_games or mlb_games
    if not has_content:
        print("\nAucun match NHL/NBA/MLB aujourd'hui. Signal existant conserve.")
        sys.exit(0)

    # ── 7. Value bets NHL ─────────────────────────────────────────────────────
    value_bets = sorted(
        [e for s in signals for e in s["edges"] if e["edge_pct"] >= 5.0],
        key=lambda x: x["edge_pct"], reverse=True
    )[:10]
    print(f"\n{len(value_bets)} bet(s) NHL avec edge >= 5% (top 10)")

    # ── 8. Output ─────────────────────────────────────────────────────────────
    output = {
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "date":             today_et,
        "bookmaker":        "bet365",
        "total_games":      len(games),
        "total_value_bets": len(value_bets),
        "signals":          signals,
        "value_bets":       value_bets,
        "props_analysis":   props_by_game,
        "nba_analysis":     nba_analysis,
        "mlb_analysis":     mlb_analysis,
    }

    # ── 9. Analyse experte IA ─────────────────────────────────────────────────
    print("\nAnalyse experte IA...")
    ai_analysis = run_analysis(output)
    output["ai_analysis"] = ai_analysis

    os.makedirs("../docs", exist_ok=True)
    with open("../docs/signal.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    reporter.generate_html(output)
    print("\nTermine -> docs/index.html + docs/signal.json")
    print("=" * 65)


if __name__ == "__main__":
    main()
