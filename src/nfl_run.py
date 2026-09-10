#!/usr/bin/env python3
"""
Point d'entree du module NFL, appele par .github/workflows/nfl_signal.yml.

    python nfl_run.py                releve si on est dans une fenetre
    python nfl_run.py --force        releve maintenant, hors cadence
    python nfl_run.py --force --props-within 12
                                     idem, mais les props ne sont scannees que
                                     pour les matchs des 12 prochaines heures

`--force` sert aux matchs de semaine (un ouvreur le mercredi, un jeudi soir)
et aux essais. Il court-circuite la cadence, donc il depense du quota a chaque
appel: a utiliser sciemment.

`--props-within H` limite le scan des props aux matchs imminents. Sans lui, un
forcage en semaine depense des requetes sur les lignes de dimanche, encore
larges — ce que la cadence hebdomadaire cherche justement a eviter.
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

    within = None
    if "--props-within" in sys.argv:
        i = sys.argv.index("--props-within")
        if i + 1 < len(sys.argv):
            within = float(sys.argv[i + 1])
    elif os.environ.get("NFL_PROPS_WITHIN"):
        try:
            within = float(os.environ["NFL_PROPS_WITHIN"])
        except ValueError:
            within = None

    state = nfl_analyzer.run(key, force=force, props_within=within)

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

    props = state.get("props") or {}
    if props.get("signals") is not None:
        print(f"\nProps: {props.get('n_signals', 0)} signal(aux) sur "
              f"{props.get('n_scanned', 0)} match(s) scanne(s), "
              f"{props.get('requests', 0)} requete(s) — "
              f"{props.get('requests_week', 0)}/{props.get('max_requests', 0)} cette semaine")
        for sg in props.get("signals", []):
            if sg.get("type") == "cote":
                print(f"    {sg['edge_pct']:+5.1f}%  {sg['selection'][:38]:40} "
                      f"{sg['odds']:.2f} ({sg['book']})  juste {sg['fair_odds']:.2f}")
            else:
                o, u = sg.get("over", {}), sg.get("under", {})
                print(f"    middle   {sg['joueur'][:24]:26} Over {o.get('ligne')} "
                      f"@{o.get('odds')} ({o.get('book')}) / Under {u.get('ligne')} "
                      f"@{u.get('odds')} ({u.get('book')}) — fenetre {sg.get('fenetre')}")

    if not state.get("n_signals"):
        print("\nAucun signal sur les marches principaux: le marche est aligne.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
