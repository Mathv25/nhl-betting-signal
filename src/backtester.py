"""
Backtester NHL Signal
Valide la performance historique du modele sur les signal.json archives.
Usage: python backtester.py [dossier_archives]
"""

import json
import os
import sys
from datetime import datetime


def load_signals(folder: str) -> list:
    """Charge tous les signal.json dans un dossier."""
    signals = []
    for fname in sorted(os.listdir(folder)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(folder, fname)
        try:
            with open(path) as f:
                data = json.load(f)
                signals.append(data)
        except Exception as e:
            print(f"Erreur {fname}: {e}")
    return signals


def analyze(signals: list):
    """
    Analyse la performance des bets recommandes.
    Pour chaque bet, compare notre prob vs le resultat reel.

    Note: Pour valider correctement, il faut enregistrer les resultats
    reels manuellement ou via une API de resultats.
    """
    total_bets   = 0
    total_profit = 0.0
    bankroll     = 100.0  # Base 100 units
    results      = []

    for signal in signals:
        date      = signal.get("date", "?")
        value_bets = signal.get("value_bets", [])

        for bet in value_bets:
            total_bets += 1
            edge    = bet.get("edge_pct", 0)
            kelly   = bet.get("kelly_fraction", 0)
            odds    = bet.get("b365_odds", 2.0)
            prob    = bet.get("our_prob", 50) / 100

            # Mise = kelly% du bankroll, plafonnee a 3%
            stake_pct = min(kelly, 3.0)
            stake     = bankroll * stake_pct / 100

            results.append({
                "date":      date,
                "bet":       bet.get("bet", ""),
                "game":      bet.get("game", ""),
                "edge":      edge,
                "our_prob":  round(prob * 100, 1),
                "b365_impl": bet.get("b365_implied", 0),
                "odds":      odds,
                "stake":     round(stake, 2),
                "stake_pct": stake_pct,
                "result":    "?",  # A remplir manuellement
                "profit":    0.0,
            })

    # Stats globales
    print("\n" + "=" * 60)
    print("RAPPORT DE BACKTESTING")
    print("=" * 60)
    print(f"Nombre de signaux analyses: {len(signals)}")
    print(f"Nombre de bets total:       {total_bets}")

    if total_bets == 0:
        print("Aucun bet a analyser.")
        return

    # Distribution des edges
    edges = [r["edge"] for r in results]
    print(f"\nDistribution des edges:")
    print(f"  Min:     {min(edges):.1f}%")
    print(f"  Max:     {max(edges):.1f}%")
    print(f"  Moyenne: {sum(edges)/len(edges):.1f}%")
    print(f"  Median:  {sorted(edges)[len(edges)//2]:.1f}%")

    # Par categorie d'edge
    cats = [
        ("Edge >= 15% (Forte valeur)", lambda x: x >= 15),
        ("Edge 8-15% (Bonne valeur)",  lambda x: 8 <= x < 15),
        ("Edge 5-8% (Acceptable)",     lambda x: 5 <= x < 8),
        ("Edge 3-5% (Marginal)",       lambda x: 3 <= x < 5),
    ]
    print(f"\nPar categorie:")
    for label, cond in cats:
        n = sum(1 for e in edges if cond(e))
        print(f"  {label}: {n} bets ({n/total_bets*100:.0f}%)")

    # Par type de bet
    types = {}
    for r in results:
        bet_type = r["bet"].split(" ")[0] if r["bet"] else "?"
        types[bet_type] = types.get(bet_type, 0) + 1
    print(f"\nPar type:")
    for t, n in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t}: {n}")

    # Simulation EV theorique
    print(f"\nEV theorique (si edges reels):")
    ev_total = 0.0
    for r in results:
        # EV = stake * (prob * (odds-1) - (1-prob))
        ev = r["stake"] * (r["our_prob"]/100 * (r["odds"] - 1) - (1 - r["our_prob"]/100))
        ev_total += ev
    print(f"  EV total: {ev_total:.2f} units sur {total_bets} bets")
    print(f"  EV par bet: {ev_total/total_bets:.3f} units")

    # Export CSV pour analyse manuelle
    out_path = "backtest_results.csv"
    with open(out_path, "w") as f:
        f.write("date,bet,game,edge_pct,our_prob,b365_implied,odds,stake_pct,result,profit\n")
        for r in results:
            f.write(f"{r['date']},{r['bet']},{r['game']},{r['edge']},"
                    f"{r['our_prob']},{r['b365_impl']},{r['odds']},"
                    f"{r['stake_pct']},{r['result']},{r['profit']}\n")

    print(f"\nResultats exportes: {out_path}")
    print("Remplis la colonne 'result' avec W (win) ou L (loss)")
    print("et relance pour obtenir les stats de win rate et profit reel.")


def calculate_from_results(csv_path: str):
    """Calcule les stats a partir d'un CSV avec resultats."""
    import csv
    bets = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["result"] not in ("W", "L"):
                continue
            odds  = float(row["odds"])
            stake = float(row["stake_pct"])
            won   = row["result"] == "W"
            profit = stake * (odds - 1) if won else -stake
            bets.append({
                "edge":   float(row["edge_pct"]),
                "result": row["result"],
                "profit": profit,
                "stake":  stake,
            })

    if not bets:
        print("Aucun resultat valide dans le CSV.")
        return

    wins    = sum(1 for b in bets if b["result"] == "W")
    total   = len(bets)
    profit  = sum(b["profit"] for b in bets)
    staked  = sum(b["stake"] for b in bets)
    roi     = profit / staked * 100 if staked > 0 else 0

    print("\n" + "=" * 60)
    print("RESULTATS REELS")
    print("=" * 60)
    print(f"Total bets resolus: {total}")
    print(f"Wins:               {wins} ({wins/total*100:.1f}%)")
    print(f"Losses:             {total-wins} ({(total-wins)/total*100:.1f}%)")
    print(f"Profit total:       {profit:+.2f} units")
    print(f"Total mise:         {staked:.2f} units")
    print(f"ROI:                {roi:+.1f}%")

    # Par range d'edge
    for min_e, max_e in [(15, 999), (8, 15), (5, 8), (3, 5)]:
        subset = [b for b in bets if min_e <= b["edge"] < max_e]
        if not subset:
            continue
        w = sum(1 for b in subset if b["result"] == "W")
        p = sum(b["profit"] for b in subset)
        label = f"Edge {min_e}%+" if max_e == 999 else f"Edge {min_e}-{max_e}%"
        print(f"  {label}: {len(subset)} bets · {w/len(subset)*100:.0f}% WR · {p:+.1f}u profit")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python backtester.py [dossier_json | fichier_csv]")
        sys.exit(1)

    arg = sys.argv[1]
    if arg.endswith(".csv"):
        calculate_from_results(arg)
    elif os.path.isdir(arg):
        signals = load_signals(arg)
        analyze(signals)
    else:
        print(f"Argument invalide: {arg}")
        sys.exit(1)
