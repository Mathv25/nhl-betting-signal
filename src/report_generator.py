"""
Report Generator - Dashboard HTML GitHub Pages
Python 3.11 compatible - zero backslashes in f-strings
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
        total_games = data.get("total_games", 0)
        total_value = data.get("total_value_bets", 0)

        try:
            dt = datetime.fromisoformat(gen_at).astimezone(pytz.timezone("America/Toronto"))
            gen_display = dt.strftime("%d %b %Y a %H:%M ET")
        except Exception:
            gen_display = gen_at

        bet_cards = self._build_bet_cards(value_bets)
        rows      = self._build_rows(signals)

        html = (
            "<!DOCTYPE html>\n"
            "<html lang=\"fr\">\n<head>\n"
            "  <meta charset=\"UTF-8\">\n"
            "  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "  <title>NHL Signal bet365 - " + date_str + "</title>\n"
            + self._css()
            + "</head>\n<body>\n<div class=\"wrap\">\n"
            + self._header()
            + self._grid(date_str, total_games, total_value)
            + "\n<div class=\"sec\">Bets recommandes - Edge 3% minimum</div>\n"
            + bet_cards
            + "\n<div class=\"sec\">Tous les matchs du jour</div>\n"
            + self._table(rows)
            + self._legend()
            + self._disclaimer(gen_display)
            + "\n</div>\n</body>\n</html>"
        )

        os.makedirs("docs", exist_ok=True)
        with open("docs/index.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("  docs/index.html genere")

    def _build_bet_cards(self, value_bets):
        if not value_bets:
            return "<p class=\"no-bets\">Aucun bet avec edge superieur a 3% aujourd'hui.</p>"
        cards = ""
        for b in value_bets:
            ep    = b.get("edge_pct", 0)
            ec    = "edge-fire" if ep >= 8 else ("edge-good" if ep >= 5 else "edge-ok")
            note  = b.get("note", "")
            note_html = ("<div class=\"bet-note\">" + note + "</div>") if note else ""
            stat_edge = ("<div class=\"stat " + ec + "\"><span class=\"sl\">Edge</span>"
                         "<span class=\"sv\">+" + str(round(ep, 1)) + "%</span></div>")
            cards += (
                "\n<div class=\"bet-card\">"
                "<div class=\"bet-header\">"
                "<span class=\"bet-game\">" + b.get("game","") + "</span>"
                "<span class=\"verdict\">" + b.get("verdict","") + "</span>"
                "</div>"
                "<div class=\"bet-type\">" + b.get("type","") + "</div>"
                "<div class=\"bet-name\">" + b.get("bet","") + "</div>"
                + note_html
                + "<div class=\"bet-stats\">"
                "<div class=\"stat\"><span class=\"sl\">Cote b365</span>"
                "<span class=\"sv\">" + str(round(b.get("b365_odds",0), 2)) + "</span></div>"
                "<div class=\"stat\"><span class=\"sl\">Prob b365</span>"
                "<span class=\"sv\">" + str(round(b.get("b365_implied",0), 1)) + "%</span></div>"
                "<div class=\"stat\"><span class=\"sl\">Prob modele</span>"
                "<span class=\"sv\">" + str(round(b.get("our_prob",0), 1)) + "%</span></div>"
                + stat_edge
                + "<div class=\"stat\"><span class=\"sl\">Mise 1/4 Kelly</span>"
                "<span class=\"sv\">" + str(round(b.get("kelly_fraction",0), 1)) + "% BR</span></div>"
                "</div></div>"
            )
        return cards

    def _build_rows(self, signals):
        rows = ""
        for s in signals:
            g   = s["game"]
            ml  = g.get("markets", {}).get("moneyline", {})
            tt  = g.get("markets", {}).get("totals", {})
            pl  = g.get("markets", {}).get("puck_line", {})
            ho  = ml.get("home", {}).get("odds_decimal", "--")
            ao  = ml.get("away", {}).get("odds_decimal", "--")
            ol  = tt.get("over", {}).get("line", "--")
            oo  = tt.get("over", {}).get("odds_decimal", "--")
            uo  = tt.get("under", {}).get("odds_decimal", "--")
            plh = pl.get("home", {}).get("odds_decimal", "--")
            pla = pl.get("away", {}).get("odds_decimal", "--")
            ne  = len(s["edges"])
            away = g.get("away_team", "")
            home = g.get("home_team", "")

            badge = ""
            if ne:
                badge = "<span class=\"eb\">" + str(ne) + (" edges" if ne > 1 else " edge") + "</span>"

            try:
                t = datetime.fromisoformat(g["commence_time"]).astimezone(
                    pytz.timezone("America/Toronto")
                ).strftime("%H:%M ET")
            except Exception:
                t = "--"

            def fmt(v):
                return str(round(v, 2)) if isinstance(v, (int, float)) else str(v)

            rows += (
                "<tr>"
                "<td class=\"tm\">" + t + "</td>"
                "<td><strong>" + away + "</strong><br><small>@ " + home + "</small></td>"
                "<td class=\"num\">" + fmt(ao) + "<br><small>" + fmt(ho) + "</small></td>"
                "<td class=\"num\">" + fmt(pla) + "<br><small>" + fmt(plh) + "</small></td>"
                "<td class=\"num\">" + str(ol) + "<br><small>O:" + fmt(oo) + " U:" + fmt(uo) + "</small></td>"
                "<td>" + badge + "</td>"
                "</tr>"
            )
        return rows

    def _css(self):
        return (
            "<style>\n"
            ":root{--bg:#f8f8f7;--s:#fff;--b:rgba(0,0,0,.1);--t:#1a1a1a;--m:#666;"
            "--g:#1D9E75;--a:#BA7517;--r:12px;--rs:8px}\n"
            "@media(prefers-color-scheme:dark){:root{--bg:#111110;--s:#1c1c1b;"
            "--b:rgba(255,255,255,.1);--t:#f0efe8;--m:#888}}\n"
            "*{box-sizing:border-box;margin:0;padding:0}\n"
            "body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;"
            "background:var(--bg);color:var(--t);line-height:1.6;font-size:15px}\n"
            ".wrap{max-width:960px;margin:0 auto;padding:1.5rem 1rem}\n"
            "header{border-bottom:.5px solid var(--b);padding-bottom:1rem;margin-bottom:1.5rem}\n"
            "header h1{font-size:22px;font-weight:600}\n"
            "header p{font-size:13px;color:var(--m);margin-top:4px}\n"
            ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));"
            "gap:10px;margin-bottom:1.5rem}\n"
            ".box{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);padding:.875rem 1rem}\n"
            ".box .l{font-size:11px;color:var(--m)}\n"
            ".box .v{font-size:24px;font-weight:600;margin-top:2px}\n"
            ".sec{font-size:11px;font-weight:600;color:var(--m);text-transform:uppercase;"
            "letter-spacing:.06em;margin:1.5rem 0 .75rem}\n"
            ".bet-card{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);"
            "padding:1rem 1.25rem;margin-bottom:.75rem}\n"
            ".bet-header{display:flex;justify-content:space-between;align-items:flex-start;"
            "flex-wrap:wrap;gap:6px;margin-bottom:3px}\n"
            ".bet-game{font-size:12px;color:var(--m)}\n"
            ".verdict{font-size:12px;font-weight:500}\n"
            ".bet-type{font-size:10px;color:var(--m);text-transform:uppercase;"
            "letter-spacing:.05em;margin-bottom:4px}\n"
            ".bet-name{font-size:18px;font-weight:600;margin-bottom:.5rem}\n"
            ".bet-note{font-size:12px;color:var(--m);margin-bottom:.625rem;"
            "background:var(--bg);border-radius:var(--rs);padding:5px 10px;"
            "border-left:2px solid var(--b)}\n"
            ".bet-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:8px}\n"
            ".stat{background:var(--bg);border-radius:var(--rs);padding:7px 10px}\n"
            ".sl{font-size:11px;color:var(--m);display:block}\n"
            ".sv{font-size:14px;font-weight:600;display:block;margin-top:1px}\n"
            ".edge-fire .sv{color:var(--g)}.edge-good .sv{color:var(--g)}.edge-ok .sv{color:var(--a)}\n"
            ".no-bets{color:var(--m);font-style:italic;padding:1rem 0}\n"
            ".tbl-wrap{overflow-x:auto}\n"
            "table{width:100%;border-collapse:collapse;background:var(--s);"
            "border-radius:var(--r);overflow:hidden;border:.5px solid var(--b);"
            "font-size:13px;min-width:580px}\n"
            "th{background:var(--bg);padding:9px 10px;text-align:left;font-weight:500;"
            "color:var(--m);font-size:10px;text-transform:uppercase;letter-spacing:.05em}\n"
            "td{padding:9px 10px;border-top:.5px solid var(--b);vertical-align:top}\n"
            "td small{color:var(--m);font-size:11px}\n"
            ".tm{color:var(--m);font-size:12px;white-space:nowrap}\n"
            ".num{font-variant-numeric:tabular-nums}\n"
            ".eb{background:#E1F5EE;color:#0F6E56;font-size:11px;padding:2px 8px;"
            "border-radius:6px;font-weight:500;white-space:nowrap}\n"
            "@media(prefers-color-scheme:dark){.eb{background:#085041;color:#9FE1CB}}\n"
            ".legend{font-size:12px;color:var(--m);margin-top:1rem;line-height:1.8}\n"
            ".disc{font-size:11px;color:var(--m);margin-top:1.5rem;padding-top:1rem;"
            "border-top:.5px solid var(--b);line-height:1.7}\n"
            ".upd{font-size:11px;color:var(--m);text-align:right;margin-top:.5rem}\n"
            "@media(max-width:600px){.bet-stats{grid-template-columns:repeat(2,1fr)}"
            "header h1{font-size:18px}}\n"
            "</style>\n"
        )

    def _header(self):
        return (
            "<header>\n"
            "  <h1>NHL Betting Signal</h1>\n"
            "  <p>Cotes <strong>bet365</strong> · Poisson bivarie · 1/4 Kelly · "
            "Alignements NHL.com · Props joueurs stats reelles</p>\n"
            "</header>\n"
        )

    def _grid(self, date_str, total_games, total_value):
        return (
            "<div class=\"grid\">\n"
            "  <div class=\"box\"><div class=\"l\">Date</div>"
            "<div class=\"v\" style=\"font-size:17px\">" + date_str + "</div></div>\n"
            "  <div class=\"box\"><div class=\"l\">Matchs</div>"
            "<div class=\"v\">" + str(total_games) + "</div></div>\n"
            "  <div class=\"box\"><div class=\"l\">Bets +EV</div>"
            "<div class=\"v\" style=\"color:var(--g)\">" + str(total_value) + "</div></div>\n"
            "  <div class=\"box\"><div class=\"l\">Bookmaker</div>"
            "<div class=\"v\" style=\"font-size:17px\">bet365</div></div>\n"
            "</div>\n"
        )

    def _table(self, rows):
        empty = "<tr><td colspan=\"6\" style=\"color:var(--m);text-align:center\">Aucun match</td></tr>"
        return (
            "<div class=\"tbl-wrap\">\n<table>\n"
            "<thead><tr>"
            "<th>Heure</th><th>Match</th><th>ML</th><th>PL</th><th>Total</th><th>Edges</th>"
            "</tr></thead>\n"
            "<tbody>" + (rows if rows else empty) + "</tbody>\n"
            "</table>\n</div>\n"
        )

    def _legend(self):
        return (
            "<div class=\"legend\">"
            "<strong>Marches:</strong> Moneyline · Puck Line · Total · "
            "1re periode · Props shots/buts/passes/points/saves"
            "<br><strong>Modele:</strong> Poisson bivarie · H/A · back-to-back · PP/PK · "
            "gardien partant · stats 10 derniers matchs · 1/4 Kelly"
            "</div>\n"
        )

    def _disclaimer(self, gen_display):
        return (
            "<p class=\"disc\">Signal informatif uniquement. Aucun resultat garanti. "
            "Verifiez les cotes sur bet365. Jouez responsablement. 18+</p>\n"
            "<p class=\"upd\">Genere le " + gen_display + "</p>\n"
        )

    def generate_empty_report(self):
        os.makedirs("docs", exist_ok=True)
        html = (
            "<!DOCTYPE html><html lang=\"fr\"><head><meta charset=\"UTF-8\">"
            "<title>NHL Signal bet365</title>"
            "<style>body{font-family:-apple-system,sans-serif;background:#f8f8f7;"
            "display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}"
            ".box{background:#fff;border-radius:16px;padding:2rem;"
            "border:.5px solid rgba(0,0,0,.1);max-width:480px;text-align:center}"
            "h1{font-size:22px}p{color:#666;font-size:14px;line-height:1.7}"
            ".b{display:inline-block;background:#E1F5EE;color:#0F6E56;"
            "padding:4px 14px;border-radius:8px;font-size:13px;margin-top:1rem}"
            "</style></head><body>"
            "<div class=\"box\"><h1>NHL Betting Signal</h1>"
            "<p>Aucun match NHL avec cotes bet365 aujourd'hui.</p>"
            "<p>Signal genere automatiquement a <strong>9h ET</strong>.</p>"
            "<span class=\"b\">bet365 · Poisson · 1/4 Kelly</span>"
            "</div></body></html>"
        )
        with open("docs/index.html", "w", encoding="utf-8") as f:
            f.write(html)
        with open("docs/signal.json", "w") as f:
            json.dump({"date": "", "games": [], "value_bets": []}, f)
