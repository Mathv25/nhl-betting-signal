"""
Report Generator — Dashboard HTML pour GitHub Pages
Design: propre, mobile-first, dark/light mode automatique.
"""

import json
import os
from datetime import datetime
import pytz


class ReportGenerator:

    def generate_html(self, data: dict):
        date_str   = data.get("date", "")
        value_bets = data.get("value_bets", [])
        signals    = data.get("signals", [])
        gen_at     = data.get("generated_at", "")

        try:
            dt = datetime.fromisoformat(gen_at).astimezone(pytz.timezone("America/Toronto"))
            gen_display = dt.strftime("%d %b %Y à %H:%M ET")
        except Exception:
            gen_display = gen_at

        # ── Cartes de bets ────────────────────────────────────────────────
        bet_cards = ""
        if not value_bets:
            bet_cards = '<p class="no-bets">Aucun bet avec edge ≥ 3% détecté aujourd\'hui. Reviens demain !</p>'
        else:
            for b in value_bets:
                ep  = b["edge_pct"]
                ec  = "edge-fire" if ep >= 8 else ("edge-good" if ep >= 5 else "edge-ok")
                note = b.get("note", "")
                note_html = f'<div class="bet-note">{note}</div>' if note else ""
                bet_cards += f"""
<div class="bet-card">
  <div class="bet-header">
    <span class="bet-game">{b['game']}</span>
    <span class="verdict">{b['verdict']}</span>
  </div>
  <div class="bet-type">{b['type']}</div>
  <div class="bet-name">{b['bet']}</div>
  {note_html}
  <div class="bet-stats">
    <div class="stat"><span class="sl">Cote b365</span><span class="sv">{b['b365_odds']:.2f}</span></div>
    <div class="stat"><span class="sl">Prob. b365</span><span class="sv">{b['b365_implied']:.1f}%</span></div>
    <div class="stat"><span class="sl">Prob. modèle</span><span class="sv">{b['our_prob']:.1f}%</span></div>
    <div class="stat {ec}"><span class="sl">Edge</span><span class="sv">+{ep:.1f}%</span></div>
    <div class="stat"><span class="sl">Mise ¼ Kelly</span><span class="sv">{b['kelly_fraction']:.1f}% BR</span></div>
  </div>
</div>"""

        # ── Tableau des matchs ────────────────────────────────────────────
        rows = ""
        for s in signals:
            g  = s["game"]
            ml = g.get("markets", {}).get("moneyline", {})
            tt = g.get("markets", {}).get("totals", {})
            pl = g.get("markets", {}).get("puck_line", {})
            ho = ml.get("home", {}).get("odds_decimal", "--")
            ao = ml.get("away", {}).get("odds_decimal", "--")
            ol = tt.get("over", {}).get("line", "--")
            oo = tt.get("over", {}).get("odds_decimal", "--")
            uo = tt.get("under", {}).get("odds_decimal", "--")
            pl_h = pl.get("home", {}).get("odds_decimal", "--")
            pl_a = pl.get("away", {}).get("odds_decimal", "--")
            ne  = len(s["edges"])
            badge = f'<span class="eb">{ne} edge{"s" if ne > 1 else ""}</span>' if ne else ""
            try:
                t = datetime.fromisoformat(g["commence_time"]).astimezone(
                    pytz.timezone("America/Toronto")
                ).strftime("%H:%M ET")
            except Exception:
                t = "--"
            fmt = lambda v: f"{v:.2f}" if isinstance(v, (int, float)) else str(v)
            rows += f"""<tr>
  <td class="tm">{t}</td>
  <td><strong>{g['away_team']}</strong><br><small>@ {g['home_team']}</small></td>
  <td class="num">{fmt(ao)}<br><small>{fmt(ho)}</small></td>
  <td class="num">{fmt(pl_a)}<br><small>{fmt(pl_h)}</small></td>
  <td class="num">{ol}<br><small>O:{fmt(oo)} U:{fmt(uo)}</small></td>
  <td>{badge}</td>
</tr>"""

        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>🏒 NHL Signal bet365 — {date_str}</title>
  <style>
    :root{{
      --bg:#f8f8f7;--s:#fff;--b:rgba(0,0,0,.1);--t:#1a1a1a;--m:#666;
      --g:#1D9E75;--a:#BA7517;--r:12px;--rs:8px;
    }}
    @media(prefers-color-scheme:dark){{
      :root{{--bg:#111110;--s:#1c1c1b;--b:rgba(255,255,255,.1);--t:#f0efe8;--m:#888}}
    }}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
          background:var(--bg);color:var(--t);line-height:1.6;font-size:15px}}
    .wrap{{max-width:960px;margin:0 auto;padding:1.5rem 1rem}}
    header{{border-bottom:.5px solid var(--b);padding-bottom:1rem;margin-bottom:1.5rem}}
    header h1{{font-size:22px;font-weight:600}}
    header p{{font-size:13px;color:var(--m);margin-top:4px}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
           gap:10px;margin-bottom:1.5rem}}
    .box{{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);padding:.875rem 1rem}}
    .box .l{{font-size:11px;color:var(--m)}}
    .box .v{{font-size:24px;font-weight:600;margin-top:2px}}
    .sec{{font-size:11px;font-weight:600;color:var(--m);text-transform:uppercase;
          letter-spacing:.06em;margin:1.5rem 0 .75rem}}
    .bet-card{{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);
               padding:1rem 1.25rem;margin-bottom:.75rem}}
    .bet-header{{display:flex;justify-content:space-between;align-items:flex-start;
                 flex-wrap:wrap;gap:6px;margin-bottom:3px}}
    .bet-game{{font-size:12px;color:var(--m)}}
    .verdict{{font-size:12px;font-weight:500}}
    .bet-type{{font-size:10px;color:var(--m);text-transform:uppercase;
               letter-spacing:.05em;margin-bottom:4px}}
    .bet-name{{font-size:18px;font-weight:600;margin-bottom:.5rem}}
    .bet-note{{font-size:12px;color:var(--m);margin-bottom:.625rem;
               background:var(--bg);border-radius:var(--rs);padding:5px 10px;
               border-left:2px solid var(--b)}}
    .bet-stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:8px}}
    .stat{{background:var(--bg);border-radius:var(--rs);padding:7px 10px}}
    .sl{{font-size:11px;color:var(--m);display:block}}
    .sv{{font-size:14px;font-weight:600;display:block;margin-top:1px}}
    .edge-fire .sv{{color:var(--g)}}
    .edge-good .sv{{color:var(--g)}}
    .edge-ok  .sv{{color:var(--a)}}
    .no-bets{{color:var(--m);font-style:italic;padding:1rem 0}}
    .tbl-wrap{{overflow-x:auto}}
    table{{width:100%;border-collapse:collapse;background:var(--s);
           border-radius:var(--r);overflow:hidden;border:.5px solid var(--b);
           font-size:13px;min-width:580px}}
    th{{background:var(--bg);padding:9px 10px;text-align:left;font-weight:500;
        color:var(--m);font-size:10px;text-transform:uppercase;letter-spacing:.05em}}
    td{{padding:9px 10px;border-top:.5px solid var(--b);vertical-align:top}}
    td small{{color:var(--m);font-size:11px}}
    .tm{{color:var(--m);font-size:12px;white-space:nowrap}}
    .num{{font-variant-numeric:tabular-nums}}
    .eb{{background:#E1F5EE;color:#0F6E56;font-size:11px;padding:2px 8px;
         border-radius:6px;font-weight:500;white-space:nowrap}}
    @media(prefers-color-scheme:dark){{
      .eb{{background:#085041;color:#9FE1CB}}
    }}
    .legend{{font-size:12px;color:var(--m);margin-top:1rem;line-height:1.8}}
    .disc{{font-size:11px;color:var(--m);margin-top:1.5rem;padding-top:1rem;
           border-top:.5px solid var(--b);line-height:1.7}}
    .upd{{font-size:11px;color:var(--m);text-align:right;margin-top:.5rem}}
    @media(max-width:600px){{
      .bet-stats{{grid-template-columns:repeat(2,1fr)}}
      header h1{{font-size:18px}}
    }}
  </style>
</head>
<body>
<div class="wrap">

  <header>
    <h1>🏒 NHL Betting Signal</h1>
    <p>Cotes <strong>bet365</strong> exclusivement · Poisson bivarié · ¼ Kelly · Alignements NHL.com validés · Props joueurs via stats réelles</p>
  </header>

  <div class="grid">
    <div class="box"><div class="l">Date</div><div class="v" style="font-size:17px">{date_str}</div></div>
    <div class="box"><div class="l">Matchs analysés</div><div class="v">{data['total_games']}</div></div>
    <div class="box"><div class="l">Bets +EV ≥3%</div><div class="v" style="color:var(--g)">{data['total_value_bets']}</div></div>
    <div class="box"><div class="l">Bookmaker</div><div class="v" style="font-size:17px">bet365</div></div>
  </div>

  <div class="sec">🎯 Bets recommandés — triés par edge décroissant</div>
  {bet_cards}

  <div class="sec">📋 Tous les matchs du jour</div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>Heure</th>
          <th>Match</th>
          <th>ML (Vis/Dom)</th>
          <th>PL ±1.5</th>
          <th>Total O/U</th>
          <th>Edges</th>
        </tr>
      </thead>
      <tbody>
        {rows if rows else '<tr><td colspan="6" style="color:var(--m);text-align:center">Aucun match aujourd\'hui</td></tr>'}
      </tbody>
    </table>
  </div>

  <div class="legend">
    <strong>Marchés couverts :</strong>
    Moneyline · Puck Line ±1.5 · Total buts · 1re période (ML + Total) ·
    Props joueurs : shots on goal, buts, passes, points, saves gardien
    <br>
    <strong>Modèle :</strong> Distribution de Poisson bivariée · Ajustements H/A, back-to-back, PP%, gardien partant ·
    Stats joueurs : 10 derniers matchs, pondération exponentielle · ¼ Kelly pour les mises
  </div>

  <p class="disc">
    ⚠️ Signal informatif et éducatif uniquement. Aucun résultat garanti.
    Vérifiez toujours les cotes directement sur bet365 avant de parier.
    Jouez de façon responsable. 18+
  </p>
  <p class="upd">Généré le {gen_display}</p>

</div>
</body>
</html>"""

        os.makedirs("docs", exist_ok=True)
        with open("docs/index.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("  ✅ docs/index.html généré")

    def generate_empty_report(self):
        """Page affichée quand il n'y a pas de matchs aujourd'hui."""
        os.makedirs("docs", exist_ok=True)
        html = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>🏒 NHL Signal bet365</title>
  <style>
    body{font-family:-apple-system,sans-serif;background:#f8f8f7;display:flex;
         align-items:center;justify-content:center;min-height:100vh;margin:0}
    .box{background:#fff;border-radius:16px;padding:2rem 2.5rem;
         border:.5px solid rgba(0,0,0,.1);max-width:480px;text-align:center}
    h1{font-size:22px;margin-bottom:.5rem}
    p{color:#666;font-size:14px;line-height:1.7}
    .badge{display:inline-block;background:#E1F5EE;color:#0F6E56;
           padding:4px 14px;border-radius:8px;font-size:13px;font-weight:500;margin-top:1rem}
  </style>
</head>
<body>
  <div class="box">
    <h1>🏒 NHL Betting Signal</h1>
    <p>Aucun match NHL avec cotes bet365 disponibles aujourd'hui.</p>
    <p style="margin-top:.75rem">Le signal se génère automatiquement chaque matin à <strong>9h ET</strong>.</p>
    <span class="badge">bet365 · Poisson · ¼ Kelly · Props réels</span>
  </div>
</body>
</html>"""
        with open("docs/index.html", "w", encoding="utf-8") as f:
            f.write(html)
        with open("docs/signal.json", "w") as f:
            json.dump({"date": "", "games": [], "value_bets": []}, f)
