#!/usr/bin/env python3
"""
Suivi des paris pris — CLI.

    python track.py add                        (mode guide, questions une a une)
    python track.py add --date 2026-09-02 --sport mlb --market props_k \
        --selection "Tarik Skubal Over 6.5 K" --prob 58 --odds 1.95 \
        --book betano --stake 1
    python track.py close                      (mode guide: paris en attente)
    python track.py close --id "2026-09-02|mlb|props_k|..." --closing-odds 1.83 --result win
    python track.py list [--pending] [--sport mlb] [--limit 20]
    python track.py stats

Les donnees vont dans docs/bets.json, lu directement par l'onglet Performance
du dashboard. `add` et `close` recalculent les statistiques a l'ecriture, donc
le dashboard n'affiche jamais des chiffres plus vieux que le fichier.

Distinct de docs/results.json, qui suit ce que le modele a PROPOSE. Ici on
enregistre ce qui a ete MISE: la cote reellement obtenue, le book, la mise.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import bet_tracker as bt   # noqa: E402


# ── Saisie guidee ───────────────────────────────────────────────────────────

def pct(raw: str) -> float:
    """
    Probabilite en pourcentage. Refusee a la question et non a l'ecriture:
    sinon une fraction saisie au 5e champ ne se voit qu'apres avoir repondu
    aux 6 suivants, et toute la saisie est perdue.
    """
    v = float(raw)
    if v <= 1:
        raise ValueError(f"attendu en pourcentage (58 et non 0.58), recu {v}")
    if v > 100:
        raise ValueError(f"{v} > 100")
    return v


def decimal_odds(raw: str) -> float:
    """Cote decimale. Une cote americaine (+150 / -180) est traduite."""
    t = raw.strip()
    if t.startswith(("+", "-")) and t[1:].isdigit():
        am = int(t)
        return round(1 + (am / 100 if am > 0 else 100 / -am), 3)
    v = float(t)
    if v < 1.01:
        raise ValueError(f"cote decimale attendue >= 1.01, recu {v} "
                         f"(pour une cote americaine, garder le + ou le -)")
    return v


def positive(raw: str) -> float:
    v = float(raw)
    if v <= 0:
        raise ValueError(f"doit etre > 0, recu {v}")
    return v


def ask(label: str, default=None, required: bool = True, cast=None):
    """Pose une question jusqu'a obtenir une reponse valide."""
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        raw = input(f"{label}{suffix}: ").strip()
        if not raw and default not in (None, ""):
            raw = str(default)
        if not raw:
            if not required:
                return None
            print("  -> obligatoire")
            continue
        if cast is None:
            return raw
        try:
            return cast(raw)
        except ValueError as e:
            print(f"  -> {e}")


def cmd_add(args):
    from datetime import datetime, timedelta, timezone
    today_et = (datetime.now(timezone.utc) - timedelta(hours=4)).strftime("%Y-%m-%d")

    if args.selection and args.prob and args.odds:
        fields = dict(date=args.date or today_et, sport=args.sport, market=args.market,
                      selection=args.selection, model_prob=args.prob,
                      odds_taken=args.odds, book=args.book or "", stake=args.stake,
                      closing_odds=args.closing_odds, result=args.result,
                      note=args.note or "")
    else:
        print("Nouveau pari (Entree = valeur par defaut)\n")
        fields = dict(
            date=ask("Date (AAAA-MM-JJ)", today_et),
            sport=ask("Sport (mlb/nhl/nba)", args.sport or "mlb"),
            market=ask("Marche (moneyline/run_line/props_k/...)", args.market or "props_k"),
            selection=ask("Selection (ex: 'Tarik Skubal Over 6.5 K')"),
            model_prob=ask("Probabilite du modele en % (ex 58)", cast=pct),
            odds_taken=ask("Cote prise (1.95, ou +150 / -180)", cast=decimal_odds),
            book=ask("Book", args.book or "betano"),
            stake=ask("Mise en unites", args.stake or 1.0, cast=positive),
            closing_odds=ask("Cote de fermeture (vide si inconnue)",
                             required=False, cast=decimal_odds),
            result=ask("Resultat (pending/win/loss/push)", "pending"),
            note=ask("Note", required=False) or "",
        )

    try:
        bet = bt.add_bet(**fields)
    except ValueError as e:
        print(f"\nRefuse: {e}")
        return 1

    ev = bet["model_prob"] / 100 * bet["odds_taken"] - 1
    print(f"\nEnregistre: {bet['id']}")
    print(f"  {bet['selection']} @ {bet['odds_taken']} ({bet['book']}) "
          f"— mise {bet['stake']}u, modele {bet['model_prob']}%")
    print(f"  EV a la prise: {ev * 100:+.1f}% "
          f"(seuil de rentabilite {100 / bet['odds_taken']:.1f}%)")
    if ev <= 0:
        print("  Attention: EV negative aux chiffres fournis.")
    return 0


