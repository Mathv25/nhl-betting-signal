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
        date_str     = data.get("date","")
        value_bets   = data.get("value_bets",[])
        signals      = data.get("signals",[])
        gen_at       = data.get("generated_at","")
        total_games  = data.get("total_games",0)
        total_value  = data.get("total_value_bets",0)
        props_by_game = data.get("props_analysis",[])

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
            "<div class=\"sec\">Bets recommandes - Edge minimum 3%</div>",
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

        gh_token = getattr(self, "gh_token", "")
        html_content = "\n".join(parts).replace("GH_TOKEN_PLACEHOLDER", gh_token)

        os.makedirs("docs", exist_ok=True)
        with open("docs/index.html","w",encoding="utf-8") as f:
            f.write(html_content)
        print("  docs/index.html genere")

    def _nav(self):
        return (
            "<nav><div class=\"nav-inner\">"
            "<span class=\"nav-title\">NHL Signal</span>"
            "<div class=\"nav-tabs\">"
            "<button class=\"tab active\" onclick=\"showTab('signal',this)\">Signal du jour</button>"
            "<button class=\"tab\" onclick=\"showTab('props',this)\">Analyse joueurs</button>"
            "<button class=\"tab\" onclick=\"showTab('calc',this)\">Calculateur</button>"
            "</div>"
            "<button class=\"refresh-btn\" onclick=\"triggerRefresh()\" id=\"refresh-btn\">Refresh</button>"
            "</div></nav>"
        )

    def _bet_cards(self, value_bets):
        if not value_bets:
            return "<p class=\"no-bets\">Aucun bet avec edge superieur a 3% aujourd'hui.</p>"
        cards = ""
        for b in value_bets:
            ep   = b.get("edge_pct",0)
            ec   = "ef" if ep>=8 else ("eg" if ep>=5 else "eo")
            note = b.get("note","")
            n_h  = ("<div class=\"bet-note\">" + note + "</div>") if note else ""
            se   = "<div class=\"stat " + ec + "\"><span class=\"sl\">Edge</span><span class=\"sv\">+" + str(round(ep,1)) + "%</span></div>"
            cards += (
                "<div class=\"bet-card\">"
                "<div class=\"bh\"><span class=\"bg\">" + b.get("game","") + "</span>"
                "<span class=\"bv\">" + b.get("verdict","") + "</span></div>"
                "<div class=\"bt\">" + b.get("type","") + "</div>"
                "<div class=\"bn\">" + b.get("bet","") + "</div>"
                + n_h +
                "<div class=\"bs\">"
                "<div class=\"stat\"><span class=\"sl\">Cote DK</span><span class=\"sv\">" + str(round(b.get("b365_odds",0),2)) + "</span></div>"
                "<div class=\"stat\"><span class=\"sl\">Prob DK</span><span class=\"sv\">" + str(round(b.get("b365_implied",0),1)) + "%</span></div>"
                "<div class=\"stat\"><span class=\"sl\">Prob modele</span><span class=\"sv\">" + str(round(b.get("our_prob",0),1)) + "%</span></div>"
                + se +
                "<div class=\"stat\"><span class=\"sl\">1/4 Kelly</span><span class=\"sv\">" + str(round(b.get("kelly_fraction",0),1)) + "% BR</span></div>"
                "</div></div>"
            )
        return cards

    def _rows(self, signals):
        rows = ""
        for s in signals:
            g   = s["game"]
            ml  = g.get("markets",{}).get("moneyline",{})
            tt  = g.get("markets",{}).get("totals",{})
            pl  = g.get("markets",{}).get("puck_line",{})
            ao  = ml.get("away",{}).get("odds_decimal","--")
            ho  = ml.get("home",{}).get("odds_decimal","--")
            ol  = tt.get("over",{}).get("line","--")
            oo  = tt.get("over",{}).get("odds_decimal","--")
            uo  = tt.get("under",{}).get("odds_decimal","--")
            pla = pl.get("away",{}).get("odds_decimal","--")
            plh = pl.get("home",{}).get("odds_decimal","--")
            ne  = len(s["edges"])
            badge = ("<span class=\"eb\">" + str(ne) + (" edges" if ne>1 else " edge") + "</span>") if ne else ""
            try:
                t = datetime.fromisoformat(g["commence_time"]).astimezone(
                    pytz.timezone("America/Toronto")).strftime("%H:%M ET")
            except Exception:
                t = "--"
            def fmt(v): return str(round(v,2)) if isinstance(v,(int,float)) else str(v)
            rows += (
                "<tr><td class=\"tm\">" + t + "</td>"
                "<td><strong>" + g.get("away_team","") + "</strong><br><small>@ " + g.get("home_team","") + "</small></td>"
                "<td class=\"num\">" + fmt(ao) + "<br><small>" + fmt(ho) + "</small></td>"
                "<td class=\"num\">" + fmt(pla) + "<br><small>" + fmt(plh) + "</small></td>"
                "<td class=\"num\">" + str(ol) + "<br><small>O:" + fmt(oo) + " U:" + fmt(uo) + "</small></td>"
                "<td>" + badge + "</td></tr>"
            )
        return rows

    def _props_section(self, props_by_game):
        if not props_by_game:
            return ""
        DEF_LABELS = {"elite":"Elite","good":"Bonne","avg":"Moyenne","weak":"Faible"}
        html = ""
        for analysis in props_by_game:
            home  = analysis.get("home_team","")
            away  = analysis.get("away_team","")
            hg    = analysis.get("home_goalie",{})
            ag    = analysis.get("away_goalie",{})
            props = analysis.get("props",[])
            hdef  = analysis.get("home_def","avg")
            adef  = analysis.get("away_def","avg")

            html += (
                "<div class=\"pg\">"
                "<div class=\"ph\">"
                "<span class=\"pm\">" + away + " @ " + home + "</span>"
                "<div class=\"pd\">"
                "<span class=\"db db-" + hdef + "\">DEF " + home[:3] + ": " + DEF_LABELS[hdef] + "</span>"
                "<span class=\"db db-" + adef + "\">DEF " + away[:3] + ": " + DEF_LABELS[adef] + "</span>"
                "</div></div>"
            )

            goalies = [g for g in [(hg,"DOM"),(ag,"VIS")] if g[0].get("name")]
            if goalies:
                html += "<div class=\"gr\">"
                for g, side in goalies:
                    html += (
                        "<div class=\"gb\">"
                        "<span class=\"gbl\">" + side + " — " + g.get("name","") + "</span>"
                        "<div class=\"gs\">"
                        "<span>SV%: <strong>" + str(round(g.get("sv_pct",0.910),3)) + "</strong></span>"
                        "<span>Saves/match: <strong>" + str(g.get("saves_pg","--")) + "</strong></span>"
                        "<span>GAA: <strong>" + str(g.get("gaa","--")) + "</strong></span>"
                        "</div></div>"
                    )
                html += "</div>"

            if props:
                html += "<div class=\"ptw\"><table class=\"pt\">"
                html += ("<thead><tr>"
                         "<th>Joueur</th><th>Pos</th><th>Eq.</th>"
                         "<th>Shots/match</th><th>Adj. vs defense</th><th>P(Over)</th>"
                         "<th>Pts/match</th><th>P(Over 0.5)</th><th>TOI</th>"
                         "</tr></thead><tbody>")
                for p in props:
                    sc = "#1D9E75" if p["shots_over_pct"]>=60 else ("#BA7517" if p["shots_over_pct"]>=50 else "var(--m)")
                    pc = "#1D9E75" if p["pts_over_pct"]>=65 else ("#BA7517" if p["pts_over_pct"]>=55 else "var(--m)")
                    html += (
                        "<tr>"
                        "<td><strong>" + p["name"] + "</strong></td>"
                        "<td>" + p["position"] + "</td>"
                        "<td>" + p["team"][:3] + "</td>"
                        "<td>" + str(p["shots_pg"]) + "</td>"
                        "<td>" + str(p["shots_pg_adj"]) + " (O" + str(p["shots_line"]) + ")</td>"
                        "<td style=\"color:" + sc + ";font-weight:500\">" + str(p["shots_over_pct"]) + "%</td>"
                        "<td>" + str(p["points_pg"]) + "</td>"
                        "<td style=\"color:" + pc + ";font-weight:500\">" + str(p["pts_over_pct"]) + "%</td>"
                        "<td>" + p["toi"] + "</td>"
                        "</tr>"
                    )
                html += "</tbody></table></div>"
            html += "</div>"
        return html

    def _calculator(self):
        return (
            "<div class=\"cc\">"
            "<p class=\"ci\">Entre une cote bet365 pour calculer l'edge via le modele Poisson.</p>"
            "<div class=\"cr2\">"
            "<div><label class=\"lbl\">Joueur</label><input type=\"text\" id=\"cp\" placeholder=\"Nathan MacKinnon\" /></div>"
            "<div><label class=\"lbl\">Marche</label>"
            "<select id=\"cm\"><option value=\"shots\">Shots on goal</option>"
            "<option value=\"points\">Points</option><option value=\"goals\">Buts</option>"
            "<option value=\"assists\">Passes</option><option value=\"saves\">Saves (gardien)</option>"
            "</select></div></div>"
            "<div class=\"cr3\">"
            "<div><label class=\"lbl\">Direction</label>"
            "<select id=\"cd\"><option value=\"over\">Over</option><option value=\"under\">Under</option></select></div>"
            "<div><label class=\"lbl\">Ligne</label><input type=\"number\" id=\"cl\" step=\"0.5\" value=\"2.5\" /></div>"
            "<div><label class=\"lbl\">Cote bet365</label><input type=\"number\" id=\"co\" step=\"0.01\" value=\"1.85\" /></div>"
            "</div>"
            "<div class=\"cr2\">"
            "<div><label class=\"lbl\">Moyenne joueur (10 derniers matchs)</label>"
            "<input type=\"number\" id=\"ca\" step=\"0.1\" value=\"3.2\" /></div>"
            "<div><label class=\"lbl\">Defense adverse</label>"
            "<select id=\"cdf\">"
            "<option value=\"elite\">Elite — CAR, FLA, BOS, DAL</option>"
            "<option value=\"good\" selected>Bonne — VGK, WPG, TBL</option>"
            "<option value=\"avg\">Moyenne — MTL, OTT, BUF, NYR</option>"
            "<option value=\"weak\">Faible — CHI, SJS, ANA, CBJ</option>"
            "</select></div></div>"
            "<button class=\"cbtn\" onclick=\"calcEdge()\">Calculer l'edge</button>"
            "</div>"
            "<div id=\"cres\" style=\"display:none\" class=\"cc\">"
            "<div class=\"rg\">"
            "<div class=\"rb\"><span class=\"rl\">Prob. modele</span><span class=\"rv\" id=\"rp\">-</span></div>"
            "<div class=\"rb\"><span class=\"rl\">Prob. b365</span><span class=\"rv\" id=\"ri\">-</span></div>"
            "<div class=\"rb\"><span class=\"rl\">Edge</span><span class=\"rv\" id=\"re\">-</span></div>"
            "<div class=\"rb\"><span class=\"rl\">1/4 Kelly</span><span class=\"rv\" id=\"rk\">-</span></div>"
            "</div>"
            "<div id=\"rv\" class=\"vb\"></div>"
            "<div id=\"rn\" class=\"cn\"></div>"
            "</div>"
            "<div class=\"sec\" style=\"margin-top:1.25rem\">Historique</div>"
            "<div id=\"ch\"></div>"
        )

    def _css(self):
        return (
            "<style>"
            ":root{--bg:#f8f8f7;--s:#fff;--b:rgba(0,0,0,.1);--t:#1a1a1a;--m:#666;"
            "--g:#1D9E75;--a:#BA7517;--r:12px;--rs:8px}"
            "@media(prefers-color-scheme:dark){:root{--bg:#111110;--s:#1c1c1b;"
            "--b:rgba(255,255,255,.1);--t:#f0efe8;--m:#888}}"
            "*{box-sizing:border-box;margin:0;padding:0}"
            "body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;"
            "background:var(--bg);color:var(--t);line-height:1.6;font-size:15px}"
            "nav{background:var(--s);border-bottom:.5px solid var(--b);position:sticky;top:0;z-index:10}"
            ".nav-inner{max-width:960px;margin:0 auto;padding:.75rem 1rem;"
            "display:flex;justify-content:space-between;align-items:center}"
            ".nav-title{font-size:15px;font-weight:500}"
            ".nav-tabs{display:flex;gap:6px}"
            ".refresh-btn{padding:6px 14px;border-radius:var(--rs);border:.5px solid var(--b);"
            "font-size:13px;cursor:pointer;background:transparent;color:var(--m)}"
            ".refresh-btn:hover{background:var(--bg);color:var(--t)}"
            ".refresh-btn.loading{opacity:.5;cursor:not-allowed}"
            ".tab{padding:6px 14px;border-radius:var(--rs);border:.5px solid var(--b);"
            "font-size:13px;cursor:pointer;background:transparent;color:var(--m)}"
            ".tab.active{background:var(--bg);color:var(--t);font-weight:500}"
            ".wrap{max-width:960px;margin:0 auto;padding:1.25rem 1rem}"
            "header{border-bottom:.5px solid var(--b);padding-bottom:1rem;margin-bottom:1.25rem}"
            "header h1{font-size:20px;font-weight:500}"
            "header p{font-size:13px;color:var(--m);margin-top:4px}"
            ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-bottom:1.25rem}"
            ".box{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);padding:.75rem 1rem}"
            ".box .l{font-size:11px;color:var(--m)}.box .v{font-size:22px;font-weight:500;margin-top:2px}"
            ".sec{font-size:11px;font-weight:500;color:var(--m);text-transform:uppercase;letter-spacing:.06em;margin:.75rem 0 .5rem}"
            ".bet-card{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);padding:1rem 1.25rem;margin-bottom:.625rem}"
            ".bh{display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;margin-bottom:3px}"
            ".bg{font-size:12px;color:var(--m)}.bv{font-size:12px;font-weight:500}"
            ".bt{font-size:10px;color:var(--m);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}"
            ".bn{font-size:17px;font-weight:500;margin-bottom:.5rem}"
            ".bet-note{font-size:12px;color:var(--m);margin-bottom:.5rem;background:var(--bg);border-radius:var(--rs);padding:5px 10px;border-left:2px solid var(--b)}"
            ".bs{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:6px}"
            ".stat{background:var(--bg);border-radius:var(--rs);padding:6px 9px}"
            ".sl{font-size:10px;color:var(--m);display:block}"
            ".sv{font-size:13px;font-weight:500;display:block;margin-top:1px}"
            ".ef .sv{color:var(--g)}.eg .sv{color:var(--g)}.eo .sv{color:var(--a)}"
            ".no-bets{color:var(--m);font-style:italic;padding:1rem 0}"
            ".tbl-wrap{overflow-x:auto}"
            "table{width:100%;border-collapse:collapse;background:var(--s);border-radius:var(--r);overflow:hidden;border:.5px solid var(--b);font-size:12px;min-width:520px}"
            "th{background:var(--bg);padding:8px 10px;text-align:left;font-weight:500;color:var(--m);font-size:10px;text-transform:uppercase;letter-spacing:.05em}"
            "td{padding:8px 10px;border-top:.5px solid var(--b);vertical-align:top}"
            "td small{color:var(--m);font-size:11px}.tm{color:var(--m);font-size:12px;white-space:nowrap}.num{font-variant-numeric:tabular-nums}"
            ".eb{background:#E1F5EE;color:#0F6E56;font-size:10px;padding:2px 7px;border-radius:4px;font-weight:500}"
            "@media(prefers-color-scheme:dark){.eb{background:#085041;color:#9FE1CB}}"
            ".pg{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);padding:1rem 1.25rem;margin-bottom:.75rem}"
            ".ph{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;margin-bottom:.75rem}"
            ".pm{font-size:15px;font-weight:500}"
            ".pd{display:flex;gap:6px;flex-wrap:wrap}"
            ".db{font-size:11px;padding:2px 8px;border-radius:4px;font-weight:500}"
            ".db-elite{background:#E1F5EE;color:#0F6E56}.db-good{background:#EAF3DE;color:#3B6D11}"
            ".db-avg{background:#FAEEDA;color:#633806}.db-weak{background:#FCEBEB;color:#791F1F}"
            "@media(prefers-color-scheme:dark){.db-elite{background:#085041;color:#9FE1CB}.db-good{background:#173404;color:#C0DD97}.db-avg{background:#412402;color:#FAC775}.db-weak{background:#501313;color:#F7C1C1}}"
            ".gr{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:.75rem}"
            ".gb{background:var(--bg);border-radius:var(--rs);padding:10px 12px}"
            ".gbl{font-size:12px;font-weight:500;display:block;margin-bottom:6px}"
            ".gs{display:flex;gap:12px;font-size:12px;color:var(--m);flex-wrap:wrap}"
            ".gs strong{color:var(--t)}"
            ".ptw{overflow-x:auto}"
            ".pt{font-size:12px;min-width:700px}"
            ".cc{background:var(--s);border:.5px solid var(--b);border-radius:var(--r);padding:1rem 1.25rem;margin-bottom:.75rem}"
            ".ci{font-size:13px;color:var(--m);margin-bottom:.875rem}"
            ".cr2{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}"
            ".cr3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px}"
            ".lbl{font-size:12px;color:var(--m);display:block;margin-bottom:4px}"
            "input,select{width:100%;font-size:14px;padding:7px 10px;border:.5px solid var(--b);border-radius:var(--rs);background:var(--bg);color:var(--t)}"
            ".cbtn{width:100%;padding:10px;font-size:14px;font-weight:500;cursor:pointer;border:.5px solid var(--b);border-radius:var(--rs);background:var(--t);color:var(--bg);margin-top:4px}"
            ".rg{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:.875rem}"
            ".rb{background:var(--bg);border-radius:var(--rs);padding:9px 11px}"
            ".rl{font-size:10px;color:var(--m);display:block}"
            ".rv{font-size:18px;font-weight:500;display:block;margin-top:2px}"
            ".vb{border-radius:var(--rs);padding:9px 13px;font-size:13px;font-weight:500}"
            ".vf{background:#E1F5EE;color:#0F6E56}.vg{background:#EAF3DE;color:#3B6D11}"
            ".vo{background:#FAEEDA;color:#633806}.vb2{background:#FCEBEB;color:#791F1F}"
            ".cn{font-size:12px;color:var(--m);margin-top:8px;padding:7px 10px;background:var(--bg);border-radius:var(--rs)}"
            ".hi{border-top:.5px solid var(--b);padding:8px 0;font-size:13px;display:flex;justify-content:space-between;align-items:center}"
            ".he{font-size:12px;font-weight:500;padding:2px 8px;border-radius:4px}"
            ".disc{font-size:11px;color:var(--m);margin-top:1.25rem;padding-top:.75rem;border-top:.5px solid var(--b);line-height:1.7}"
            ".upd{font-size:11px;color:var(--m);text-align:right;margin-top:.4rem}"
            "@media(max-width:600px){.cr2,.cr3{grid-template-columns:1fr}.rg{grid-template-columns:repeat(2,1fr)}.bs{grid-template-columns:repeat(2,1fr)}.gr{grid-template-columns:1fr}}"
            "</style>"
        )

    def _header(self):
        return (
            "<header>"
            "<h1>NHL Betting Signal</h1>"
            "<p>Signal auto <strong>DraftKings</strong> · Analyse joueurs stats reelles NHL.com · Calculateur edge bet365 · 1/4 Kelly</p>"
            "</header>"
        )

    def _grid(self, date_str, total_games, total_value):
        return (
            "<div class=\"grid\">"
            "<div class=\"box\"><div class=\"l\">Date</div><div class=\"v\" style=\"font-size:15px\">" + date_str + "</div></div>"
            "<div class=\"box\"><div class=\"l\">Matchs</div><div class=\"v\">" + str(total_games) + "</div></div>"
            "<div class=\"box\"><div class=\"l\">Bets +EV</div><div class=\"v\" style=\"color:var(--g)\">" + str(total_value) + "</div></div>"
            "<div class=\"box\"><div class=\"l\">Ref.</div><div class=\"v\" style=\"font-size:14px\">DraftKings</div></div>"
            "</div>"
        )

    def _table(self, rows):
        empty = "<tr><td colspan=\"6\" style=\"color:var(--m);text-align:center;padding:1rem\">Aucun match</td></tr>"
        return (
            "<div class=\"tbl-wrap\"><table>"
            "<thead><tr><th>Heure</th><th>Match</th><th>ML</th><th>PL</th><th>Total</th><th>Edges</th></tr></thead>"
            "<tbody>" + (rows if rows else empty) + "</tbody>"
            "</table></div>"
        )

    def _disclaimer(self, gen_display):
        return (
            "<p class=\"disc\">Signal informatif uniquement. Verifie les cotes sur bet365 avant de parier. Aucun resultat garanti. 18+</p>"
            "<p class=\"upd\">Genere le " + gen_display + "</p>"
        )

    def _script(self):
        return (
            "<script>"
            "function triggerRefresh(){"
            "var btn=document.getElementById('refresh-btn');"
            "btn.textContent='En cours...';"
            "btn.classList.add('loading');"
            "btn.disabled=true;"
            "fetch('https://api.github.com/repos/Mathv25/nhl-betting-signal/actions/workflows/daily_signal.yml/dispatches',{"
            "method:'POST',"
            "headers:{'Accept':'application/vnd.github.v3+json',"
            "'Content-Type':'application/json',"
            "'Authorization':'token GH_TOKEN_PLACEHOLDER'},"
            "body:JSON.stringify({ref:'main'})"
            "}).then(function(r){"
            "if(r.status===204){"
            "btn.textContent='Lance! (~30s)';"
            "setTimeout(function(){window.location.reload();},35000);"
            "}else{"
            "btn.textContent='Erreur';"
            "btn.disabled=false;"
            "btn.classList.remove('loading');"
            "}"
            "}).catch(function(){"
            "btn.textContent='Erreur reseau';"
            "btn.disabled=false;"
            "btn.classList.remove('loading');"
            "});}"
            "function showTab(id,btn){"
            "['signal','props','calc'].forEach(function(t){document.getElementById('tab-'+t).style.display=t===id?'block':'none';});"
            "document.querySelectorAll('.tab').forEach(function(t){t.classList.remove('active');});"
            "btn.classList.add('active');}"
            "var DEF={elite:.82,good:.93,avg:1.0,weak:1.12};"
            "var hist=[];"
            "function pOver(lam,line){var p=0;for(var k=Math.ceil(line)+1;k<line+20;k++){var pmf=Math.exp(-lam)*Math.pow(lam,k);var f=1;for(var i=2;i<=k;i++)f*=i;p+=pmf/f;}return Math.min(Math.max(p,.05),.95);}"
            "function nCDF(z){var t=1/(1+.2316419*Math.abs(z));var d=.3989423*Math.exp(-z*z/2);var p=d*t*(.3193815+t*(-.3565638+t*(1.7814779+t*(-1.821256+t*1.3302744))));return z>0?1-p:p;}"
            "function calcEdge(){"
            "var pl=document.getElementById('cp').value||'Joueur';"
            "var mk=document.getElementById('cm').value;"
            "var dr=document.getElementById('cd').value;"
            "var li=parseFloat(document.getElementById('cl').value);"
            "var od=parseFloat(document.getElementById('co').value);"
            "var av=parseFloat(document.getElementById('ca').value);"
            "var df=document.getElementById('cdf').value;"
            "if(isNaN(od)||isNaN(av)||isNaN(li))return;"
            "var al=av*DEF[df];"
            "var op=mk==='saves'?(dr==='over'?1-nCDF((li-al)/4.5):nCDF((li-al)/4.5)):(dr==='over'?pOver(al,li):1-pOver(al,li));"
            "op=Math.min(Math.max(op,.05),.95);"
            "var bp=1/od,ep=(op-bp)/bp*100,b=od-1;"
            "var ky=b>0?Math.max(((b*op)-(1-op))/b/4*100,0):0;"
            "document.getElementById('rp').textContent=(op*100).toFixed(1)+'%';"
            "document.getElementById('ri').textContent=(bp*100).toFixed(1)+'%';"
            "document.getElementById('re').textContent=(ep>=0?'+':'')+ep.toFixed(1)+'%';"
            "document.getElementById('rk').textContent=ky.toFixed(1)+'% BR';"
            "var ml={'shots':'shots on goal','points':'points','goals':'buts','assists':'passes','saves':'saves'};"
            "var bs=pl+' '+dr.charAt(0).toUpperCase()+dr.slice(1)+' '+li+' '+ml[mk];"
            "var rv=document.getElementById('rv');"
            "var cl,tx;"
            "if(ep>=8){cl='vf';tx='Forte valeur — '+bs;}"
            "else if(ep>=5){cl='vg';tx='Bonne valeur — '+bs;}"
            "else if(ep>=3){cl='vo';tx='Valeur acceptable — '+bs;}"
            "else{cl='vb2';tx='Pas de valeur — eviter';}"
            "rv.className='vb '+cl;rv.textContent=tx;"
            "var dl={'elite':'defense elite','good':'bonne defense','avg':'defense moyenne','weak':'defense faible'};"
            "var ap=((DEF[df]-1)*100).toFixed(0);"
            "document.getElementById('rn').textContent='Moy. ajustee: '+al.toFixed(2)+' (base '+av+' x '+dl[df]+' '+(DEF[df]<1?'':'+')+ ap+'%) | Ligne: '+dr+' '+li+' | Cote: '+od;"
            "document.getElementById('cres').style.display='block';"
            "hist.unshift({bs:bs,od:od,ep:ep});"
            "var el=document.getElementById('ch');"
            "el.innerHTML=hist.slice(0,8).map(function(h){"
            "var ec=h.ep>=5?'#1D9E75':h.ep>=3?'#BA7517':'#A32D2D';"
            "var eb=h.ep>=5?'#E1F5EE':h.ep>=3?'#FAEEDA':'#FCEBEB';"
            "return '<div class=\"hi\"><span>'+h.bs+' @ '+h.od+'</span>"
            "<span class=\"he\" style=\"background:'+eb+';color:'+ec+'\">'+(h.ep>=0?'+':'')+h.ep.toFixed(1)+'%</span></div>';}).join('');}"
            "</script>"
        )

    def generate_empty_report(self):
        os.makedirs("docs", exist_ok=True)
        import pytz
        data = {
            "generated_at": datetime.now(pytz.timezone("America/Toronto")).isoformat(),
            "date": datetime.now(pytz.timezone("America/Toronto")).strftime("%Y-%m-%d"),
            "total_games": 0, "total_value_bets": 0,
            "signals": [], "value_bets": [], "props_analysis": [],
        }
        self.generate_html(data)
        with open("docs/signal.json","w") as f:
            json.dump({"date":"","games":[],"value_bets":[]},f)
