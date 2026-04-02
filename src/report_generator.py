import json, os
from datetime import datetime
import pytz

class ReportGenerator:

    def generate_html(self, data: dict):
        date_str   = data.get("date","")
        value_bets = data.get("value_bets",[])
        signals    = data.get("signals",[])
        gen_at     = data.get("generated_at","")
        try:
            dt = datetime.fromisoformat(gen_at).astimezone(pytz.timezone("America/Toronto"))
            gen_display = dt.strftime("%d %b %Y a %H:%M ET")
        except Exception:
            gen_display = gen_at

        bet_cards = ""
        if not value_bets:
            bet_cards = '<p class="no-bets">Aucun bet avec edge >= 3% detecte aujourd\'hui.</p>'
        else:
            for b in value_bets:
                ec = "edge-fire" if b["edge_pct"]>=8 else ("edge-good" if b["edge_pct"]>=5 else "edge-ok")
                bet_cards += f"""<div class="bet-card">
                  <div class="bet-header">
                    <span class="bet-game">{b['game']}</span>
                    <span class="verdict">{b['verdict']}</span>
                  </div>
                  <div class="bet-type">{b['type']}</div>
                  <div class="bet-name">{b['bet']}</div>
                  <div class="bet-stats">
                    <div class="stat"><span class="stat-label">Cote b365</span>
                      <span class="stat-val">{b['b365_odds']:.2f}</span></div>
                    <div class="stat"><span class="stat-label">Prob. implicite b365</span>
                      <span class="stat-val">{b['b365_implied']:.1f}%</span></div>
                    <div class="stat"><span class="stat-label">Notre prob. (Poisson)</span>
                      <span class="stat-val">{b['our_prob']:.1f}%</span></div>
                    <div class="stat {ec}"><span class="stat-label">Edge</span>
                      <span class="stat-val">+{b['edge_pct']:.1f}%</span></div>
                    <div class="stat"><span class="stat-label">Mise (1/2 Kelly)</span>
                      <span class="stat-val">{b['kelly_fraction']:.1f}% bankroll</span></div>
                  </div>
                </div>"""

        rows = ""
        for s in signals:
            g  = s["game"]
            ml = g.get("markets",{}).get("moneyline",{})
            tt = g.get("markets",{}).get("totals",{})
            ho = ml.get("home",{}).get("odds_decimal","--")
            ao = ml.get("away",{}).get("odds_decimal","--")
            ol = tt.get("over",{}).get("line","--")
            oo = tt.get("over",{}).get("odds_decimal","--")
            uo = tt.get("under",{}).get("odds_decimal","--")
            ne = len(s["edges"])
            badge = f'<span class="eb">{ne} edge{"s" if ne>1 else ""}</span>' if ne else ""
            try:
                t = datetime.fromisoformat(g["commence_time"]).astimezone(pytz.timezone("America/Toronto")).strftime("%H:%M ET")
            except Exception:
                t = "--"
            fmt = lambda v: f"{v:.2f}" if isinstance(v,(int,float)) else str(v)
            rows += f"""<tr>
              <td class="tm">{t}</td>
              <td><strong>{g['away_team']}</strong><br><small>@ {g['home_team']}</small></td>
              <td>{fmt(ao)}<br><small>{fmt(ho)}</small></td>
              <td>{ol} | O:{fmt(oo)} U:{fmt(uo)}</td>
              <td>{badge}</td></tr>"""

        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>NHL Signal bet365 - {date_str}</title>
  <style>
    :root{{--bg:#f8f8f7;--s:#fff;--b:rgba(0,0,0,.1);--t:#1a1a1a;--m:#666;--g:#1D9E75;--a:#BA7517;--r:12px}}
    @media(prefers-color-scheme:dark){{:root{{--bg:#111110;--s:#1c1c1b;--b:rgba(255,255,255,.1);--t:#f0efe8;--m:#999}}}}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:var(--bg);color:var(--t);line-height:1.6}}
    .wrap{{max-width:900px;margin:0 auto;padding:1.5rem 1rem}}
    header{{border-bottom:.5px solid var(--b);padding-bottom:1rem;margin-bottom:1.5rem}}
    header h1{{font-size:22px;font-weight:600}} header p{{font-size:13px;color:var(--m);margin-top:4px}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:1.5rem}}
    .box{{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);padding:1rem}}
    .box .l{{font-size:12px;color:var(--m)}} .box .v{{font-size:26px;font-weight:600;margin-top:2px}}
    .sec{{font-size:12px;font-weight:600;color:var(--m);text-transform:uppercase;letter-spacing:.05em;margin:1.5rem 0 .75rem}}
    .bet-card{{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);padding:1rem 1.25rem;margin-bottom:.75rem}}
    .bet-header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px;flex-wrap:wrap;gap:8px}}
    .bet-game{{font-size:12px;color:var(--m)}} .verdict{{font-size:12px;font-weight:500}}
    .bet-type{{font-size:11px;color:var(--m);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}}
    .bet-name{{font-size:18px;font-weight:600;margin-bottom:.75rem}}
    .bet-stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px}}
    .stat{{background:var(--bg);border-radius:8px;padding:8px 10px}}
    .stat-label{{font-size:11px;color:var(--m);display:block}}
    .stat-val{{font-size:15px;font-weight:600;display:block;margin-top:2px}}
    .edge-fire .stat-val,.edge-good .stat-val{{color:var(--g)}} .edge-ok .stat-val{{color:var(--a)}}
    .no-bets{{color:var(--m);font-style:italic;padding:1rem 0}}
    table{{width:100%;border-collapse:collapse;background:var(--s);border-radius:var(--r);overflow:hidden;border:.5px solid var(--b);font-size:13px}}
    th{{background:var(--bg);padding:10px 12px;text-align:left;font-weight:500;color:var(--m);font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
    td{{padding:10px 12px;border-top:.5px solid var(--b);vertical-align:top}}
    td small{{color:var(--m);font-size:11px}} .tm{{color:var(--m);font-size:12px;white-space:nowrap}}
    .eb{{background:#E1F5EE;color:#0F6E56;font-size:11px;padding:2px 8px;border-radius:6px;font-weight:500}}
    @media(prefers-color-scheme:dark){{.eb{{background:#085041;color:#9FE1CB}}}}
    .disc{{font-size:11px;color:var(--m);margin-top:2rem;padding-top:1rem;border-top:.5px solid var(--b);line-height:1.7}}
    .upd{{font-size:11px;color:var(--m);text-align:right;margin-top:.5rem}}
  </style>
</head>
<body><div class="wrap">
  <header>
    <h1>🏒 NHL Betting Signal</h1>
    <p>Cotes exclusives <strong>bet365</strong> · Modele Poisson · 1/2 Kelly · Alignements NHL.com valides</p>
  </header>
  <div class="grid">
    <div class="box"><div class="l">Date</div><div class="v" style="font-size:18px">{date_str}</div></div>
    <div class="box"><div class="l">Matchs analyses</div><div class="v">{data['total_games']}</div></div>
    <div class="box"><div class="l">Bets +EV (>=3%)</div><div class="v" style="color:var(--g)">{data['total_value_bets']}</div></div>
    <div class="box"><div class="l">Bookmaker</div><div class="v" style="font-size:18px">bet365</div></div>
  </div>
  <div class="sec">Bets recommandes - Edge >= 3%</div>
  {bet_cards}
  <div class="sec">Tous les matchs du jour</div>
  <table>
    <thead><tr><th>Heure</th><th>Match</th><th>ML Vis/Dom</th><th>Total O/U</th><th>Edges</th></tr></thead>
    <tbody>{rows if rows else '<tr><td colspan="5" style="color:var(--m)">Aucun match</td></tr>'}</tbody>
  </table>
  <p class="disc">Signal informatif et educatif uniquement. Aucun resultat garanti. Verifiez toujours les cotes directement sur bet365 avant de parier. Jouez de facon responsable. 18+</p>
  <p class="upd">Genere le {gen_display}</p>
</div></body></html>"""

        os.makedirs("docs", exist_ok=True)
        with open("docs/index.html","w",encoding="utf-8") as f:
            f.write(html)
        print("  docs/index.html genere")

    def generate_empty_report(self):
        os.makedirs("docs", exist_ok=True)
        with open("docs/index.html","w") as f:
            f.write('<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>NHL Signal</title></head><body style="font-family:sans-serif;padding:2rem"><h1>NHL Betting Signal</h1><p>Aucun match NHL programme aujourd\'hui.</p></body></html>')
        with open("docs/signal.json","w") as f:
            json.dump({"date":"","games":[],"value_bets":[]},f)