def cmd_close(args):
    data = bt.load()
    if args.id:
        try:
            bet = bt.close_bet(args.id, args.closing_odds, args.result)
        except (KeyError, ValueError) as e:
            print(f"Refuse: {e}")
            return 1
        print(f"Mis a jour: {bet['id']} -> fermeture "
              f"{bet.get('closing_odds')}, resultat {bet['result']}")
        return 0

    # Mode guide: tout ce qui attend un resultat ou une cote de fermeture.
    todo = [b for b in data["bets"]
            if b.get("result") == "pending" or not b.get("closing_odds")]
    if args.sport:
        todo = [b for b in todo if b.get("sport") == args.sport]
    if not todo:
        print("Rien a completer: tous les paris ont un resultat et une cote de fermeture.")
        return 0

    print(f"{len(todo)} pari(s) a completer — Entree pour passer, 'q' pour arreter.\n")
    for b in sorted(todo, key=lambda x: x.get("date", "")):
        print(f"[{b['date']}] {b['selection']} @ {b['odds_taken']} ({b['book']}) "
              f"— modele {b['model_prob']}%, mise {b['stake']}u")
        if not b.get("closing_odds"):
            raw = input("  Cote de fermeture (vide = passer, q = quitter): ").strip()
            if raw.lower() == "q":
                break
            if raw:
                try:
                    bt.close_bet(b["id"], closing_odds=decimal_odds(raw))
                except ValueError as e:
                    print(f"  -> ignore: {e}")
        if b.get("result") == "pending":
            raw = input("  Resultat (win/loss/push, vide = passer, q = quitter): ").strip().lower()
            if raw == "q":
                break
            if raw:
                try:
                    bt.close_bet(b["id"], result=raw)
                except ValueError as e:
                    print(f"  -> ignore: {e}")
        print()

    st = bt.load()["stats"]
    print(f"{st['n_counted']} pari(s) regle(s), {st['n_pending']} en attente, "
          f"{st['clv']['n_missing']} sans cote de fermeture.")
    return 0


def cmd_list(args):
    bets = bt.load()["bets"]
    if args.pending:
        bets = bt.pending(bets)
    if args.sport:
        bets = [b for b in bets if b.get("sport") == args.sport]
    bets = sorted(bets, key=lambda b: b.get("date", ""), reverse=True)[:args.limit]
    if not bets:
        print("Aucun pari.")
        return 0
    print(f"{'date':11}{'sport':6}{'marche':13}{'sel':38}"
          f"{'prob':>6}{'cote':>7}{'ferm':>7}{'mise':>6}{'res':>8}{'profit':>8}")
    print("-" * 110)
    for b in bets:
        p = bt.profit(b)
        print(f"{b.get('date',''):11}{b.get('sport',''):6}{b.get('market','')[:12]:13}"
              f"{b.get('selection','')[:37]:38}{b.get('model_prob',0):>5.1f}%"
              f"{b.get('odds_taken',0):>7.2f}"
              f"{(b.get('closing_odds') or 0):>7.2f}{b.get('stake',0):>6.2f}"
              f"{b.get('result',''):>8}{('—' if p is None else f'{p:+.2f}'):>8}")
    return 0


