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

        html = ""
        for analysis in props_by_game:
            home  = analysis.get("home_team", "")
            away  = analysis.get("away_team", "")
            hg    = analysis.get("home_goalie", {})
            ag    = analysis.get("away_goalie", {})
            bets  = analysis.get("bets", [])
            retour = analysis.get("retour_de_flamme", [])
            lineup_confirmed = analysis.get("lineup_confirmed", True)
            hshots = analysis.get("home_def_shots", 31.0)
            ashots = analysis.get("away_def_shots", 31.0)
            hga    = analysis.get("home_def_ga", 3.10)
            aga    = analysis.get("away_def_ga", 3.10)
            hsr    = analysis.get("home_shots_rank", 16)
            asr    = analysis.get("away_shots_rank", 16)
            hgr    = analysis.get("home_ga_rank", 16)
            agr    = analysis.get("away_ga_rank", 16)

            def rank_color(r):
                if r <= 4:   return "#0F6E56"
                if r <= 10:  return "#2563EB"
                if r <= 22:  return "#6B7280"
                return "#B45309"

            def rank_label(r):
                if r <= 4:   return "Elite"
                if r <= 10:  return "Bonne"
                if r <= 22:  return "Moyenne"
                return "Faible"

            # En-tete match
            html += (
                "<div class='pg'>"
                "<div class='ph'>"
                "<div class='pm'><span class='pm-away'>" + away + "</span>"
                " <span class='pm-at'>@</span> "
                "<span class='pm-home'>" + home + "</span></div>"

                "<div class='matchup-grid'>"

                "<div class='matchup-col'>"
                "<div class='mc-title'>DEF " + home[:3].upper() + "</div>"
                "<div class='mc-stat'><span style='color:" + rank_color(hsr) + "'>" + rank_label(hsr) + " (#" + str(hsr) + ")</span> shots</div>"
                "<div class='mc-stat'><span style='color:" + rank_color(hgr) + "'>" + rank_label(hgr) + " (#" + str(hgr) + ")</span> buts</div>"
                "<div class='mc-val'><strong>" + str(hshots) + "</strong> shots/m accordes · <strong>" + str(hga) + "</strong> GA/m</div>"
                "</div>"

                "<div class='matchup-col'>"
                "<div class='mc-title'>DEF " + away[:3].upper() + "</div>"
                "<div class='mc-stat'><span style='color:" + rank_color(asr) + "'>" + rank_label(asr) + " (#" + str(asr) + ")</span> shots</div>"
                "<div class='mc-stat'><span style='color:" + rank_color(agr) + "'>" + rank_label(agr) + " (#" + str(agr) + ")</span> buts</div>"
                "<div class='mc-val'><strong>" + str(ashots) + "</strong> shots/m accordes · <strong>" + str(aga) + "</strong> GA/m</div>"
                "</div>"

                "<div class='matchup-col'>"
                "<div class='mc-title'>Gardiens</div>"
            )

            for g, side in [(hg, "DOM"), (ag, "VIS")]:
                if g.get("name"):
                    sv = g.get("sv_pct", 0)
                    sv_c = "#0F6E56" if sv >= 0.915 else ("#B45309" if sv < 0.900 else "#6B7280")
                    html += (
                        "<div class='mc-goalie'><span class='mc-side'>" + side + "</span> "
                        "<strong>" + g["name"] + "</strong> "
                        "<span style='color:" + sv_c + "'>SV% " + str(sv) + "</span> · "
                        "GAA " + str(g.get("gaa", "--")) + "</div>"
                    )

            html += "</div></div></div>"

            # Bets joueurs
            if not bets:
                html += "<div class='no-bets' style='margin:0 0 1rem'>Aucun bet +EV identifie (edge < 8%)</div>"
            else:
                html += "<div class='player-bets'>"
                for b in bets:
                    edge      = b.get("edge_pct", 0)
                    prob      = b.get("our_prob", 0)
                    kelly     = b.get("kelly", 0)
                    market    = b.get("market", "")
                    mdetail   = b.get("market_detail", "")
                    name      = b.get("name", "")
                    pos       = b.get("position", "")
                    team      = b.get("team", "")
                    opp       = b.get("opponent", "")
                    toi       = b.get("toi", "--")
                    notes     = b.get("context_notes", [])
                    all_mkts  = b.get("all_markets", [])
                    dk_impl   = b.get("dk_implied", 52.4)

                    # Shots stats
                    s_pg   = b.get("shots_pg", 0)
                    s_adj  = b.get("shots_adj", 0)
                    s_line = b.get("shots_line", 0)
                    s_prob = b.get("shots_prob", 0)
                    s_edge = b.get("shots_edge", 0)
                    l5s    = b.get("last5_shots", 0)
                    l10s   = b.get("last10_shots", 0)
                    avg5s  = round(l5s / 5,  1)
                    avg10s = round(l10s / 10, 1) if l10s else s_pg

                    # Goals/points
                    g_pg   = b.get("goals_pg", 0)
                    g_adj  = b.get("goals_adj", 0)
                    g_prob = b.get("goals_prob", 0)
                    g_edge = b.get("goals_edge", 0)
                    l5g    = b.get("last5_goals", 0)
                    sg     = b.get("season_goals", 0)
                    p_pg   = b.get("points_pg", 0)
                    p_adj  = b.get("points_adj", 0)
                    p_prob = b.get("points_prob", 0)
                    p_edge = b.get("points_edge", 0)
                    l5p    = b.get("last5_points", 0)
                    sp     = b.get("season_points", 0)

                    opp_sr = b.get("opp_shots_rank", 16)
                    opp_gr = b.get("opp_ga_rank", 16)

                    ec = "#0F6E56" if edge >= 15 else "#BA7517"
                    eb = "#E1F5EE" if edge >= 15 else "#FAEEDA"

                    def pec(e):
                        if e >= 15: return "#0F6E56"
                        if e >= 8:  return "#BA7517"
                        return "#9CA3AF"

                    est_odds_str = str(b.get("est_odds", "~1.75"))
                    html += (
                        "<div class='pb'>"
                        "<div class='pb-head'>"
                        "<div class='pb-info'>"
                        "<span class='pb-name'>" + name + "</span>"
                        "<span class='pb-pos'>" + pos + "</span>"
                        "<span class='pb-team'>" + team[:3].upper() + " vs " + opp[:3].upper() + " · " + toi + " TOI</span>"
                        "</div>"
                        "<div class='pb-season'>" + str(sg) + " buts · " + str(sp) + " pts cette saison</div>"
                        "</div>"
                        "<div class='pb-main-bet' style='border-left-color:" + ec + "'>"
                        "<div class='pbm-label'>📌 MEILLEUR BET</div>"
                        "<div class='pbm-market' style='color:" + ec + "'>" + market + "</div>"
                        "<div class='pbm-detail'>" + mdetail + "</div>"

                        "<div class='pbm-odds'>"
                        "<div class='pbm-odd'><span>Cote est. b365</span><strong>" + est_odds_str + "</strong></div>"
                        "<div class='pbm-odd'><span>Notre prob</span><strong style='color:" + ec + "'>" + str(prob) + "%</strong></div>"
                        "<div class='pbm-odd'><span>b365 implied</span><strong>" + str(dk_impl) + "%</strong></div>"
                        "<div class='pbm-odd edge-highlight' style='background:" + eb + ";color:" + ec + "'>"
                        "<span>Edge</span><strong>+" + str(edge) + "%</strong></div>"
                        "<div class='pbm-odd'><span>1/4 Kelly</span><strong>" + str(kelly) + "% BR</strong></div>"
                        "</div></div>"

                        # Section shots (toujours affichee)
                        "<div class='pb-shots'>"
                        "<div class='pbs-title'>🎯 Shots on Goal</div>"
                        "<div class='pbs-grid'>"
                        "<div class='pbs-col'>"
                        "<div class='pbs-stat'><span>Moy 10m (pond.)</span><strong>" + str(s_pg) + "</strong></div>"
                        "<div class='pbs-stat'><span>Adj DEF adverse</span><strong>" + str(s_adj) + "</strong></div>"
                        "<div class='pbs-stat'><span>Ligne DK estimee</span><strong>" + str(s_line) + "</strong></div>"
                        "</div>"
                        "<div class='pbs-col'>"
                        "<div class='pbs-stat'><span>Last 5 (" + str(avg5s) + "/m)</span><strong>" + str(l5s) + " shots</strong></div>"
                        "<div class='pbs-stat'><span>Last 10 (" + str(avg10s) + "/m)</span><strong>" + str(l10s) + " shots</strong></div>"
                        "<div class='pbs-stat'><span>Prob Over " + str(s_line if s_line else "?") + "</span>"
                        "<strong style='color:" + pec(s_edge) + "'>" + str(s_prob) + "% (edge +" + str(s_edge) + "%)</strong></div>"
                        "</div>"
                        "<div class='pbs-col'>"
                        "<div class='pbs-stat'><span>DEF adverse shots</span>"
                        "<strong style='color:" + ("#B45309" if opp_sr >= 25 else "#0F6E56" if opp_sr <= 8 else "#6B7280") + "'>"
                        "#" + str(opp_sr) + " ligue</strong></div>"
                        "<div class='pbs-stat'><span>DEF adverse buts</span>"
                        "<strong style='color:" + ("#B45309" if opp_gr >= 25 else "#0F6E56" if opp_gr <= 8 else "#6B7280") + "'>"
                        "#" + str(opp_gr) + " ligue</strong></div>"
                        "<div class='pbs-stat'><span>Buts saison</span><strong>" + str(sg) + " buts</strong></div>"
                        "</div>"
                        "</div>"

                        # Autres stats
                        "<div class='pbs-others'>"
                        "<span>Buts: moy " + str(g_pg) + "/m · adj " + str(g_adj) + " · last5: " + str(l5g) + " · prob " + str(g_prob) + "% (edge +" + str(g_edge) + "%)</span>"
                        " &nbsp;|&nbsp; "
                        "<span>Pts: moy " + str(p_pg) + "/m · adj " + str(p_adj) + " · last5: " + str(l5p) + " · prob " + str(p_prob) + "% (edge +" + str(p_edge) + "%)</span>"
                        "</div>"
                        "</div>"

                        # Contexte narratif
                    )

                    if notes:
                        html += "<div class='pb-context'>"
                        for note in notes:
                            html += "<div class='pb-note'>" + note + "</div>"
                        html += "</div>"

                    # Autres marches +EV
                    other_mkts = [m for m in all_mkts if m["label"] != market]
                    if other_mkts:
                        html += "<div class='pb-others-bets'>Autres bets +EV: "
                        for m in other_mkts:
                            mc = "#0F6E56" if m["edge"] >= 15 else "#BA7517"
                            html += (
                                "<span class='pb-other-bet' style='color:" + mc + "'>"
                                + m["label"] + " (+" + str(m["edge"]) + "% edge · " + str(m["prob"]) + "% prob)"
                                "</span> "
                            )
                        html += "</div>"

                    html += "</div>"  # /pb

                html += "</div>"  # /player-bets

            # Badge lineup non confirme
            if not lineup_confirmed:
                html += (
                    "<div class='lineup-warning'>"
                    "⚠️ Lineup non confirme — Daily Faceoff n'a pas retourne les line combos. "
                    "Verifiez les lineups avant de parier."
                    "</div>"
                )

            # Bloc retour de flamme
            if retour:
                html += (
                    "<div class='retour-section'>"
                    "<div class='retour-title'>🧊 Retour de flamme — Regression vers la moyenne</div>"
                    "<div class='retour-subtitle'>Joueurs en dessous de leur moyenne last 5 · DK va probablement baisser la ligne · Edge sur le Over base sur la vraie moyenne</div>"
                )
                for r in retour:
                    rname     = r.get("name", "")
                    rteam     = r.get("team", "")
                    ropp      = r.get("opponent", "")
                    ravg10    = r.get("avg10_shots", 0)
                    ravg5     = r.get("avg5_shots", 0)
                    rdrop     = r.get("drop_pct", 0)
                    rline     = r.get("dk_line_est", 0)
                    radj      = r.get("shots_adj", 0)
                    rprob     = r.get("our_prob", 0)
                    redge     = r.get("edge_pct", 0)
                    rodds     = r.get("est_odds", 0)
                    rkelly    = r.get("kelly", 0)
                    ropp_rank = r.get("opp_shots_rank", 16)
                    rpos      = r.get("position", "")
                    rtoi      = r.get("toi", "--")

                    drop_color = "#A32D2D" if rdrop >= 40 else "#B45309"
                    edge_color = "#0F6E56" if redge >= 15 else "#BA7517"

                    html += (
                        "<div class='retour-card'>"
                        "<div class='retour-head'>"
                        "<div>"
                        "<span class='retour-name'>" + rname + "</span>"
                        "<span class='retour-meta'>" + rpos + " · " + rteam[:3].upper() + " vs " + ropp[:3].upper() + " · " + rtoi + " TOI</span>"
                        "</div>"
                        "<div class='retour-drop' style='color:" + drop_color + "'>-" + str(rdrop) + "% depuis last 5</div>"
                        "</div>"

                        "<div class='retour-stats'>"
                        "<div class='retour-stat'><span>Moy last 10</span><strong>" + str(ravg10) + " shots/m</strong></div>"
                        "<div class='retour-stat'><span>Moy last 5</span><strong style='color:" + drop_color + "'>" + str(ravg5) + " shots/m</strong></div>"
                        "<div class='retour-stat'><span>Ligne DK estimee</span><strong>" + str(rline) + " shots</strong></div>"
                        "<div class='retour-stat'><span>Shots proj. (moy reelle)</span><strong>" + str(radj) + "</strong></div>"
                        "<div class='retour-stat'><span>DEF adverse</span><strong style='color:" + rank_color(ropp_rank) + "'>#" + str(ropp_rank) + " ligue</strong></div>"
                        "<div class='retour-stat edge-cell' style='color:" + edge_color + "'><span>Edge</span><strong>+" + str(redge) + "%</strong></div>"
                        "<div class='retour-stat'><span>Cote est. b365</span><strong>" + str(rodds) + "</strong></div>"
                        "<div class='retour-stat'><span>Notre prob</span><strong>" + str(rprob) + "%</strong></div>"
                        "<div class='retour-stat'><span>1/4 Kelly</span><strong>" + str(rkelly) + "% BR</strong></div>"
                        "</div>"

                        "<div class='retour-signal'>📌 Bet: Shots Over " + str(rline) + " · Logique: moy reelle " + str(ravg10) + "/m → DK va coter bas sur la forme recente</div>"
                        "</div>"
                    )
                html += "</div>"  # /retour-section

            html += "</div>"  # /pg

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
            ".lineup-warning{background:#FAEEDA;border-left:3px solid #B45309;color:#633806;padding:10px 14px;border-radius:6px;font-size:12px;margin:0 0 1rem}"
            ".retour-section{margin:1rem 0 0;border-top:.5px solid var(--b);padding-top:1rem}"
            ".retour-title{font-size:14px;font-weight:500;color:var(--t);margin-bottom:4px}"
            ".retour-subtitle{font-size:11px;color:var(--m);margin-bottom:1rem;line-height:1.5}"
            ".retour-card{background:var(--s);border:.5px solid var(--b);border-left:3px solid #378ADD;border-radius:8px;padding:12px 14px;margin-bottom:10px}"
            ".retour-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px}"
            ".retour-name{font-size:14px;font-weight:500;color:var(--t);display:block}"
            ".retour-meta{font-size:11px;color:var(--m)}"
            ".retour-drop{font-size:13px;font-weight:500;flex-shrink:0;margin-left:8px}"
            ".retour-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:10px}"
            ".retour-stat{background:var(--bg);border-radius:5px;padding:6px 8px;font-size:11px;color:var(--m)}"
            ".retour-stat span{display:block;margin-bottom:2px}"
            ".retour-stat strong{font-size:13px;font-weight:500;color:var(--t)}"
            ".retour-signal{font-size:11px;color:#185FA5;background:#E6F1FB;border-radius:5px;padding:7px 10px;line-height:1.5}"
            "/* PROPS JOUEURS */"
            ".matchup-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:.75rem}"
            ".matchup-col{background:var(--bg);border:.5px solid var(--b);border-radius:var(--rs);padding:.75rem}"
            ".mc-title{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--m);margin-bottom:.4rem}"
            ".mc-stat{font-size:12px;margin-bottom:2px}"
            ".mc-val{font-size:11px;color:var(--m);margin-top:4px}"
            ".mc-goalie{font-size:12px;margin-bottom:3px}"
            ".mc-side{font-size:10px;color:var(--m);font-weight:600;margin-right:4px}"
            ".player-bets{display:flex;flex-direction:column;gap:.75rem;margin-top:.75rem}"
            ".pb{background:var(--bg);border:.5px solid var(--b);border-radius:var(--rs);overflow:hidden}"
            ".pb-head{display:flex;justify-content:space-between;align-items:flex-start;padding:.75rem 1rem .5rem;flex-wrap:wrap;gap:4px}"
            ".pb-info{display:flex;align-items:center;gap:6px;flex-wrap:wrap}"
            ".pb-name{font-size:16px;font-weight:700}"
            ".pb-pos{font-size:11px;color:var(--m);background:var(--s);padding:2px 6px;border-radius:4px;border:.5px solid var(--b)}"
            ".pb-team{font-size:12px;color:var(--m)}"
            ".pb-season{font-size:11px;color:var(--m)}"
            ".pb-main-bet{border-left:3px solid;padding:.75rem 1rem;background:var(--s);margin:.25rem 0}"
            ".pbm-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--m);margin-bottom:3px}"
            ".pbm-market{font-size:17px;font-weight:700;margin-bottom:3px}"
            ".pbm-detail{font-size:12px;color:var(--m);margin-bottom:.6rem}"
            ".pbm-odds{display:flex;gap:8px;flex-wrap:wrap}"
            ".pbm-odd{display:flex;flex-direction:column;gap:2px;background:var(--bg);border-radius:6px;padding:5px 10px;min-width:80px}"
            ".pbm-odd span{font-size:10px;color:var(--m)}"
            ".pbm-odd strong{font-size:14px;font-weight:700}"
            ".edge-highlight{border:.5px solid currentColor}"
            ".pb-shots{padding:.75rem 1rem;border-top:.5px solid var(--b)}"
            ".pbs-title{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--m);margin-bottom:.5rem}"
            ".pbs-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:.5rem}"
            ".pbs-col{display:flex;flex-direction:column;gap:3px}"
            ".pbs-stat{font-size:11px;color:var(--m);display:flex;flex-direction:column}"
            ".pbs-stat strong{font-size:13px;font-weight:600;color:var(--t)}"
            ".pbs-others{font-size:11px;color:var(--m);padding-top:.4rem;border-top:.5px solid var(--b)}"
            ".pb-context{padding:.6rem 1rem;background:var(--s);border-top:.5px solid var(--b);display:flex;flex-direction:column;gap:4px}"
            ".pb-note{font-size:12px;color:var(--t)}"
            ".pb-others-bets{padding:.5rem 1rem;font-size:12px;color:var(--m);border-top:.5px solid var(--b)}"
            ".pb-other-bet{font-weight:600;margin-right:8px}"
            "@media(max-width:600px){.matchup-grid{grid-template-columns:1fr}.pbs-grid{grid-template-columns:1fr}.pbm-odds{gap:6px}}"
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
