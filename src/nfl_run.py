#!/usr/bin/env python3
"""
Point d'entree du module NFL, appele par .github/workflows/nfl_signal.yml.

    python nfl_run.py            releve si on est dans une fenetre
    python nfl_run.py --force    releve maintenant, hors cadence

`--force` sert aux matchs de semaine (un ouvreur le mercredi n'entre dans
aucune des trois fenetres) et aux essais. Il court-circuite la cadence, donc
il depense du quota a chaque appel: a utiliser sciemment.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_analyzer   # noqa: E402


def main() -> int:
    force = "--force" in sys.argv or os.environ.get("NFL_FORCE", "").lower() == "true"
    key   = os.environ.get("ODDS_API_KEY")
    if not key:
        print("ERREUR: ODDS_API_KEY manquante")
        return 1

    state = nfl_analyzer.run(key, force=force)

    print(f"\nSemaine {state.get('week', '?')} — {state.get('reason', '')}")
    print(f"{state.get('n_games', 0)} match(s), {state.get('n_signals', 0)} signal(aux) "
          f"au-dessus de {state.get('min_edge', '?')}%")
    if state.get("paper_logged"):
        print(f"{state['paper_logged']} pari(s) papier enregistre(s)")
    if state.get("closing_captured"):
        print(f"{state['closing_captured']} cote(s) de fermeture relevee(s)")

    for g in state.get("games", []):
        if not g.get("signals"):
            continue
        print(f"\n  {g['away_team']} @ {g['home_team']}")
        for s in g["signals"]:
            print(f"    {s['edge_pct']:+5.1f}%  {s['selection'][:38]:40} "
                  f"{s['odds']:.2f} ({s['book']})  juste {s['fair_odds']:.2f} "
                  f"[{s['source']}, {s['n_books']} books]")

    if not state.get("n_signals"):
        print("\nAucun signal: le marche est aligne. C'est un resultat, pas une panne.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
