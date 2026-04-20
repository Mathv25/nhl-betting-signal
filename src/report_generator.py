"""
Report Generator - Dashboard GitHub Pages complet
4 sections: Signal auto | Analyse joueurs | Performance | Calculateur edge
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

        bet_cards    = self._bet_cards(value_bets)
        rows         = self._rows(signals)
        props_html   = self._props_section(props_by_game)
        calc_html    = self._calculator()
        perf_html    = self._performance_section()
        mlb_html     = self._mlb_section(data.get("mlb_analysis", []))

        parts = [
            "<!DOCTYPE html><html lang=\"fr\"><head>",
            "<meta charset=\"UTF-8\">",
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
            "<meta name=\"signal-generated-at\" content=\"" + gen_at + "\">",
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
            "<div id=\"tab-nba\" style=\"display:none\">",
            self._nba_section(data.get("nba_analysis", [])),
            "</div>",
            "<div id=\"tab-mlb\" style=\"display:none\">",
            mlb_html,
            "</div>",
            "<div id=\"tab-perf\" style=\"display:none\">",
            perf_html,
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
            "<span class=\"nt\">🏒 NHL <span>Signal</span></span>"
            "<div class=\"tabs\">"
            "<button class=\"tab active\" onclick=\"showTab('tab-signal',this)\">Signal</button>"
            "<button class=\"tab\" onclick=\"showTab('tab-props',this)\">Props NHL</button>"
            "<button class=\"tab\" onclick=\"showTab('tab-nba',this)\">NBA</button>"
            "<button class=\"tab\" onclick=\"showTab('tab-mlb',this)\">MLB</button>"
            "<button class=\"tab\" onclick=\"showTab('tab-perf',this)\">Performance</button>"
            "<button class=\"tab\" onclick=\"showTab('tab-calc',this)\">Calculateur</button>"
            "</div>"
            "<button id=\"refreshBtn\" onclick=\"location.reload(true)\" title=\"Recharger la page\" style=\""
            "background:none;border:1px solid var(--b);border-radius:8px;padding:5px 12px;"
            "font-size:13px;font-weight:500;cursor:pointer;color:var(--m);transition:all .15s;"
            "white-space:nowrap;\">"
            "↻ Actualiser"
            "</button>"
            "</div></nav>"
        )

    def _header(self):
        return (
            "<header>"
            "<h1>NHL Betting Signal</h1>"
            "<p>Modele Poisson · Cotes DraftKings · Critere de Kelly · Alignements NHL.com · Props joueurs</p>"
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

    def _performance_section(self) -> str:
        """
        Retourne un conteneur vide: les donnees sont chargees dynamiquement
        via fetch('results.json') dans le navigateur a chaque affichage de l'onglet.
        """
        return (
            "<div id='perf-content'>"
            "<div class='perf-empty'>"
            "<div class='perf-empty-icon' style='font-size:28px'>⏳</div>"
            "<div class='perf-empty-sub'>Chargement des performances...</div>"
            "</div>"
            "</div>"
        )

    def _bet_cards(self, value_bets):
        if not value_bets:
            return "<p class=\"no-bets\">Aucun bet avec edge superieur a 5% aujourd'hui.</p>"
        cards = ""
        for b in value_bets:
            ep  = b.get("edge_pct", 0)
            ec  = "var(--g)" if ep >= 8 else ("var(--a)" if ep >= 5 else "var(--r2)")
            eb  = "var(--g2)" if ep >= 8 else ("var(--a2)" if ep >= 5 else "var(--r2b)")
            et  = "var(--g3)" if ep >= 8 else ("var(--a3)" if ep >= 5 else "var(--r2d)")
            vd  = b.get("verdict", "")
            bar_w = min(round(ep / 20 * 100), 100)
            bar_c = "#10B981" if ep >= 8 else ("#F59E0B" if ep >= 5 else "#EF4444")
            note  = b.get("note", "")
            cards += (
                "<div class=\"bc\">"
                "<div class=\"bh\">"
                "<div>"
                "<div class=\"bt\">" + b.get("type", "") + "</div>"
                "<div class=\"bn\">" + b.get("bet", "") + "</div>"
                "<div class=\"bg\">" + b.get("game", "") + "</div>"
                + ("<div class=\"bg\" style='margin-top:4px;font-size:11px'>" + note + "</div>" if note else "") +
                "</div>"
                "<span class=\"vd\" style=\"background:" + eb + ";color:" + et + "\">" + vd + "</span>"
                "</div>"
                "<div class=\"bs\">"
                "<div class=\"stat\"><span class=\"sl\">Cote DK</span><span class=\"sv\">" + str(round(b.get("b365_odds", 0), 2)) + "</span></div>"
                "<div class=\"stat\"><span class=\"sl\">Prob DK</span><span class=\"sv\">" + str(round(b.get("b365_implied", 0), 1)) + "%</span></div>"
                "<div class=\"stat\"><span class=\"sl\">Prob modele</span><span class=\"sv\">" + str(round(b.get("our_prob", 0), 1)) + "%</span></div>"
                "<div class=\"stat\" style=\"color:" + ec + "\"><span class=\"sl\">Edge</span><span class=\"sv\">+" + str(round(ep, 1)) + "%</span></div>"
                "<div class=\"stat\"><span class=\"sl\">1/4 Kelly</span><span class=\"sv\">" + str(round(b.get("kelly_fraction", 0), 1)) + "% BR</span></div>"
                "</div>"
                "<div class=\"edge-bar-wrap\">"
                "<div class=\"edge-bar-label\">"
                "<span>Force du signal</span>"
                "<span style=\"color:" + ec + ";font-weight:700\">+" + str(round(ep, 1)) + "% edge</span>"
                "</div>"
                "<div class=\"edge-bar\"><div class=\"edge-bar-fill\" style=\"width:" + str(bar_w) + "%;background:" + bar_c + "\"></div></div>"
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
                    s_pg   = b.get("shots_pg", 0)
                    s_adj  = b.get("shots_adj", 0)
                    s_line = b.get("shots_line", 0)
                    s_prob = b.get("shots_prob", 0)
                    s_edge = b.get("shots_edge", 0)
                    l5s    = b.get("last5_shots", 0)
                    l10s   = b.get("last10_shots", 0)
                    avg5s  = round(l5s / 5,  1)
                    avg10s = round(l10s / 10, 1) if l10s else s_pg
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
                        "<div class='pbs-others'>"
                        "<span>Buts: moy " + str(g_pg) + "/m · adj " + str(g_adj) + " · last5: " + str(l5g) + " · prob " + str(g_prob) + "% (edge +" + str(g_edge) + "%)</span>"
                        " &nbsp;|&nbsp; "
                        "<span>Pts: moy " + str(p_pg) + "/m · adj " + str(p_adj) + " · last5: " + str(l5p) + " · prob " + str(p_prob) + "% (edge +" + str(p_edge) + "%)</span>"
                        "</div>"
                        "</div>"
                    )

                    if notes:
                        html += "<div class='pb-context'>"
                        for note in notes:
                            html += "<div class='pb-note'>" + note + "</div>"
                        html += "</div>"

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

                    html += "</div>"
                html += "</div>"

            if not lineup_confirmed:
                html += (
                    "<div class='lineup-warning'>"
                    "⚠️ Lineup non confirme — Daily Faceoff n'a pas retourne les line combos. "
                    "Verifiez les lineups avant de parier."
                    "</div>"
                )

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
                html += "</div>"

            html += "</div>"

        return html

    def _nba_section(self, nba_analysis: list) -> str:
        if not nba_analysis:
            return "<div style='color:var(--m);padding:1rem 0;font-size:13px'>Aucune analyse NBA disponible ou pas de matchs ce soir.</div>"

        html = "<div class='nba-header'>NBA Player Props — Analyse +EV</div>"
        for game_data in nba_analysis:
            home  = game_data.get("home_team", "")
            away  = game_data.get("away_team", "")
            bets  = game_data.get("bets", [])
            if not bets: continue
            html += (
                "<div class='nba-game'>"
                "<div class='nba-matchup'>" + away + " <span class='nba-at'>@</span> " + home + "</div>"
            )
            for b in bets:
                player   = b.get("player", "")
                market   = b.get("market", "")
                prob     = b.get("our_prob", 0)
                edge     = b.get("edge_pct", 0)
                kelly    = b.get("kelly", 0)
                odds     = b.get("est_odds", 0)
                avg10    = b.get("avg10", 0)
                avg5     = b.get("avg5", 0)
                adj      = b.get("adj_proj", 0)
                def_rank = b.get("def_rank", 15)
                opponent = b.get("opponent", "")
                context  = b.get("context", [])
                team     = b.get("team", "")
                ec = "#0F6E56" if edge >= 15 else "#BA7517"
                eb = "#E1F5EE" if edge >= 15 else "#FAEEDA"
                dr_color = "#B45309" if def_rank >= 25 else ("#0F6E56" if def_rank <= 5 else "#6B7280")
                html += (
                    "<div class='nba-card'>"
                    "<div class='nba-card-head'>"
                    "<div>"
                    "<span class='nba-player'>" + player + "</span>"
                    "<span class='nba-meta'>" + team.split()[-1] + " vs " + opponent.split()[-1] + "</span>"
                    "</div>"
                    "<div class='nba-edge' style='color:" + ec + ";background:" + eb + "'>"
                    "+" + str(edge) + "% edge"
                    "</div>"
                    "</div>"
                    "<div class='nba-bet-label'>" + market + "</div>"
                    "<div class='nba-stats'>"
                    "<div class='nba-stat'><span>Moy last 10</span><strong>" + str(avg10) + "</strong></div>"
                    "<div class='nba-stat'><span>Moy last 5</span><strong>" + str(avg5) + "</strong></div>"
                    "<div class='nba-stat'><span>Proj. adj DEF</span><strong>" + str(adj) + "</strong></div>"
                    "<div class='nba-stat'><span>DEF adverse</span><strong style='color:" + dr_color + "'>#" + str(def_rank) + " ligue</strong></div>"
                    "<div class='nba-stat'><span>Notre prob</span><strong style='color:" + ec + "'>" + str(prob) + "%</strong></div>"
                    "<div class='nba-stat'><span>Cote est. b365</span><strong>" + str(odds) + "</strong></div>"
                    "<div class='nba-stat'><span>b365 implied</span><strong>52.4%</strong></div>"
                    "<div class='nba-stat'><span>1/4 Kelly</span><strong>" + str(kelly) + "% BR</strong></div>"
                    "</div>"
                )
                if context:
                    for note in context[:2]:
                        html += "<div class='nba-note'>" + note + "</div>"
                html += "</div>"
            html += "</div>"
        return html

    def _mlb_section(self, mlb_analysis: list) -> str:
        if not mlb_analysis:
            return (
                "<div style='color:var(--m);padding:1rem 0;font-size:13px'>"
                "Aucune analyse MLB disponible ou pas de matchs ce soir."
                "</div>"
            )

        html = "<div class='mlb-header'>MLB Player Props — Analyse +EV</div>"
        for game_data in mlb_analysis:
            home = game_data.get("home_team", "")
            away = game_data.get("away_team", "")
            bets = game_data.get("bets", [])
            if not bets:
                continue
            html += (
                "<div class='mlb-game'>"
                "<div class='mlb-matchup'>"
                + away + " <span class='mlb-at'>@</span> " + home
                + "</div>"
            )
            for b in bets:
                player      = b.get("player", "")
                market      = b.get("market", "")
                player_type = b.get("player_type", "batter")
                prob        = b.get("our_prob", 0)
                edge        = b.get("edge_pct", 0)
                kelly       = b.get("kelly", 0)
                odds        = b.get("est_odds", 0)
                season_avg  = b.get("season_avg", 0)
                adj_proj    = b.get("adj_proj", 0)
                opp_k_rate  = b.get("opp_k_rate")
                park_factor = b.get("park_factor", 1.0)
                dk_implied  = b.get("dk_implied", 52.6)
                team        = b.get("team", "")
                opponent    = b.get("opponent", "")
                context     = b.get("context", [])

                ec = "#0F6E56" if edge >= 15 else "#BA7517"
                eb = "#E1F5EE" if edge >= 15 else "#FAEEDA"
                type_icon = "⚾" if player_type == "pitcher" else "🏏"
                type_label = "Lanceur" if player_type == "pitcher" else "Frappeur"

                html += (
                    "<div class='mlb-card'>"
                    "<div class='mlb-card-head'>"
                    "<div>"
                    "<span class='mlb-player'>" + type_icon + " " + player + "</span>"
                    "<span class='mlb-meta'>" + type_label + " · " + team.split()[-1] + " vs " + opponent.split()[-1] + "</span>"
                    "</div>"
                    "<div class='mlb-edge' style='color:" + ec + ";background:" + eb + "'>"
                    "+" + str(edge) + "% edge"
                    "</div>"
                    "</div>"
                    "<div class='mlb-bet-label'>" + market + "</div>"
                    "<div class='mlb-stats'>"
                    "<div class='mlb-stat'><span>Moy saison</span><strong>" + str(season_avg) + "</strong></div>"
                    "<div class='mlb-stat'><span>Proj. ajustee</span><strong>" + str(adj_proj) + "</strong></div>"
                )
                if opp_k_rate is not None:
                    html += "<div class='mlb-stat'><span>K% adverse</span><strong>" + str(opp_k_rate) + "%</strong></div>"
                pf_color = "#B45309" if park_factor >= 1.08 else ("#0F6E56" if park_factor <= 0.92 else "#6B7280")
                html += (
                    "<div class='mlb-stat'><span>Park factor</span><strong style='color:" + pf_color + "'>" + str(park_factor) + "</strong></div>"
                    "<div class='mlb-stat'><span>Notre prob</span><strong style='color:" + ec + "'>" + str(prob) + "%</strong></div>"
                    "<div class='mlb-stat'><span>DK implied</span><strong>" + str(dk_implied) + "%</strong></div>"
                    "<div class='mlb-stat'><span>Cote est. DK</span><strong>" + str(odds) + "</strong></div>"
                    "<div class='mlb-stat'><span>1/4 Kelly</span><strong>" + str(kelly) + "% BR</strong></div>"
                    "</div>"
                )
                for note in context[:2]:
                    html += "<div class='mlb-note'>" + note + "</div>"
                html += "</div>"
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
            "btn.classList.add('active');"
            "if(id==='tab-perf'){loadPerf();}"
            "}"

            "function loadPerf(){"
            "fetch('results.json?t='+Date.now())"
            ".then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})"
            ".then(function(data){renderPerf(data);})"
            ".catch(function(){document.getElementById('perf-content').innerHTML="
            "\"<div class='perf-empty'><div class='perf-empty-icon'>📊</div>"
            "<div class='perf-empty-title'>Aucune donnee de performance</div>"
            "<div class='perf-empty-sub'>Le backtester resout automatiquement les bets chaque matin.</div></div>\";});}"

            "function renderPerf(data){"
            "var s=data.summary||{};"
            "var bets=data.bets||[];"
            "var total=s.total||0;"
            "var wr=s.win_rate||0;"
            "var profit=s.profit||0;"
            "var roi=s.roi||0;"
            "var by_edge=s.by_edge||{};"
            "var updated=s.last_updated||'';"
            "if(total===0){"
            "document.getElementById('perf-content').innerHTML="
            "\"<div class='perf-empty'><div class='perf-empty-icon'>⏳</div>"
            "<div class='perf-empty-title'>En attente de resultats</div>"
            "<div class='perf-empty-sub'>Des bets ont ete enregistres mais aucun match n'est encore resolu.</div></div>\";"
            "return;}"
            "var pc=profit>=0?'#1D9E75':'#A32D2D';"
            "var rc2=roi>=0?'#1D9E75':'#A32D2D';"
            "var ps=profit>=0?'+':'';"
            "var rs2=roi>=0?'+':'';"
            "var wrc=wr>=55?'#1D9E75':wr>=50?'#BA7517':'#A32D2D';"
            "var h=\"<div class='perf-wrap'>\";"
            "h+=\"<div class='perf-title'>Performance cumulee du modele</div>\";"
            "h+=\"<div class='perf-grid'>\";"
            "h+=\"<div class='perf-box'><div class='perf-label'>Bets resolus</div><div class='perf-val'>\"+total+\"</div></div>\";"
            "h+=\"<div class='perf-box'><div class='perf-label'>Win Rate</div><div class='perf-val' style='color:\"+wrc+\"'>\"+wr+\"%</div></div>\";"
            "h+=\"<div class='perf-box'><div class='perf-label'>Profit (unites)</div><div class='perf-val' style='color:\"+pc+\"'>\"+ps+profit+\"u</div></div>\";"
            "h+=\"<div class='perf-box'><div class='perf-label'>ROI</div><div class='perf-val' style='color:\"+rc2+\"'>\"+rs2+roi+\"%</div></div>\";"
            "h+=\"</div>\";"
            "var edgeKeys=Object.keys(by_edge);"
            "if(edgeKeys.length){"
            "h+=\"<div class='perf-section-title'>Par tranche d'edge</div><div class='perf-edge-table'>\";"
            "edgeKeys.forEach(function(label){"
            "var info=by_edge[label];"
            "var n=info.n||0;var w=info.wins||0;var p=info.profit||0;"
            "var wrl=n>0?Math.round(w/n*1000)/10:0;"
            "var epc=p>=0?'#1D9E75':'#A32D2D';"
            "var eps=p>=0?'+':'';"
            "h+=\"<div class='perf-edge-row'>\";"
            "h+=\"<span class='perf-edge-label'>Edge \"+label+\"%</span>\";"
            "h+=\"<span class='perf-edge-n'>\"+n+\" bets</span>\";"
            "h+=\"<span class='perf-edge-wr'>\"+wrl+\"% WR</span>\";"
            "h+=\"<span class='perf-edge-profit' style='color:\"+epc+\"'>\"+eps+p+\"u</span>\";"
            "h+=\"</div>\";"
            "});"
            "h+=\"</div>\";}"
            "var resolved=bets.filter(function(b){return b.result==='W'||b.result==='L';});"
            "var pending=bets.filter(function(b){return b.result==='?';});"
            "var recent=resolved.slice().reverse().slice(0,30);"
            "if(recent.length){"
            "h+=\"<div class='perf-section-title'>Historique recents (\"+resolved.length+\" resolus\";"
            "if(pending.length)h+=\", \"+pending.length+\" en attente\";"
            "h+=\")</div>\";"
            "h+=\"<div class='perf-hist'>\";"
            "recent.forEach(function(b){"
            "var res=b.result||'?';"
            "var brc=res==='W'?'#1D9E75':'#A32D2D';"
            "var brb=res==='W'?'#E1F5EE':'#FCEBEB';"
            "var ep=b.edge_pct||0;"
            "var odds=b.b365_odds||0;"
            "var kelly=Math.min(b.kelly_fraction||0,3.0);"
            "var pbr=res==='W'?Math.round(kelly*(odds-1)*100)/100:Math.round(-kelly*100)/100;"
            "var pbs2=pbr>=0?'+':'';"
            "h+=\"<div class='perf-hist-row'>\";"
            "h+=\"<div class='perf-hist-left'>\";"
            "h+=\"<span class='perf-hist-result' style='background:\"+brb+\";color:\"+brc+\"'>\"+res+\"</span>\";"
            "h+=\"<div><div class='perf-hist-bet'>\"+b.bet+\"</div>\";"
            "h+=\"<div class='perf-hist-game'>\"+b.game+\" &middot; \"+b.date+\"</div></div>\";"
            "h+=\"</div>\";"
            "h+=\"<div class='perf-hist-right'>\";"
            "h+=\"<span class='perf-hist-edge'>+\"+ep+\"% edge</span>\";"
            "h+=\"<span class='perf-hist-profit' style='color:\"+brc+\"'>\"+pbs2+pbr+\"u</span>\";"
            "h+=\"</div></div>\";"
            "});"
            "h+=\"</div>\";}"
            "if(updated){"
            "try{"
            "var d=new Date(updated);"
            "var opts={day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'America/Toronto'};"
            "var upd=d.toLocaleString('fr-CA',opts)+' ET';"
            "}catch(e){var upd=updated;}"
            "h+=\"<div class='perf-updated'>Mis a jour le \"+upd+\"</div>\";}"
            "h+=\"</div>\";"
            "document.getElementById('perf-content').innerHTML=h;}"

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
            # ── Variables & reset ─────────────────────────────────────────
            ":root{"
            "--bg:#F4F5F7;--s:#FFFFFF;--b:rgba(0,0,0,.08);--t:#111827;--m:#6B7280;"
            "--g:#059669;--g2:#D1FAE5;--g3:#065F46;"
            "--a:#D97706;--a2:#FEF3C7;--a3:#92400E;"
            "--r2:#DC2626;--r2b:#FEE2E2;--r2d:#991B1B;"
            "--r:14px;--rs:10px;"
            "--nav-h:56px;"
            "--accent:#2563EB;"
            "}"
            "@media(prefers-color-scheme:dark){:root{"
            "--bg:#0F1117;--s:#1A1D24;--b:rgba(255,255,255,.09);--t:#F1F2F4;--m:#9CA3AF;"
            "--g:#10B981;--g2:#064E3B;--g3:#6EE7B7;"
            "--a:#F59E0B;--a2:#451A03;--a3:#FCD34D;"
            "--r2:#EF4444;--r2b:#450A0A;--r2d:#FCA5A5;"
            "}}"
            "*{box-sizing:border-box;margin:0;padding:0}"
            "body{font-family:-apple-system,BlinkMacSystemFont,'Inter','Segoe UI',sans-serif;"
            "background:var(--bg);color:var(--t);line-height:1.6;font-size:15px;-webkit-font-smoothing:antialiased}"
            # ── Nav ───────────────────────────────────────────────────────
            "nav{background:var(--s);border-bottom:1px solid var(--b);position:sticky;top:0;z-index:100;"
            "box-shadow:0 1px 3px rgba(0,0,0,.06)}"
            ".ni{max-width:980px;margin:0 auto;padding:0 1rem;height:var(--nav-h);"
            "display:flex;align-items:center;justify-content:space-between;gap:12px}"
            ".nt{font-weight:700;font-size:15px;letter-spacing:-.3px;white-space:nowrap}"
            ".nt span{color:var(--accent)}"
            ".tabs{display:flex;gap:2px;background:var(--bg);padding:3px;border-radius:9px;border:1px solid var(--b)}"
            ".tab{background:transparent;border:none;border-radius:7px;padding:5px 14px;"
            "font-size:13px;font-weight:500;cursor:pointer;color:var(--m);transition:all .15s ease;white-space:nowrap}"
            ".tab:hover{color:var(--t);background:rgba(0,0,0,.04)}"
            ".tab.active{background:var(--s);color:var(--t);box-shadow:0 1px 3px rgba(0,0,0,.12)}"
            "@media(prefers-color-scheme:dark){.tab.active{box-shadow:0 1px 3px rgba(0,0,0,.4)}}"
            # ── Layout ────────────────────────────────────────────────────
            ".wrap{max-width:980px;margin:0 auto;padding:1.75rem 1rem}"
            # ── Header ────────────────────────────────────────────────────
            "header{margin-bottom:1.75rem}"
            "header h1{font-size:24px;font-weight:800;letter-spacing:-.5px;color:var(--t)}"
            "header p{font-size:13px;color:var(--m);margin-top:5px}"
            # ── Stats grid ────────────────────────────────────────────────
            ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:1.75rem}"
            ".box{background:var(--s);border:1px solid var(--b);border-radius:var(--r);padding:1rem 1.125rem;"
            "box-shadow:0 1px 4px rgba(0,0,0,.05)}"
            ".box .l{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--m)}"
            ".box .v{font-size:26px;font-weight:800;letter-spacing:-.5px;margin-top:4px;color:var(--t)}"
            # ── Section labels ────────────────────────────────────────────
            ".sec{font-size:11px;font-weight:700;color:var(--m);text-transform:uppercase;"
            "letter-spacing:.08em;margin:1.75rem 0 .875rem;display:flex;align-items:center;gap:8px}"
            ".sec::after{content:'';flex:1;height:1px;background:var(--b)}"
            # ── Bet cards ─────────────────────────────────────────────────
            ".bc{background:var(--s);border:1px solid var(--b);border-radius:var(--r);"
            "padding:1.125rem 1.25rem;margin-bottom:.875rem;"
            "box-shadow:0 1px 4px rgba(0,0,0,.05);transition:box-shadow .15s}"
            ".bc:hover{box-shadow:0 4px 12px rgba(0,0,0,.09)}"
            ".bh{display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;margin-bottom:1rem}"
            ".bt{font-size:10px;font-weight:700;color:var(--m);text-transform:uppercase;letter-spacing:.07em;margin-bottom:3px}"
            ".bn{font-size:19px;font-weight:800;letter-spacing:-.3px}"
            ".bg{font-size:12px;color:var(--m);margin-top:3px}"
            ".vd{font-size:12px;font-weight:600;padding:4px 12px;border-radius:20px;letter-spacing:.01em}"
            ".bs{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px}"
            ".stat{background:var(--bg);border:1px solid var(--b);border-radius:8px;padding:7px 10px}"
            ".sl{display:block;font-size:10px;color:var(--m);font-weight:600;text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}"
            ".sv{font-size:15px;font-weight:700}"
            # ── Edge bar ──────────────────────────────────────────────────
            ".edge-bar-wrap{margin:.875rem 0 0;}"
            ".edge-bar-label{font-size:10px;font-weight:700;color:var(--m);text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px;display:flex;justify-content:space-between}"
            ".edge-bar{height:6px;background:var(--b);border-radius:6px;overflow:hidden}"
            ".edge-bar-fill{height:100%;border-radius:6px;transition:width .3s ease}"
            # ── No bets ───────────────────────────────────────────────────
            ".no-bets{color:var(--m);font-size:13px;padding:.75rem 0}"
            # ── Table ─────────────────────────────────────────────────────
            ".tbl-wrap{overflow-x:auto;border:1px solid var(--b);border-radius:var(--r);"
            "box-shadow:0 1px 4px rgba(0,0,0,.05)}"
            "table{width:100%;border-collapse:collapse;font-size:13px}"
            "th{text-align:left;padding:.625rem .875rem;border-bottom:1px solid var(--b);"
            "font-size:10px;font-weight:700;color:var(--m);text-transform:uppercase;letter-spacing:.06em;background:var(--bg)}"
            "td{padding:.625rem .875rem;border-bottom:1px solid var(--b)}"
            "tr:last-child td{border-bottom:none}"
            "tbody tr:hover{background:rgba(0,0,0,.025)}"
            "@media(prefers-color-scheme:dark){tbody tr:hover{background:rgba(255,255,255,.025)}}"
            ".tm{color:var(--m);white-space:nowrap;font-size:12px;font-weight:500}"
            ".num{text-align:right;font-size:13px}"
            ".eb{background:var(--g2);color:var(--g3);font-size:11px;font-weight:700;"
            "padding:3px 9px;border-radius:20px;letter-spacing:.02em}"
            # ── Calculator ────────────────────────────────────────────────
            ".calc{background:var(--s);border:1px solid var(--b);border-radius:var(--r);"
            "padding:1.375rem;box-shadow:0 1px 4px rgba(0,0,0,.05)}"
            ".cform{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end;margin-bottom:1.125rem}"
            ".cf{display:flex;flex-direction:column;gap:5px}"
            ".cf label{font-size:11px;font-weight:700;color:var(--m);text-transform:uppercase;letter-spacing:.06em}"
            ".cf input{padding:9px 12px;border:1px solid var(--b);border-radius:8px;"
            "background:var(--bg);color:var(--t);font-size:14px;width:160px;outline:none}"
            ".cf input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(37,99,235,.15)}"
            ".calc button{padding:10px 20px;background:var(--accent);color:#fff;border:none;"
            "border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;transition:opacity .15s}"
            ".calc button:hover{opacity:.88}"
            ".cres{background:var(--bg);border:1px solid var(--b);border-radius:10px;padding:1rem 1.125rem;margin-bottom:1rem}"
            ".cr-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}"
            ".cr-stat{display:flex;flex-direction:column;gap:3px}"
            ".cr-stat span{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--m)}"
            ".cr-stat strong{font-size:18px;font-weight:800}"
            ".hi{display:flex;justify-content:space-between;padding:.45rem 0;border-bottom:1px solid var(--b);font-size:13px}"
            ".hi:last-child{border-bottom:none}"
            ".he{font-weight:700}"
            # ── Performance ───────────────────────────────────────────────
            ".perf-wrap{padding:.25rem 0}"
            ".perf-title{font-size:16px;font-weight:700;letter-spacing:-.3px;color:var(--t);"
            "margin-bottom:1.125rem;padding-bottom:.875rem;border-bottom:1px solid var(--b)}"
            ".perf-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:1.75rem}"
            ".perf-box{background:var(--s);border:1px solid var(--b);border-radius:var(--r);"
            "padding:1rem 1.125rem;box-shadow:0 1px 4px rgba(0,0,0,.05)}"
            ".perf-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--m);margin-bottom:5px}"
            ".perf-val{font-size:26px;font-weight:800;letter-spacing:-.5px}"
            ".perf-section-title{font-size:10px;font-weight:700;color:var(--m);text-transform:uppercase;"
            "letter-spacing:.08em;margin:1.5rem 0 .625rem;display:flex;align-items:center;gap:8px}"
            ".perf-section-title::after{content:'';flex:1;height:1px;background:var(--b)}"
            ".perf-edge-table{background:var(--s);border:1px solid var(--b);border-radius:var(--r);"
            "overflow:hidden;margin-bottom:1.75rem;box-shadow:0 1px 4px rgba(0,0,0,.05)}"
            ".perf-edge-row{display:flex;align-items:center;justify-content:space-between;"
            "padding:.875rem 1.125rem;border-bottom:1px solid var(--b);font-size:13px}"
            ".perf-edge-row:last-child{border-bottom:none}"
            ".perf-edge-label{font-weight:600;min-width:120px}"
            ".perf-edge-n{color:var(--m);min-width:70px}"
            ".perf-edge-wr{min-width:70px}"
            ".perf-edge-profit{font-weight:600;text-align:right}"
            ".perf-hist{display:flex;flex-direction:column;gap:0;background:var(--s);border:.5px solid var(--b);border-radius:var(--r);overflow:hidden;margin-bottom:1rem}"
            ".perf-hist-row{display:flex;align-items:center;justify-content:space-between;padding:.75rem 1rem;border-bottom:.5px solid var(--b);gap:1rem}"
            ".perf-hist-row:last-child{border-bottom:none}"
            ".perf-hist-left{display:flex;align-items:center;gap:.75rem;flex:1;min-width:0}"
            ".perf-hist-result{font-size:12px;font-weight:700;padding:4px 10px;border-radius:6px;flex-shrink:0}"
            ".perf-hist-bet{font-size:14px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
            ".perf-hist-game{font-size:11px;color:var(--m)}"
            ".perf-hist-right{display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex-shrink:0}"
            ".perf-hist-edge{font-size:11px;color:var(--m)}"
            ".perf-hist-profit{font-size:14px;font-weight:600}"
            ".perf-updated{font-size:11px;color:var(--m);text-align:right;margin-top:.5rem}"
            ".perf-empty{text-align:center;padding:3rem 1rem;color:var(--m)}"
            ".perf-empty-icon{font-size:40px;margin-bottom:1rem}"
            ".perf-empty-title{font-size:16px;font-weight:500;color:var(--t);margin-bottom:.5rem}"
            ".perf-empty-sub{font-size:13px;line-height:1.6;max-width:400px;margin:0 auto}"
            ".nba-header{font-size:15px;font-weight:500;color:var(--t);margin:0 0 1rem;padding-bottom:.75rem;border-bottom:.5px solid var(--b)}"
            ".nba-game{margin-bottom:1.5rem}"
            ".nba-matchup{font-size:14px;font-weight:500;color:var(--t);margin-bottom:.75rem}"
            ".nba-at{color:var(--m);font-weight:400;margin:0 6px}"
            ".nba-card{background:var(--bg);border:.5px solid var(--b);border-radius:8px;padding:12px 14px;margin-bottom:10px}"
            ".nba-card-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}"
            ".nba-player{font-size:14px;font-weight:500;color:var(--t);display:block}"
            ".nba-meta{font-size:11px;color:var(--m)}"
            ".nba-edge{font-size:12px;font-weight:500;padding:3px 10px;border-radius:20px;flex-shrink:0}"
            ".nba-bet-label{font-size:13px;font-weight:500;color:var(--t);margin-bottom:10px;border-left:3px solid #378ADD;padding-left:8px}"
            # ── NBA section ───────────────────────────────────────────────
            ".nba-header{font-size:16px;font-weight:700;letter-spacing:-.3px;color:var(--t);"
            "margin-bottom:1.125rem;padding-bottom:.875rem;border-bottom:1px solid var(--b)}"
            ".nba-game{background:var(--s);border:1px solid var(--b);border-radius:var(--r);"
            "padding:1.125rem;margin-bottom:1rem;box-shadow:0 1px 4px rgba(0,0,0,.05)}"
            ".nba-matchup{font-size:15px;font-weight:700;color:var(--t);margin-bottom:.875rem;"
            "padding-bottom:.625rem;border-bottom:1px solid var(--b)}"
            ".nba-at{color:var(--m);font-weight:400;margin:0 8px}"
            ".nba-card{background:var(--bg);border:1px solid var(--b);border-radius:var(--rs);"
            "padding:12px 14px;margin-bottom:10px}"
            ".nba-card-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}"
            ".nba-player{font-size:15px;font-weight:700;color:var(--t);display:block;letter-spacing:-.2px}"
            ".nba-meta{font-size:11px;color:var(--m);margin-top:2px}"
            ".nba-edge{font-size:12px;font-weight:700;padding:4px 12px;border-radius:20px;flex-shrink:0;letter-spacing:.01em}"
            ".nba-bet-label{font-size:13px;font-weight:700;color:var(--t);margin-bottom:10px;"
            "border-left:3px solid var(--accent);padding-left:10px}"
            ".nba-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-bottom:8px}"
            ".nba-stat{background:var(--s);border:1px solid var(--b);border-radius:7px;padding:6px 9px;font-size:11px;color:var(--m)}"
            ".nba-stat span{display:block;font-weight:600;text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}"
            ".nba-stat strong{font-size:14px;font-weight:700;color:var(--t)}"
            ".nba-note{font-size:11px;color:var(--accent);background:rgba(37,99,235,.08);border-radius:5px;"
            "padding:5px 10px;margin-top:5px;font-weight:500}"
            # ── MLB section ───────────────────────────────────────────────
            ".mlb-header{font-size:16px;font-weight:700;letter-spacing:-.3px;color:var(--t);"
            "margin-bottom:1.125rem;padding-bottom:.875rem;border-bottom:1px solid var(--b)}"
            ".mlb-game{background:var(--s);border:1px solid var(--b);border-radius:var(--r);"
            "padding:1.125rem;margin-bottom:1rem;box-shadow:0 1px 4px rgba(0,0,0,.05)}"
            ".mlb-matchup{font-size:15px;font-weight:700;color:var(--t);margin-bottom:.875rem;"
            "padding-bottom:.625rem;border-bottom:1px solid var(--b)}"
            ".mlb-at{color:var(--m);font-weight:400;margin:0 8px}"
            ".mlb-card{background:var(--bg);border:1px solid var(--b);border-radius:var(--rs);"
            "padding:12px 14px;margin-bottom:10px}"
            ".mlb-card-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}"
            ".mlb-player{font-size:15px;font-weight:700;color:var(--t);display:block;letter-spacing:-.2px}"
            ".mlb-meta{font-size:11px;color:var(--m);margin-top:2px}"
            ".mlb-edge{font-size:12px;font-weight:700;padding:4px 12px;border-radius:20px;flex-shrink:0;letter-spacing:.01em}"
            ".mlb-bet-label{font-size:13px;font-weight:700;color:var(--t);margin-bottom:10px;"
            "border-left:3px solid #E84646;padding-left:10px}"
            ".mlb-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-bottom:8px}"
            ".mlb-stat{background:var(--s);border:1px solid var(--b);border-radius:7px;padding:6px 9px;font-size:11px;color:var(--m)}"
            ".mlb-stat span{display:block;font-weight:600;text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}"
            ".mlb-stat strong{font-size:14px;font-weight:700;color:var(--t)}"
            ".mlb-note{font-size:11px;color:#B45309;background:rgba(217,119,6,.08);border-radius:5px;"
            "padding:5px 10px;margin-top:5px;font-weight:500}"
            # ── General ───────────────────────────────────────────────────
            ".disc{font-size:11px;color:var(--m);margin-top:2rem;padding-top:1rem;border-top:1px solid var(--b);line-height:1.8}"
            ".upd{font-size:11px;color:var(--m);text-align:right;margin-top:.5rem}"
            ".lineup-warning{background:var(--a2);border-left:3px solid var(--a);color:var(--a3);"
            "padding:10px 14px;border-radius:8px;font-size:12px;font-weight:500;margin:0 0 1rem}"
            # ── Retour de flamme ──────────────────────────────────────────
            ".retour-section{margin:1.25rem 0 0;border-top:1px solid var(--b);padding-top:1.25rem}"
            ".retour-title{font-size:15px;font-weight:700;color:var(--t);margin-bottom:4px;letter-spacing:-.2px}"
            ".retour-subtitle{font-size:12px;color:var(--m);margin-bottom:1rem;line-height:1.6}"
            ".retour-card{background:var(--s);border:1px solid var(--b);border-left:3px solid var(--accent);"
            "border-radius:var(--rs);padding:12px 14px;margin-bottom:10px;box-shadow:0 1px 3px rgba(0,0,0,.04)}"
            ".retour-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px}"
            ".retour-name{font-size:14px;font-weight:700;color:var(--t);display:block;letter-spacing:-.2px}"
            ".retour-meta{font-size:11px;color:var(--m);margin-top:2px}"
            ".retour-drop{font-size:13px;font-weight:700;flex-shrink:0;margin-left:8px}"
            ".retour-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:10px}"
            ".retour-stat{background:var(--bg);border:1px solid var(--b);border-radius:7px;padding:6px 8px;font-size:11px;color:var(--m)}"
            ".retour-stat span{display:block;font-weight:600;text-transform:uppercase;letter-spacing:.04em;margin-bottom:2px}"
            ".retour-stat strong{font-size:13px;font-weight:700;color:var(--t)}"
            ".retour-signal{font-size:11px;color:var(--accent);background:rgba(37,99,235,.08);"
            "border-radius:6px;padding:7px 10px;line-height:1.6;font-weight:500}"
            # ── Matchup grid ──────────────────────────────────────────────
            ".matchup-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:.875rem}"
            ".matchup-col{background:var(--bg);border:1px solid var(--b);border-radius:var(--rs);padding:.875rem}"
            ".mc-title{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:var(--m);margin-bottom:.5rem}"
            ".mc-stat{font-size:12px;margin-bottom:3px;font-weight:500}"
            ".mc-val{font-size:11px;color:var(--m);margin-top:5px;line-height:1.5}"
            ".mc-goalie{font-size:12px;margin-bottom:4px;font-weight:500}"
            ".mc-side{font-size:10px;color:var(--m);font-weight:700;margin-right:4px;text-transform:uppercase}"
            # ── Player bet cards ──────────────────────────────────────────
            ".player-bets{display:flex;flex-direction:column;gap:.875rem;margin-top:.875rem}"
            ".pb{background:var(--bg);border:1px solid var(--b);border-radius:var(--rs);"
            "overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.04)}"
            ".pb-head{display:flex;justify-content:space-between;align-items:flex-start;"
            "padding:.875rem 1rem .625rem;flex-wrap:wrap;gap:5px;background:var(--s);border-bottom:1px solid var(--b)}"
            ".pb-info{display:flex;align-items:center;gap:7px;flex-wrap:wrap}"
            ".pb-name{font-size:16px;font-weight:800;letter-spacing:-.3px}"
            ".pb-pos{font-size:10px;font-weight:700;color:var(--m);background:var(--bg);padding:2px 8px;"
            "border-radius:20px;border:1px solid var(--b);text-transform:uppercase;letter-spacing:.04em}"
            ".pb-team{font-size:12px;color:var(--m);font-weight:500}"
            ".pb-season{font-size:11px;color:var(--m);font-weight:500}"
            ".pb-main-bet{border-left:4px solid;padding:.875rem 1rem;background:var(--s);margin:.375rem 0}"
            ".pbm-label{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;color:var(--m);margin-bottom:4px}"
            ".pbm-market{font-size:18px;font-weight:800;margin-bottom:4px;letter-spacing:-.3px}"
            ".pbm-detail{font-size:12px;color:var(--m);margin-bottom:.75rem;font-weight:500}"
            ".pbm-odds{display:flex;gap:8px;flex-wrap:wrap}"
            ".pbm-odd{display:flex;flex-direction:column;gap:3px;background:var(--bg);border:1px solid var(--b);"
            "border-radius:8px;padding:6px 10px;min-width:82px}"
            ".pbm-odd span{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--m)}"
            ".pbm-odd strong{font-size:15px;font-weight:800}"
            ".edge-highlight{border:1.5px solid currentColor;background:var(--bg)!important}"
            ".pb-shots{padding:.875rem 1rem;border-top:1px solid var(--b)}"
            ".pbs-title{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:var(--m);margin-bottom:.625rem}"
            ".pbs-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:.5rem}"
            ".pbs-col{display:flex;flex-direction:column;gap:4px}"
            ".pbs-stat{font-size:11px;color:var(--m);display:flex;flex-direction:column;font-weight:500}"
            ".pbs-stat strong{font-size:13px;font-weight:700;color:var(--t)}"
            ".pbs-others{font-size:11px;color:var(--m);padding-top:.5rem;border-top:1px solid var(--b);font-weight:500}"
            ".pb-context{padding:.625rem 1rem;background:var(--bg);border-top:1px solid var(--b);"
            "display:flex;flex-direction:column;gap:5px}"
            ".pb-note{font-size:12px;color:var(--t);font-weight:500}"
            ".pb-others-bets{padding:.5rem 1rem;font-size:12px;color:var(--m);border-top:1px solid var(--b);font-weight:500}"
            ".pb-other-bet{font-weight:700;margin-right:8px}"
            # ── Props game cards ──────────────────────────────────────────
            ".pg{background:var(--s);border:1px solid var(--b);border-radius:var(--r);"
            "padding:1.375rem;margin-bottom:1.125rem;box-shadow:0 1px 4px rgba(0,0,0,.05)}"
            ".ph{margin-bottom:1.125rem}"
            ".pm{font-size:17px;font-weight:800;letter-spacing:-.3px;margin-bottom:.5rem}"
            ".pm-away{color:var(--t)}"
            ".pm-at{color:var(--m);font-weight:400;margin:0 8px}"
            ".pm-home{color:var(--t)}"
            # ── History & perf ────────────────────────────────────────────
            ".perf-edge-wr{min-width:70px;font-weight:600}"
            ".perf-edge-profit{font-weight:700;text-align:right}"
            ".perf-hist{display:flex;flex-direction:column;background:var(--s);border:1px solid var(--b);"
            "border-radius:var(--r);overflow:hidden;margin-bottom:1rem;box-shadow:0 1px 4px rgba(0,0,0,.05)}"
            ".perf-hist-row{display:flex;align-items:center;justify-content:space-between;"
            "padding:.875rem 1.125rem;border-bottom:1px solid var(--b);gap:1rem;transition:background .1s}"
            ".perf-hist-row:hover{background:rgba(0,0,0,.02)}"
            ".perf-hist-row:last-child{border-bottom:none}"
            ".perf-hist-left{display:flex;align-items:center;gap:.875rem;flex:1;min-width:0}"
            ".perf-hist-result{font-size:12px;font-weight:800;padding:4px 12px;border-radius:7px;flex-shrink:0;letter-spacing:.02em}"
            ".perf-hist-bet{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
            ".perf-hist-game{font-size:11px;color:var(--m);font-weight:500;margin-top:1px}"
            ".perf-hist-right{display:flex;flex-direction:column;align-items:flex-end;gap:3px;flex-shrink:0}"
            ".perf-hist-edge{font-size:11px;color:var(--m);font-weight:500}"
            ".perf-hist-profit{font-size:14px;font-weight:800}"
            ".perf-updated{font-size:11px;color:var(--m);text-align:right;margin-top:.5rem;font-weight:500}"
            ".perf-empty{text-align:center;padding:3rem 1rem;color:var(--m)}"
            ".perf-empty-icon{font-size:42px;margin-bottom:1rem}"
            ".perf-empty-title{font-size:17px;font-weight:700;color:var(--t);margin-bottom:.5rem;letter-spacing:-.2px}"
            ".perf-empty-sub{font-size:13px;line-height:1.7;max-width:400px;margin:0 auto}"
            # ── Mobile ────────────────────────────────────────────────────
            "@media(max-width:640px){"
            ".tabs{overflow-x:auto;flex-wrap:nowrap;-webkit-overflow-scrolling:touch}"
            ".tab{padding:5px 10px;font-size:12px}"
            ".matchup-grid,.pbs-grid{grid-template-columns:1fr}"
            ".pbm-odds{gap:6px}"
            ".perf-grid{grid-template-columns:repeat(2,1fr)}"
            ".perf-edge-row{flex-wrap:wrap;gap:4px}"
            ".cr-grid{grid-template-columns:repeat(2,1fr)}"
            ".nba-stats{grid-template-columns:repeat(2,1fr)}"
            ".retour-stats{grid-template-columns:repeat(2,1fr)}"
            ".box .v{font-size:22px}"
            ".bn{font-size:16px}"
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
