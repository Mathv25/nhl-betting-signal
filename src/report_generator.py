"""
Report Generator - Dashboard GitHub Pages complet
3 sections: Signal auto | Analyse joueurs | Calculateur edge
Python 3.11 compatible - zero backslashes in f-strings
"""

import json, os
from datetime import datetime
import pytz


class ReportGenerator:

    def generate_html(self, data: dict):
        date_str      = data.get("date", "")
        value_bets    = data.get("value_bets", [])
        signals       = data.get("signals", [])
        gen_at        = data.get("generated_at", "")
        total_games   = data.get("total_games", 0)
        total_value   = data.get("total_value_bets", 0)
        props_by_game = data.get("props_analysis", [])

        try:
            dt = datetime.fromisoformat(gen_at).astimezone(pytz.timezone("America/Toronto"))
            gen_display = dt.strftime("%d %b %Y a %H:%M ET")
        except Exception:
            gen_display = gen_at

        bet_cards  = self._bet_cards(value_bets)
        rows       = self._rows(signals)
        props_html = self._props_section(props_by_game)
        calc_html  = self._calculator()

        parts = [
            "<!DOCTYPE html><html lang=\"fr\"><head>",
            "<meta charset=\"UTF-8\">",
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
            "<title>NHL Signal - " + date_str + "</title>",
            self._css(),
            "</head><body>",
            self._nav(),
            "<div class=\"wrap\">",
            self._header(),
            self._grid(date_str, total_games, total_value),
            "<div id=\"tab-signal\">",
            "<div class=\"sec\">Bets recommandes - Edge minimum 5%</div>",
            bet_cards,
            "<div class=\"sec\" style=\"margin-top:1.5rem\">Tous les matchs</div>",
            self._table(rows),
            "</div>",
            "<div id=\"tab-props\" style=\"display:none\">",
            props_html if props_html else "<p class=\"no-bets\">Analyse joueurs disponible apres le prochain run.</p>",
            "</div>",
            "<div id=\"tab-calc\" style=\"display:none\">",
            calc_html,
            "</div>",
            self._disclaimer(gen_display),
            "</div>",
            self._script(),
            "</body></html>",
        ]

        os.makedirs("../docs", exist_ok=True)
        with open("../docs/index.html", "w", encoding="utf-8") as f:
            f.write("".join(parts))
        print("  docs/index.html genere")

    def _nav(self):
        return (
            "<nav>"
            "<div class=\"ni\">"
            "<span class=\"nt\">🏒 NHL Signal</span>"
            "<div class=\"tabs\">"
            "<button class=\"tab active\" onclick=\"showTab('tab-signal',this)\">Signal du jour</button>"
            "<button class=\"tab\" onclick=\"showTab('tab-props',this)\">Analyse joueurs</button>"
            "<button class=\"tab\" onclick=\"showTab('tab-calc',this)\">Calculateur</button>"
            "</div></div></nav>"
        )

    def _header(self):
        return (
            "<header>"
            "<h1>NHL Betting Signal</h1>"
            "<p>DraftKings · Modele Poisson · Kelly criterion · Alignements NHL.com valides · Props joueurs reels</p>"
            "</header>"
        )

    def _grid(self, date_str, total_games, total_value):
        return (
            "<div class=\"grid\">"
            "<div class=\"box\"><div class=\"l\">Date</div><div class=\"v\" style=\"font-size:17px\">" + date_str + "</div></div>"
            "<div class=\"box\"><div class=\"l\">Matchs analyses</div><div class=\"v\">" + str(total_games) + "</div></div>"
            "<div class=\"box\"><div class=\"l\">Bets +EV (>=5%)</div><div class=\"v\" style=\"color:var(--g)\">" + str(total_value) + "</div></div>"
            "<div class=\"box\"><div class=\"l\">Bookmaker</div><div class=\"v\" style=\"font-size:17px\">DraftKings</div></div>"
            "</div>"
        )

    def _bet_cards(self, value_bets):
        if not value_bets:
            return "<p class=\"no-bets\">Aucun bet avec edge superieur a 5% aujourd'hui.</p>"
        cards = ""
        for b in value_bets:
            ep  = b.get("edge_pct", 0)
            ec  = "#1D9E75" if ep >= 7 else ("#BA7517" if ep >= 5 else "#A32D2D")
            eb  = "#E1F5EE" if ep >= 7 else ("#FAEEDA" if ep >= 5 else "#FCEBEB")
            vd  = b.get("verdict", "")
            se  = "<div class=\"stat\" style=\"color:" + ec + "\"><span class=\"sl\">Edge</span><span class=\"sv\">+" + str(round(ep, 1)) + "%</span></div>"
            cards += (
                "<div class=\"bc\">"
                "<div class=\"bh\">"
                "<div>"
                "<div class=\"bt\">" + b.get("type", "") + "</div>"
                "<div class=\"bn\">" + b.get("bet", "") + "</div>"
                "<div class=\"bg\">" + b.get("game", "") + "</div>"
                "</div>"
                "<span class=\"vd\" style=\"background:" + eb + ";color:" + ec + "\">" + vd + "</span>"
                "</div>"
                "<div class=\"bs\">"
                "<div class=\"stat\"><span class=\"sl\">Cote DK</span><span class=\"sv\">" + str(round(b.get("b365_odds", 0), 2)) + "</span></div>"
                "<div class=\"stat\"><span class=\"sl\">Prob DK</span><span class=\"sv\">" + str(round(b.get("b365_implied", 0), 1)) + "%</span></div>"
                "<div class=\"stat\"><span class=\"sl\">Prob modele</span><span class=\"sv\">" + str(round(b.get("our_prob", 0), 1)) + "%</span></div>"
                + se +
                "<div class=\"stat\"><span class=\"sl\">1/4 Kelly</span><span class=\"sv\">" + str(round(b.get("kelly_fraction", 0), 1)) + "% BR</span></div>"
                "</div>"
                "</div>"
            )
        return cards

    def _table(self, rows):
        return (
            "<div class=\"tbl-wrap\"><table>"
            "<thead><tr>"
            "<th>Heure</th><th>Match</th>"
            "<th>ML Vis/Dom</th><th>PL +/-1.5</th>"
            "<th>Total O/U</th><th>Edges</th>"
            "</tr></thead>"
            "<tbody>"
            + (rows if rows else "<tr><td colspan=\"6\" style=\"color:var(--m);text-align:center\">Aucun match</td></tr>")
            + "</tbody></table></div>"
        )

    def _rows(self, signals):
        rows = ""
        for s in signals:
            g   = s["game"]
            ml  = g.get("markets", {}).get("moneyline", {})
            tt  = g.get("markets", {}).get("totals", {})
            pl  = g.get("markets", {}).get("puck_line", {})
            ao  = ml.get("away", {}).get("odds_decimal", "--")
            ho  = ml.get("home", {}).get("odds_decimal", "--")
            ol  = tt.get("over", {}).get("line", "--")
            oo  = tt.get("over", {}).get("odds_decimal", "--")
            uo  = tt.get("under", {}).get("odds_decimal", "--")
            pla = pl.get("away", {}).get("odds_decimal", "--")
            plh = pl.get("home", {}).get("odds_decimal", "--")
            ne  = len(s["edges"])
            badge = ("<span class=\"eb\">" + str(ne) + (" edges" if ne > 1 else " edge") + "</span>") if ne else ""
            try:
                t = datetime.fromisoformat(g["commence_time"]).astimezone(
                    pytz.timezone("America/Toronto")).strftime("%H:%M ET")
            except Exception:
                t = "--"
            def fmt(v): return str(round(v, 2)) if isinstance(v, (int, float)) else str(v)
            rows += (
                "<tr><td class=\"tm\">" + t + "</td>"
                "<td><strong>" + g.get("away_team", "") + "</strong><br><small>@ " + g.get("home_team", "") + "</small></td>"
                "<td class=\"num\">" + fmt(ao) + "<br><small>" + fmt(ho) + "</small></td>"
                "<td class=\"num\">" + fmt(pla) + "<br><small>" + fmt(plh) + "</small></td>"
                "<td class=\"num\">" + str(ol) + "<br><small>O:" + fmt(oo) + " U:" + fmt(uo) + "</small></td>"
                "<td>" + badge + "</td></tr>"
            )
        return rows

    def _props_section(self, props_by_game):
        if not props_by_game:
            return "<div style='color:var(--m);padding:1rem 0;font-size:13px'>Aucune analyse joueurs disponible.</div>"

        DEF_LABELS = {
            "elite": ("Elite (top 4)",   "#0F6E56"),
            "good":  ("Bonne (top 10)",  "#2563EB"),
            "avg":   ("Moyenne",          "#6B7280"),
            "weak":  ("Faible (bot 10)", "#B45309"),
        }

        html = ""
        for analysis in props_by_game:
            home  = analysis.get("home_team", "")
            away  = analysis.get("away_team", "")
            hg    = analysis.get("home_goalie", {})
            ag    = analysis.get("away_goalie", {})
            bets  = analysis.get("bets", [])
            hdef  = analysis.get("home_def", "avg")
            adef  = analysis.get("away_def", "avg")
            hshots = analysis.get("home_def_shots", 31.0)
            ashots = analysis.get("away_def_shots", 31.0)
            hga    = analysis.get("home_def_ga", 3.10)
            aga    = analysis.get("away_def_ga", 3.10)

            hdef_label, hdef_color = DEF_LABELS.get(hdef, ("Moyenne", "#6B7280"))
            adef_label, adef_color = DEF_LABELS.get(adef, ("Moyenne", "#6B7280"))

            html += (
                "<div class=\"pg\">"
                "<div class=\"ph\">"
                "<div class=\"pm\">" + away + " @ " + home + "</div>"
                "<div class=\"pd\">"
                "<span class=\"db\" style=\"color:" + hdef_color + ";border-color:" + hdef_color + "\">"
                "DEF " + home[:3].upper() + ": " + hdef_label + " · " + str(hshots) + " shots/m · " + str(hga) + " GA/m"
                "</span>"
                "<span class=\"db\" style=\"color:" + adef_color + ";border-color:" + adef_color + "\">"
                "DEF " + away[:3].upper() + ": " + adef_label + " · " + str(ashots) + " shots/m · " + str(aga) + " GA/m"
                "</span>"
                "</div></div>"
            )

            # Gardiens
            goalie_html = ""
            for g, label in [(hg, "DOM — " + home), (ag, "VIS — " + away)]:
                if g.get("name"):
                    sv = g.get("sv_pct", 0)
                    sv_color = "#0F6E56" if sv >= 0.915 else ("#B45309" if sv < 0.900 else "#6B7280")
                    goalie_html += (
                        "<div class=\"gb\">"
                        "<div class=\"gbn\">" + label + "</div>"
                        "<div class=\"gname\">" + g["name"] + "</div>"
                        "<div class=\"gs\">"
                        "<span>SV% <strong style=\"color:" + sv_color + "\">" + str(sv) + "</strong></span>"
                        "<span>Saves/m <strong>" + str(g.get("saves_pg", "--")) + "</strong></span>"
                        "<span>GAA <strong>" + str(g.get("gaa", "--")) + "</strong></span>"
                        "</div></div>"
                    )
            if goalie_html:
                html += "<div class=\"gr\">" + goalie_html + "</div>"

            # Bets +EV
            if bets:
                html += "<div class=\"bets-list\">"
                for b in bets:
                    edge = b.get("edge_pct", 0)
                    prob = b.get("our_prob", 0)
                    kelly = b.get("kelly", 0)
                    market = b.get("market", "")
                    name = b.get("name", "")
                    pos  = b.get("position", "")
                    team = b.get("team", "")
                    opp  = b.get("opponent", "")
                    toi  = b.get("toi", "--")
                    ctx  = b.get("context", "")
                    l5   = b.get("last5", "")
                    avg  = b.get("avg", "")
                    dk_odds = b.get("dk_odds", "-115")
                    dk_impl = b.get("dk_implied", 52.4)

                    ec = "#0F6E56" if edge >= 15 else "#BA7517"
                    eb = "#E1F5EE" if edge >= 15 else "#FAEEDA"
                    verdict = "🔥 FORT" if edge >= 15 else "✅ BON"

                    html += (
                        "<div class=\"bet-row\">"
                        "<div class=\"bet-left\">"
                        "<div class=\"bet-player\">"
                        "<span class=\"bet-name\">" + name + "</span>"
                        "<span class=\"bet-pos\">" + pos + "</span>"
                        "<span class=\"bet-team\">" + team[:3].upper() + " vs " + opp[:3].upper() + " · " + toi + "</span>"
                        "</div>"
                        "<div class=\"bet-market\">" + market + "</div>"
                        "<div class=\"bet-ctx\">" + ctx + " · " + avg + " · " + l5 + "</div>"
                        "</div>"
                        "<div class=\"bet-right\">"
                        "<div class=\"bet-badge\" style=\"background:" + eb + ";color:" + ec + "\">" + verdict + "</div>"
                        "<div class=\"bet-odds\">"
                        "<div><span class=\"bo-label\">DK</span><span class=\"bo-val\">" + dk_odds + "</span></div>"
                        "<div><span class=\"bo-label\">Notre prob</span><span class=\"bo-val\" style=\"color:" + ec + "\">" + str(prob) + "%</span></div>"
                        "<div><span class=\"bo-label\">DK implied</span><span class=\"bo-val\">" + str(dk_impl) + "%</span></div>"
                        "<div><span class=\"bo-label\">Edge</span><span class=\"bo-val\" style=\"color:" + ec + ";font-weight:700\">+" + str(edge) + "%</span></div>"
                        "<div><span class=\"bo-label\">1/4 Kelly</span><span class=\"bo-val\">" + str(kelly) + "% BR</span></div>"
                        "</div>"
                        "</div>"
                        "</div>"
                    )
                html += "</div>"
            else:
                html += "<div class=\"no-bets\">Aucun bet +EV identifie pour ce match (edge < 8%).</div>"

            html += "</div>"

        return html


    def _calculator(self):
        return (
            "<div class=\"calc\">"
            "<div class=\"sec\">Calculateur d'edge manuel</div>"
            "<div class=\"cform\">"
            "<div class=\"cf\">"
            "<label>Cote bookmaker</label>"
            "<input id=\"od\" type=\"number\" step=\"0.01\" min=\"1.01\" placeholder=\"ex: 1.85\">"
            "</div>"
            "<div class=\"cf\">"
            "<label>Notre probabilite (%)</label>"
            "<input id=\"pr\" type=\"number\" step=\"0.1\" min=\"1\" max=\"99\" placeholder=\"ex: 58.5\">"
            "</div>"
            "<button onclick=\"calcEdge()\">Calculer l'edge</button>"
            "</div>"
            "<div id=\"cres\" style=\"display:none\" class=\"cres\">"
            "<div class=\"cr-grid\">"
            "<div class=\"cr-stat\"><span>Edge</span><strong id=\"cep\"></strong></div>"
            "<div class=\"cr-stat\"><span>Prob implicite cote</span><strong id=\"cip\"></strong></div>"
            "<div class=\"cr-stat\"><span>1/4 Kelly</span><strong id=\"ckl\"></strong></div>"
            "<div class=\"cr-stat\"><span>Verdict</span><strong id=\"cvd\"></strong></div>"
            "</div>"
            "</div>"
            "<div class=\"sec\" style=\"margin-top:1.5rem\">Historique</div>"
            "<div id=\"ch\"></div>"
            "</div>"
        )

    def _disclaimer(self, gen_display):
        return (
            "<p class=\"disc\">"
            "Signal informatif et educatif uniquement. Aucun resultat garanti. "
            "Verifiez les cotes directement sur DraftKings avant de parier. "
            "Jouez de facon responsable. 18+"
            "</p>"
            "<p class=\"upd\">Genere le " + gen_display + "</p>"
        )

    def _script(self):
        return (
            "<script>"
            "function showTab(id,btn){"
            "document.querySelectorAll('[id^=\"tab-\"]').forEach(function(el){el.style.display='none';});"
            "document.getElementById(id).style.display='block';"
            "document.querySelectorAll('.tab').forEach(function(b){b.classList.remove('active');});"
            "btn.classList.add('active');}"
            "function calcEdge(){"
            "var od=parseFloat(document.getElementById('od').value);"
            "var pr=parseFloat(document.getElementById('pr').value);"
            "if(isNaN(od)||isNaN(pr)||od<1.01||pr<1||pr>99){alert('Valeurs invalides');return;}"
            "var ip=1/od*100;"
            "var ep=pr-ip;"
            "var kl=(pr/100-(1-pr/100)/(od-1))/4*100;"
            "var ec=ep>=7?'#0F6E56':ep>=4?'#BA7517':'#A32D2D';"
            "var vd=ep>=7?'Forte valeur':ep>=4?'Valeur moderee':'Pas de valeur';"
            "document.getElementById('cep').innerHTML='<span style=\"color:'+ec+'\">'+(ep>=0?'+':'')+ep.toFixed(1)+'%</span>';"
            "document.getElementById('cip').textContent=ip.toFixed(1)+'%';"
            "document.getElementById('ckl').textContent=Math.max(0,kl).toFixed(1)+'% bankroll';"
            "document.getElementById('cvd').innerHTML='<span style=\"color:'+ec+'\">'+vd+'</span>';"
            "document.getElementById('cres').style.display='block';"
            "var hist=JSON.parse(localStorage.getItem('nh')||'[]');"
            "hist.unshift({od:od,pr:pr,ep:ep});"
            "localStorage.setItem('nh',JSON.stringify(hist.slice(0,10)));"
            "var el=document.getElementById('ch');"
            "el.innerHTML=hist.slice(0,8).map(function(h){"
            "var ec2=h.ep>=7?'#0F6E56':h.ep>=4?'#BA7517':'#A32D2D';"
            "return '<div class=\"hi\"><span>Cote '+h.od+' · Prob '+h.pr+'%</span>"
            "<span class=\"he\" style=\"color:'+ec2+'\">'+(h.ep>=0?'+':'')+h.ep.toFixed(1)+'%</span></div>';"
            "}).join('');}"
            "</script>"
        )

    def _css(self):
        return (
            "<style>"
            ":root{--bg:#f8f8f7;--s:#fff;--b:rgba(0,0,0,.1);--t:#1a1a1a;--m:#666;--g:#1D9E75;--a:#BA7517;--r:12px;--rs:8px}"
            "@media(prefers-color-scheme:dark){:root{--bg:#111110;--s:#1c1c1b;--b:rgba(255,255,255,.1);--t:#f0efe8;--m:#888}}"
            "*{box-sizing:border-box;margin:0;padding:0}"
            "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--t);line-height:1.6;font-size:15px}"
            "nav{border-bottom:.5px solid var(--b);background:var(--s);position:sticky;top:0;z-index:10}"
            ".ni{max-width:960px;margin:0 auto;padding:.75rem 1rem;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px}"
            ".nt{font-weight:600;font-size:15px}"
            ".tabs{display:flex;gap:4px}"
            ".tab{background:transparent;border:.5px solid var(--b);border-radius:6px;padding:5px 12px;font-size:13px;cursor:pointer;color:var(--m)}"
            ".tab.active{background:var(--t);color:var(--bg);border-color:var(--t)}"
            ".wrap{max-width:960px;margin:0 auto;padding:1.5rem 1rem}"
            "header{border-bottom:.5px solid var(--b);padding-bottom:1rem;margin-bottom:1.5rem}"
            "header h1{font-size:22px;font-weight:600}"
            "header p{font-size:13px;color:var(--m);margin-top:4px}"
            ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:1.5rem}"
            ".box{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);padding:.875rem 1rem}"
            ".box .l{font-size:11px;color:var(--m)}"
            ".box .v{font-size:24px;font-weight:600;margin-top:2px}"
            ".sec{font-size:11px;font-weight:600;color:var(--m);text-transform:uppercase;letter-spacing:.06em;margin:1.5rem 0 .75rem}"
            ".bc{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);padding:1rem 1.25rem;margin-bottom:.75rem}"
            ".bh{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:6px;margin-bottom:.75rem}"
            ".bt{font-size:10px;color:var(--m);text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px}"
            ".bn{font-size:18px;font-weight:600}"
            ".bg{font-size:12px;color:var(--m);margin-top:2px}"
            ".vd{font-size:12px;font-weight:500;padding:3px 10px;border-radius:20px}"
            ".bs{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:8px}"
            ".stat{background:var(--bg);border-radius:6px;padding:6px 10px}"
            ".sl{display:block;font-size:10px;color:var(--m)}"
            ".sv{font-size:15px;font-weight:600}"
            ".no-bets{color:var(--m);font-size:13px;padding:.5rem 0}"
            ".tbl-wrap{overflow-x:auto}"
            "table{width:100%;border-collapse:collapse;font-size:13px}"
            "th{text-align:left;padding:.5rem .75rem;border-bottom:.5px solid var(--b);font-size:11px;color:var(--m);font-weight:500}"
            "td{padding:.5rem .75rem;border-bottom:.5px solid var(--b)}"
            ".tm{color:var(--m);white-space:nowrap;font-size:12px}"
            ".num{text-align:right;font-size:13px}"
            ".eb{background:#E1F5EE;color:#0F6E56;font-size:11px;padding:2px 8px;border-radius:6px;font-weight:500}"
            "@media(prefers-color-scheme:dark){.eb{background:#085041;color:#9FE1CB}}"
            ".calc{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);padding:1.25rem}"
            ".cform{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin-bottom:1rem}"
            ".cf{display:flex;flex-direction:column;gap:4px}"
            ".cf label{font-size:12px;color:var(--m)}"
            ".cf input{padding:8px 10px;border:.5px solid var(--b);border-radius:6px;background:var(--bg);color:var(--t);font-size:14px;width:160px}"
            ".calc button{padding:9px 18px;background:var(--t);color:var(--bg);border:none;border-radius:6px;font-size:14px;cursor:pointer;font-weight:500}"
            ".cres{background:var(--bg);border:.5px solid var(--b);border-radius:var(--rs);padding:1rem;margin-bottom:1rem}"
            ".cr-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}"
            ".cr-stat{display:flex;flex-direction:column;gap:2px}"
            ".cr-stat span{font-size:11px;color:var(--m)}"
            ".cr-stat strong{font-size:16px;font-weight:600}"
            ".hi{display:flex;justify-content:space-between;padding:.4rem 0;border-bottom:.5px solid var(--b);font-size:13px}"
            ".he{font-weight:600}"
            ".disc{font-size:11px;color:var(--m);margin-top:2rem;padding-top:1rem;border-top:.5px solid var(--b);line-height:1.7}"
            ".upd{font-size:11px;color:var(--m);text-align:right;margin-top:.5rem}"
            "/* PROPS JOUEURS */"
            ".bets-list{display:flex;flex-direction:column;gap:.5rem}"
            ".bet-row{display:flex;justify-content:space-between;align-items:stretch;background:var(--bg);border:.5px solid var(--b);border-radius:var(--rs);padding:.875rem 1rem;gap:1rem;flex-wrap:wrap}"
            ".bet-left{flex:1;min-width:200px;display:flex;flex-direction:column;gap:4px}"
            ".bet-right{display:flex;flex-direction:column;align-items:flex-end;gap:6px;min-width:140px}"
            ".bet-player{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:2px}"
            ".bet-name{font-size:15px;font-weight:700}"
            ".bet-pos{font-size:11px;color:var(--m);background:var(--s);padding:2px 5px;border-radius:4px;border:.5px solid var(--b)}"
            ".bet-team{font-size:11px;color:var(--m)}"
            ".bet-market{font-size:14px;font-weight:600;color:var(--t)}"
            ".bet-ctx{font-size:11px;color:var(--m);line-height:1.5}"
            ".bet-badge{font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;letter-spacing:.03em}"
            ".bet-odds{display:flex;flex-direction:column;gap:3px;text-align:right}"
            ".bo-label{font-size:10px;color:var(--m);margin-right:4px}"
            ".bo-val{font-size:13px;font-weight:600}"
            ".pg{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);padding:1.25rem;margin-bottom:1rem}"
            ".ph{margin-bottom:1rem}"
            ".pm{font-size:16px;font-weight:600;margin-bottom:.5rem}"
            ".pd{display:flex;flex-wrap:wrap;gap:6px}"
            ".db{font-size:11px;padding:3px 8px;border-radius:4px;border:.5px solid;font-weight:500}"
            ".gr{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:1rem}"
            ".gb{background:var(--bg);border:.5px solid var(--b);border-radius:var(--rs);padding:.75rem}"
            ".gbn{font-size:10px;color:var(--m);text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px}"
            ".gname{font-size:14px;font-weight:600;margin-bottom:.4rem}"
            ".gs{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--m)}"
            ".pcards{display:flex;flex-direction:column;gap:.75rem}"
            ".pc{background:var(--bg);border:.5px solid var(--b);border-radius:var(--rs);padding:1rem}"
            ".pch{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.75rem;flex-wrap:wrap;gap:4px}"
            ".pname{font-size:15px;font-weight:600;margin-right:.4rem}"
            ".ppos{font-size:11px;color:var(--m);background:var(--s);padding:2px 6px;border-radius:4px;border:.5px solid var(--b)}"
            ".pteam{font-size:11px;color:var(--m);margin-top:4px}"
            ".pstats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:.6rem}"
            ".pstat{background:var(--s);border:.5px solid var(--b);border-radius:6px;padding:.6rem .75rem}"
            ".pstat-title{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--m);margin-bottom:.4rem}"
            ".pstat-row{font-size:11px;color:var(--m);display:flex;flex-direction:column;gap:2px;margin-bottom:.4rem}"
            ".pstat-row strong{color:var(--t)}"
            ".pstat-rec{font-size:12px;font-weight:600}"
            ".pbet{display:flex;align-items:center;gap:10px;background:var(--s);border:.5px solid;border-radius:8px;padding:.6rem .9rem;margin-bottom:.75rem;flex-wrap:wrap}"
            ".pbet-tag{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--m);white-space:nowrap}"
            ".pbet-main{font-size:16px;font-weight:700;flex:1}"
            ".pbet-prob{font-size:12px;color:var(--m);white-space:nowrap}"
            ".preason{font-size:11px;color:var(--m);background:var(--s);border:.5px solid var(--b);border-radius:4px;padding:.4rem .6rem;line-height:1.5}"
            "@media(max-width:600px){"
            ".pstats{grid-template-columns:1fr}"
            ".gr{grid-template-columns:1fr}"
            ".cr-grid{grid-template-columns:repeat(2,1fr)}"
            "}"
            "</style>"
        )

    def generate_empty_report(self):
        tz = pytz.timezone("America/Toronto")
        data = {
            "generated_at": datetime.now(tz).isoformat(),
            "date":         datetime.now(tz).strftime("%Y-%m-%d"),
            "total_games":      0,
            "total_value_bets": 0,
            "signals":          [],
            "value_bets":       [],
            "props_analysis":   [],
        }
        self.generate_html(data)
        os.makedirs("../docs", exist_ok=True)
        with open("../docs/signal.json", "w") as f:
            json.dump({"date": "", "games": [], "value_bets": []}, f)
