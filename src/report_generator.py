"""
Génère le dashboard HTML pour GitHub Pages.
Design: propre, mobile-friendly, dark/light mode.
"""

import json
from datetime import datetime
import pytz


class ReportGenerator:

    def generate_html(self, data: dict):
        date_str = data.get("date", "")
        value_bets = data.get("value_bets", [])
        signals = data.get("signals", [])
        generated_at = data.get("generated_at", "")

        # Formatage de la date pour affichage
        try:
            dt = datetime.fromisoformat(generated_at).astimezone(pytz.timezone("America/Toronto"))
            gen_display = dt.strftime("%d %b %Y à %H:%M ET")
        except Exception:
            gen_display = generated_at

        # Cartes de bets
        bet_cards_html = ""
        if not value_bets:
            bet_cards_html = '<p class="no-bets">Aucun bet avec edge ≥ 3% détecté aujourd\'hui.</p>'
        else:
            for bet in value_bets:
                edge = bet["edge_pct"]
                edge_class = "edge-fire" if edge >= 8 else ("edge-good" if edge >= 5 else "edge-ok")
                kelly = bet.get("kelly_fraction", 0)
                bet_cards_html += f"""
                <div class="bet-card">
                  <div class="bet-header">
                    <span class="bet-game">{bet['game']}</span>
                    <span class="verdict">{bet['verdict']}</span>
                  </div>
                  <div class="bet-type">{bet['type']}</div>
                  <div class="bet-name">{bet['bet']}</div>
                  <div class="bet-stats">
                    <div class="stat">
                      <span class="stat-label">Cote b365</span>
                      <span class="stat-val">{bet['b365_odds']:.2f}</span>
                    </div>
                    <div class="stat">
                      <span class="stat-label">Prob. implicite</span>
                      <span class="stat-val">{bet['b365_implied']:.1f}%</span>
                    </div>
                    <div class="stat">
                      <span class="stat-label">Notre prob.</span>
                      <span class="stat-val">{bet['our_prob']:.1f}%</span>
                    </div>
                    <div class="stat {edge_class}">
                      <span class="stat-label">Edge</span>
                      <span class="stat-val">+{edge:.1f}%</span>
                    </div>
                    <div class="stat">
                      <span class="stat-label">Mise suggérée</span>
                      <span class="stat-val">{kelly:.1f}% bankroll</span>
                    </div>
                  </div>
                </div>"""

        # Tableau des matchs
        games_html = ""
        for s in signals:
            g = s["game"]
            ml = g.get("markets", {}).get("moneyline", {})
            totals = g.get("markets", {}).get("totals", {})
            home_odds = ml.get("home", {}).get("odds_decimal", "—")
            away_odds = ml.get("away", {}).get("odds_decimal", "—")
            over_line = totals.get("over", {}).get("line", "—")
            over_odds = totals.get("over", {}).get("odds_decimal", "—")
            under_odds = totals.get("under", {}).get("odds_decimal", "—")
            n_edges = len(s["edges"])
            badge = f'<span class="edge-badge">{n_edges} edge{"s" if n_edges > 1 else ""}</span>' if n_edges else ""

            try:
                dt = datetime.fromisoformat(g["commence_time"]).astimezone(pytz.timezone("America/Toronto"))
                time_str = dt.strftime("%H:%M ET")
            except Exception:
                time_str = "—"

            games_html += f"""
            <tr>
              <td class="td-time">{time_str}</td>
              <td><strong>{g['away_team']}</strong><br><small>{g['home_team']}</small></td>
              <td>{away_odds if isinstance(away_odds, str) else f'{away_odds:.2f}'}<br>
                  <small>{home_odds if isinstance(home_odds, str) else f'{home_odds:.2f}'}</small></td>
              <td>{over_line} | O:{over_odds if isinstance(over_odds, str) else f'{over_odds:.2f}'} / U:{under_odds if isinstance(under_odds, str) else f'{under_odds:.2f}'}</td>
              <td>{badge}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>🏒 NHL Signal — bet365 | {date_str}</title>
  <style>
    :root {{
      --bg: #f8f8f7;
      --surface: #ffffff;
      --border: rgba(0,0,0,0.1);
      --text: #1a1a1a;
      --muted: #666;
      --green: #1D9E75;
      --amber: #BA7517;
      --red: #A32D2D;
      --blue: #185FA5;
      --radius: 12px;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #111110;
        --surface: #1c1c1b;
        --border: rgba(255,255,255,0.1);
        --text: #f0efe8;
        --muted: #999;
      }}
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg); color: var(--text); line-height: 1.6; }}
    .container {{ max-width: 900px; margin: 0 auto; padding: 1.5rem 1rem; }}
    header {{ border-bottom: 0.5px solid var(--border); padding-bottom: 1rem; margin-bottom: 1.5rem; }}
    header h1 {{ font-size: 22px; font-weight: 600; }}
    header p {{ font-size: 13px; color: var(--muted); margin-top: 4px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
                gap: 12px; margin-bottom: 1.5rem; }}
    .stat-box {{ background: var(--surface); border: 0.5px solid var(--border);
                 border-radius: var(--radius); padding: 1rem; }}
    .stat-box .label {{ font-size: 12px; color: var(--muted); }}
    .stat-box .value {{ font-size: 26px; font-weight: 600; margin-top: 2px; }}
    .section-title {{ font-size: 13px; font-weight: 600; color: var(--muted);
                      text-transform: uppercase; letter-spacing: 0.05em;
                      margin: 1.5rem 0 0.75rem; }}
    .bet-card {{ background: var(--surface); border: 0.5px solid var(--border);
                 border-radius: var(--radius); padding: 1rem 1.25rem; margin-bottom: 0.75rem; }}
    .bet-header {{ display: flex; justify-content: space-between; align-items: flex-start;
                   margin-bottom: 4px; flex-wrap: wrap; gap: 8px; }}
    .bet-game {{ font-size: 12px; color: var(--muted); }}
    .verdict {{ font-size: 12px; font-weight: 500; }}
    .bet-type {{ font-size: 11px; color: var(--muted); text-transform: uppercase;
                 letter-spacing: 0.05em; margin-bottom: 4px; }}
    .bet-name {{ font-size: 18px; font-weight: 600; margin-bottom: 0.75rem; }}
    .bet-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
                  gap: 8px; }}
    .stat {{ background: var(--bg); border-radius: 8px; padding: 8px 10px; }}
    .stat-label {{ font-size: 11px; color: var(--muted); display: block; }}
    .stat-val {{ font-size: 15px; font-weight: 600; display: block; margin-top: 2px; }}
    .edge-fire .stat-val {{ color: var(--green); }}
    .edge-good .stat-val {{ color: var(--green); }}
    .edge-ok .stat-val {{ color: var(--amber); }}
    .no-bets {{ color: var(--muted); font-style: italic; padding: 1rem 0; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--surface);
             border-radius: var(--radius); overflow: hidden;
             border: 0.5px solid var(--border); font-size: 13px; }}
    th {{ background: var(--bg); padding: 10px 12px; text-align: left;
          font-weight: 500; color: var(--muted); font-size: 11px;
          text-transform: uppercase; letter-spacing: 0.05em; }}
    td {{ padding: 10px 12px; border-top: 0.5px solid var(--border); vertical-align: top; }}
    td small {{ color: var(--muted); font-size: 11px; }}
    .td-time {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .edge-badge {{ background: #E1F5EE; color: #0F6E56; font-size: 11px;
                   padding: 2px 8px; border-radius: 6px; font-weight: 500; white-space: nowrap; }}
    @media (prefers-color-scheme: dark) {{
      .edge-badge {{ background: #085041; color: #9FE1CB; }}
    }}
    .disclaimer {{ font-size: 11px; color: var(--muted); margin-top: 2rem;
                   padding-top: 1rem; border-top: 0.5px solid var(--border); line-height: 1.7; }}
    .updated {{ font-size: 11px; color: var(--muted); text-align: right; margin-top: 0.5rem; }}
  </style>
</head>
<body>
<div class="container">
  <header>
    <h1>🏒 NHL Betting Signal</h1>
    <p>Cotes exclusives <strong>bet365</strong> · Modèle Poisson · Kelly criterion · Alignements validés NHL.com</p>
  </header>

  <div class="summary">
    <div class="stat-box">
      <div class="label">Date</div>
      <div class="value" style="font-size:18px">{date_str}</div>
    </div>
    <div class="stat-box">
      <div class="label">Matchs analysés</div>
      <div class="value">{data['total_games']}</div>
    </div>
    <div class="stat-box">
      <div class="label">Bets +EV (≥3%)</div>
      <div class="value" style="color:var(--green)">{data['total_value_bets']}</div>
    </div>
    <div class="stat-box">
      <div class="label">Bookmaker</div>
      <div class="value" style="font-size:18px">bet365</div>
    </div>
  </div>

  <div class="section-title">🎯 Bets recommandés — Edge ≥ 3%</div>
  {bet_cards_html}

  <div class="section-title">📋 Tous les matchs du jour</div>
  <table>
    <thead>
      <tr>
        <th>Heure</th>
        <th>Match</th>
        <th>Moneyline (Vis/Dom)</th>
        <th>Total O/U</th>
        <th>Edges</th>
      </tr>
    </thead>
    <tbody>
      {games_html if games_html else '<tr><td colspan="5" style="color:var(--muted)">Aucun match</td></tr>'}
    </tbody>
  </table>

  <p class="disclaimer">
    ⚠️ Signal informatif et éducatif. Les probabilités sont des estimations statistiques — aucun résultat garanti.
    Toujours vérifier les cotes directement sur bet365 avant de parier. Le jeu comporte des risques financiers.
    Jouez de façon responsable. 18+.
  </p>
  <p class="updated">Généré le {gen_display}</p>
</div>
</body>
</html>"""

        with open("docs/index.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("  ✅ docs/index.html généré")

    def generate_empty_report(self):
        """Page vide si aucun match aujourd'hui."""
        html = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><title>NHL Signal</title></head>
<body style="font-family:sans-serif;padding:2rem">
<h1>🏒 NHL Betting Signal</h1>
<p>Aucun match NHL programmé aujourd'hui.</p>
</body></html>"""
        with open("docs/index.html", "w") as f:
            f.write(html)
        with open("docs/signal.json", "w") as f:
            json.dump({"date": "", "games": [], "value_bets": []}, f)