def cmd_stats(args):
    # Recalcul plutot que lecture du bloc `stats` du fichier: si le code de
    # calcul a change depuis la derniere ecriture, le fichier contient des
    # chiffres d'une version anterieure.
    st = bt.compute_stats(bt.load()["bets"])
    y, r, c = st["yield"], st["record"], st["clv"]

    print(f"\n{'=' * 62}\nPARIS SUIVIS\n{'=' * 62}")
    print(f"{st['n_bets']} pari(s) — {st['n_counted']} regle(s), "
          f"{st['n_pending']} en attente, {st['n_push']} push")
    if not st["n_counted"]:
        print("\nRien de regle: aucun rendement a calculer.")
        return 0

    print(f"\nMise totale     {y['staked']:.2f}u")
    print(f"Profit          {y['profit']:+.2f}u")
    print(f"Yield           {y['yield_pct']:+.2f}%"
          f"   IC 95% [{y['ci_low']:+.2f}% ; {y['ci_high']:+.2f}%]")
    if not y["reliable"]:
        print(f"                echantillon trop petit pour conclure "
              f"({y['n']} paris, il en faut ~30 pour l'approximation normale)")
    elif not y["excludes_zero"]:
        print("                l'intervalle contient 0: pas encore distinguable "
              "du hasard")
    else:
        print("                l'intervalle exclut 0")
    print(f"WR              {r['win_rate']:.1f}% ({r['wins']}-{r['losses']}) "
          f"a cote moyenne {r['avg_odds']:.2f} "
          f"(rentabilite a {r['breakeven_wr']:.1f}%, ecart {r['wr_vs_breakeven']:+.1f} pts)")
    if c["n"]:
        print(f"CLV moyen       {c['avg_clv_pct']:+.2f}% sur {c['n']} pari(s) "
              f"— {c['pct_positive']:.0f}% pris a meilleur prix que la fermeture")
    if c["n_missing"]:
        print(f"                {c['n_missing']} pari(s) sans cote de fermeture "
              f"(python track.py close)")

    if st["calibration"]:
        print(f"\n{'Tranche':10}{'n':>5}{'annonce':>10}{'observe':>10}"
              f"{'ecart':>8}{'cote moy':>10}{'profit':>9}")
        print("-" * 62)
        for row in st["calibration"]:
            flag = "  (mince)" if row["thin"] else ""
            print(f"{row['bucket']:10}{row['n']:>5}{row['expected']:>9.1f}%"
                  f"{row['observed']:>9.1f}%{row['gap']:>+8.1f}"
                  f"{row['avg_odds']:>10.2f}{row['profit']:>+9.2f}{flag}")

    if st["by_market"]:
        print(f"\n{'Marche':16}{'n':>5}{'ROI':>9}{'IC 95%':>22}{'WR':>8}{'cote moy':>10}")
        print("-" * 70)
        for m in st["by_market"]:
            ci = (f"[{m['ci_low']:+.1f} ; {m['ci_high']:+.1f}]"
                  if m["ci_low"] is not None else "n/d")
            print(f"{m['market'][:15]:16}{m['n']:>5}{m['roi_pct']:>+8.1f}%{ci:>22}"
                  f"{m['win_rate']:>7.1f}%{m['avg_odds']:>10.2f}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="enregistrer un pari pris")
    a.add_argument("--date")
    a.add_argument("--sport", default="mlb")
    a.add_argument("--market", default="props_k")
    a.add_argument("--selection")
    a.add_argument("--prob", type=float, help="probabilite du modele en %%")
    a.add_argument("--odds", type=float, help="cote prise (decimale)")
    a.add_argument("--book")
    a.add_argument("--stake", type=float, default=1.0)
    a.add_argument("--closing-odds", dest="closing_odds", type=float)
    a.add_argument("--result", default="pending", choices=list(bt.RESULTS))
    a.add_argument("--note")
    a.set_defaults(func=cmd_add)

    c = sub.add_parser("close", help="cotes de fermeture et resultats")
    c.add_argument("--id")
    c.add_argument("--closing-odds", dest="closing_odds", type=float)
    c.add_argument("--result", choices=list(bt.RESULTS))
    c.add_argument("--sport")
    c.set_defaults(func=cmd_close)

    l = sub.add_parser("list", help="lister les paris")
    l.add_argument("--pending", action="store_true")
    l.add_argument("--sport")
    l.add_argument("--limit", type=int, default=30)
    l.set_defaults(func=cmd_list)

    s = sub.add_parser("stats", help="yield, WR, CLV, calibration, ROI par marche")
    s.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
