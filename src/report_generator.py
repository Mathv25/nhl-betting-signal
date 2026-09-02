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
        nba_html     = self._nba_section(data.get("nba_analysis", []))
        calc_html    = self._calculator()
        perf_html    = self._performance_section()
        mlb_html     = self._mlb_section(data.get("mlb_analysis", []))
        power_html   = self._power_section(data.get("power_analysis", []))
        ai_html      = self._ai_analysis_section(data.get("ai_analysis", {}))

        signal_json = json.dumps(data, ensure_ascii=False, default=str)

        parts = [
            "<!DOCTYPE html><html lang=\"fr\"><head>",
            "<meta charset=\"UTF-8\">",
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
            "<meta name=\"signal-generated-at\" content=\"" + gen_at + "\">",
            "<title>NHL Signal - " + date_str + "</title>",
            self._css(),
            "<script>window._SIGNAL=" + signal_json + ";</script>",
            "</head><body>",
            self._nav(),
            "<div class=\"wrap\">",
            self._header(),
            self._grid(date_str, total_games, total_value),
            "<div id=\"tab-signal\">",
            # ── NHL market edges ──
            "<div class=\"sec\">Bets recommandes - Edge minimum 5%</div>",
            bet_cards,
            # ── NHL player props ──
            "<div class=\"sec\" style=\"margin-top:1.5rem\">Props joueurs NHL</div>",
            props_html if props_html else "<p class=\"no-bets\">Aucun prop NHL identifie.</p>",
            # ── NBA ──
            "<div class=\"sec\" style=\"margin-top:1.5rem\">NBA</div>",
            nba_html if nba_html else "<p class=\"no-bets\">Aucun bet NBA identifie.</p>",
            # ── MLB: PAS ici — la section vit dans l'onglet MLB dédié. La dupliquer
            #    créait des id='kc-<joueur>' en double → getElementById renvoyait le
            #    div caché (onglet Signal) et le calculateur ne s'ouvrait pas sous les K.
            "<div class=\"sec\" style=\"margin-top:1.5rem\">MLB</div>",
            "<p class=\"no-bets\">Props MLB dans l'onglet <b>MLB</b> ↑ (calculateur d'edge sur chaque carte).</p>",
            # ── Table matchs NHL ──
            "<div class=\"sec\" style=\"margin-top:1.5rem\">Tous les matchs NHL</div>",
            self._table(rows),
            # ── Expert IA ──
            "<div class=\"sec\" style=\"margin-top:1.5rem\">Analyse experte IA</div>",
            ai_html,
            "</div>",
            "<div id=\"tab-props\" style=\"display:none\">",
            props_html if props_html else "<p class=\"no-bets\">Analyse joueurs disponible apres le prochain run.</p>",
            "</div>",
            "<div id=\"tab-nba\" style=\"display:none\">",
            nba_html,
            "</div>",
            "<div id=\"tab-mlb\" style=\"display:none\">",
            mlb_html,
            power_html,
            "</div>",
            "<div id=\"tab-perf\" style=\"display:none\">",
            perf_html,
            "</div>",
            "<div id=\"tab-ai\" style=\"display:none\">",
            ai_html,
            "</div>",
            self._disclaimer(gen_display, data.get("odds_api")),
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
            ""
            "<button class=\"tab\" onclick=\"showTab('tab-ai',this)\">Expert IA</button>"
            "</div>"
            "<button id=\"refreshBtn\" onclick=\"refreshData()\" title=\"Recharger le signal\" style=\""
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
            "<div class=\"box\"><div class=\"l\">Date</div><div class=\"v\" id=\"stat-date\" style=\"font-size:17px\">" + date_str + "</div></div>"
            "<div class=\"box\"><div class=\"l\">Matchs analyses</div><div class=\"v\" id=\"stat-games\">" + str(total_games) + "</div></div>"
            "<div class=\"box\"><div class=\"l\">Bets +EV (>=5%)</div><div class=\"v\" id=\"stat-value\" style=\"color:var(--g)\">" + str(total_value) + "</div></div>"
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
                "<div class=\"stat\"><span class=\"sl\">Cote b365</span><span class=\"sv\">" + str(round(b.get("b365_odds", 0), 2)) + "</span></div>"
                "<div class=\"stat\"><span class=\"sl\">Prob b365</span><span class=\"sv\">" + str(round(b.get("b365_implied", 0), 1)) + "%</span></div>"
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

                    # Ne pas inventer de cote: si elle est inconnue, on l'affiche comme inconnue.
                    est_odds_str = str(b.get("est_odds") or "n/d")
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
            home   = game_data.get("home_team", "")
            away   = game_data.get("away_team", "")
            bets   = game_data.get("bets", [])
            status = game_data.get("status", "")
            if not bets:
                continue
            status_badge = (
                " <span style='background:#FEE2E2;color:#991B1B;font-size:11px;"
                "padding:2px 8px;border-radius:6px;font-weight:500'>En cours</span>"
                if status == "started" else ""
            )
            html += (
                "<div class='mlb-game'>"
                "<div class='mlb-matchup'>"
                + away + " <span class='mlb-at'>@</span> " + home + status_badge
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
                adj_raw     = b.get("adj_proj_raw")
                adj_mult    = b.get("adj_mult")
                adj_mult_rw = b.get("adj_mult_raw")
                opp_k_rate  = b.get("opp_k_rate")
                opp_k_src   = b.get("opp_k_source", "")
                park_factor = b.get("park_factor", 1.0)
                dk_implied  = b.get("dk_implied", 52.6)
                team        = b.get("team", "")
                opponent    = b.get("opponent", "")
                context     = b.get("context", [])

                type_icon = "⚾" if player_type == "pitcher" else "🏏"
                type_label = "Lanceur" if player_type == "pitcher" else "Frappeur"

                # Lanceurs: badge = projection (pas d'edge — cotes bet365 inconnues)
                # Frappeurs HR: badge = edge réel calculé
                if player_type == "pitcher":
                    badge_color = "#2563EB"
                    badge_bg    = "#EFF6FF"
                    badge_txt   = "proj " + str(adj_proj) + "K"
                else:
                    badge_color = "#0F6E56" if edge >= 15 else "#BA7517"
                    badge_bg    = "#E1F5EE" if edge >= 15 else "#FAEEDA"
                    badge_txt   = "+" + str(edge) + "% edge"

                html += (
                    "<div class='mlb-card'>"
                    "<div class='mlb-card-head'>"
                    "<div>"
                    "<span class='mlb-player'>" + type_icon + " " + player + "</span>"
                    "<span class='mlb-meta'>" + type_label + " · " + team.split()[-1] + " vs " + opponent.split()[-1] + "</span>"
                    "</div>"
                    "<div class='mlb-edge' style='color:" + badge_color + ";background:" + badge_bg + "'>"
                    + badge_txt +
                    "</div>"
                    "</div>"
                    "<div class='mlb-bet-label'>" + market + "</div>"
                    "<div class='mlb-stats'>"
                    "<div class='mlb-stat'><span>Moy saison</span><strong>" + str(season_avg) + "K</strong></div>"
                    "<div class='mlb-stat'><span>Proj. régressée</span><strong>" + str(adj_proj) + "K</strong>"
                    + ("<span style='text-transform:none;font-weight:500'>x" + f"{adj_mult:.3f}" + "</span>" if adj_mult else "")
                    + "</div>"
                )
                # Comparaison brute vs régressée — à suivre une semaine avant de
                # trancher sur l'exposant K_REGRESSION_EXP.
                if adj_raw is not None and player_type == "pitcher":
                    delta = adj_raw - adj_proj
                    html += ("<div class='mlb-stat'><span>Proj. brute (ancienne)</span>"
                             "<strong style='color:var(--m)'>" + str(adj_raw) + "K</strong>"
                             + ("<span style='text-transform:none;font-weight:500'>x" + f"{adj_mult_rw:.3f}"
                                + " · écart " + f"{delta:+.2f}" + "K</span>" if adj_mult_rw else ""))
                    html += "</div>"
                if opp_k_rate is not None and player_type == "pitcher":
                    k_lbl = "K% adverse" + (" — " + opp_k_src if opp_k_src else "")
                    html += "<div class='mlb-stat'><span>" + k_lbl + "</span><strong>" + str(opp_k_rate) + "%</strong>"
                    lg_k = b.get("league_k_rate")
                    if lg_k:
                        html += "<span style='text-transform:none;font-weight:500'>ligue " + str(lg_k) + "%</span>"
                    html += "</div>"
                pf_color = "#B45309" if park_factor >= 1.08 else ("#0F6E56" if park_factor <= 0.92 else "#6B7280")
                html += "<div class='mlb-stat'><span>Park factor</span><strong style='color:" + pf_color + "'>" + str(park_factor) + "</strong></div>"
                if player_type != "pitcher":
                    ec = "#0F6E56" if edge >= 15 else "#BA7517"
                    html += (
                        "<div class='mlb-stat'><span>Notre prob</span><strong style='color:" + ec + "'>" + str(prob) + "%</strong></div>"
                        "<div class='mlb-stat'><span>1/4 Kelly</span><strong>" + str(kelly) + "% BR</strong></div>"
                    )
                else:
                    html += "<div class='mlb-stat' style='color:var(--m);font-size:11px'>Edge calculé via le calculateur ↑</div>"
                html += "</div>"
                # Courbe K — probs par niveau + calculateur d'edge interactif
                k_curve = b.get("k_curve", [])
                if k_curve and player_type == "pitcher":
                    cid = player.replace(" ","_")
                    # Cotes API disponibles → EV affichée sur chaque palier.
                    # Sinon → calculateur manuel (fallback quota/API en panne).
                    coted = b.get("odds_rungs", 0) or 0
                    src   = next((kc.get("baseline_source", "") for kc in k_curve
                                  if kc.get("best_odds")), "")
                    nbk   = next((kc.get("n_books", 0) for kc in k_curve
                                  if kc.get("best_odds")), 0)
                    if coted:
                        title = ("EV par palier — meilleure cote du marché · baseline "
                                 + (src or "?") + " · " + str(nbk) + " book(s)")
                    else:
                        title = "Prob K — cliquer un niveau puis entrer la cote bet365 (cotes API indisponibles)"
                    html += "<div class='mlb-k-curve'><span class='mlb-k-curve-title'>" + title + "</span>"
                    for kc in k_curve:
                        k = kc.get("k_exact", 0)
                        if k < 3 or k > 10:
                            continue
                        is_best = abs(kc.get("line", 0) - b.get("line", 0)) < 0.1
                        kc_bg  = "rgba(15,110,86,0.12)" if is_best else "transparent"
                        kc_bdr = "2px solid #0F6E56" if is_best else "1px solid #E5E7EB"
                        prob   = kc.get("prob", 0)
                        odds   = kc.get("best_odds")
                        html += (
                            "<div class='mlb-k-cell' style='border:" + kc_bdr + ";background:" + kc_bg
                            + ";cursor:pointer' onclick=\"mlbCalcSel('" + cid + "'," + str(k) + "," + str(prob) + ")\">"
                            "<div class='mlb-k-num'>K≥" + str(k) + "</div>"
                            "<div class='mlb-k-prob'>" + str(prob) + "%</div>"
                        )
                        if odds:
                            ev  = kc.get("ev_pct", 0)
                            evc = "#0F6E56" if ev > 0 else "#B45309"
                            html += (
                                "<div class='mlb-k-ev' style='color:" + evc + "'>"
                                + ("+" if ev > 0 else "") + str(ev) + "% EV</div>"
                                "<div class='mlb-k-book'>" + f"{odds:.2f}" + " "
                                + str(kc.get("best_book", ""))[:9] + "</div>"
                            )
                        html += "</div>"
                    html += "</div>"
                    if not coted:
                        html += (
                            "<div class='mlb-k-calc' id='kc-" + cid + "' style='display:none'>"
                            "K≥<b id='kc-k-" + cid + "'></b> · Notre prob: <b id='kc-p-" + cid + "'></b>% · "
                            "Cote bet365: <input id='kc-i-" + cid + "' class='mlb-k-odds-input' type='number' "
                            "step='0.01' min='1.01' placeholder='ex: 1.41' oninput=\"mlbCalcEdge('" + cid + "')\"> "
                            "<b id='kc-e-" + cid + "'></b>"
                            "</div>"
                        )
                # 4 notes: rolling, K% adverse, ajustement régressé vs brut,
                # distribution des manches. Sous 4 la comparaison du chantier
                # en cours est tronquée.
                for note in context[:4]:
                    html += "<div class='mlb-note'>" + note + "</div>"
                html += "</div>"
            html += "</div>"
        return html

    def _power_section(self, power_analysis: list) -> str:
        if not power_analysis:
            return ""

        html = "<div class='mlb-header' style='margin-top:1.5rem'>🔥 Frappeurs — Candidats 4+ Bases</div>"
        for game_data in power_analysis:
            batters = game_data.get("power_batters", [])
            if not batters:
                continue
            home = game_data.get("home_team", "")
            away = game_data.get("away_team", "")
            html += (
                "<div class='mlb-game'>"
                "<div class='mlb-matchup'>" + away + " <span class='mlb-at'>@</span> " + home + "</div>"
            )
            for b in batters[:6]:
                player    = b.get("player", "")
                team      = b.get("team", "")
                mean_tb   = b.get("mean_tb", 0)
                rolling   = b.get("rolling_avg", 0)
                season    = b.get("season_avg", 0)
                hr_rate   = b.get("hr_rate", 0)
                hot       = b.get("hot_streak", 0)
                p4        = b.get("p4", 0)
                curve     = b.get("curve", [])
                cid       = player.replace(" ", "_")

                hot_str = ("↑ En feu" if hot > 0.3 else "↓ En baisse" if hot < -0.3 else "→ Stable")
                hot_col = "#0F6E56" if hot > 0.3 else "#DC2626" if hot < -0.3 else "#6B7280"

                opp = b.get("opponent", "")
                ctx = b.get("context", [])
                if opp or ctx:
                    _items = "".join(
                        "<span style='display:inline-block;margin:2px 4px 0 0;padding:2px 6px;"
                        "background:#EDE9FE;border-radius:4px'>" + str(x) + "</span>"
                        for x in ctx
                    )
                    matchup_html = (
                        "<div style='margin:6px 0;padding:8px 10px;background:#F5F3FF;"
                        "border-radius:8px;font-size:12px;color:#4C1D95'>"
                        + ("<b>vs " + opp + "</b><br>" if opp else "")
                        + _items +
                        "</div>"
                    )
                else:
                    matchup_html = ""

                html += (
                    "<div class='mlb-card'>"
                    "<div class='mlb-card-head'>"
                    "<div>"
                    "<span class='mlb-player'>🏏 " + player + "</span>"
                    "<span class='mlb-meta'>" + team.split()[-1] + "</span>"
                    "</div>"
                    "<div class='mlb-edge' style='color:#7C3AED;background:#F5F3FF'>"
                    "P(4+TB) " + str(p4) + "%"
                    "</div>"
                    "</div>"
                    "<div class='mlb-stats'>"
                    "<div class='mlb-stat'><span>Moy TB (blend)</span><strong>" + str(mean_tb) + "</strong></div>"
                    "<div class='mlb-stat'><span>Rolling " + str(b.get("games", 0)) + "j</span><strong>" + str(rolling) + "</strong></div>"
                    "<div class='mlb-stat'><span>Saison</span><strong>" + str(season) + "</strong></div>"
                    "<div class='mlb-stat'><span>HR/match</span><strong>" + str(hr_rate) + "</strong></div>"
                    "<div class='mlb-stat'><span>Tendance</span><strong style='color:" + hot_col + "'>" + hot_str + "</strong></div>"
                    "</div>"
                    + matchup_html +
                    "<div class='mlb-k-curve'>"
                    "<span class='mlb-k-curve-title'>P(TB ≥ N) — cliquer, entrer cote bet365</span>"
                )
                for c in curve:
                    n    = c.get("n", 0)
                    prob = c.get("prob", 0)
                    html += (
                        "<div class='mlb-k-cell' style='border:1px solid var(--b);cursor:pointer'"
                        " onclick=\"mlbCalcSel('" + cid + "'," + str(n) + "," + str(prob) + ")\">"
                        "<div class='mlb-k-num'>TB≥" + str(n) + "</div>"
                        "<div class='mlb-k-prob'>" + str(prob) + "%</div>"
                        "</div>"
                    )
                html += (
                    "</div>"
                    "<div class='mlb-k-calc' id='kc-" + cid + "' style='display:none'>"
                    "TB≥<b id='kc-k-" + cid + "'></b> · Notre prob: <b id='kc-p-" + cid + "'></b>% · "
                    "Cote bet365: <input id='kc-i-" + cid + "' class='mlb-k-odds-input' type='number' "
                    "step='0.01' min='1.01' placeholder='ex: 5.00' oninput=\"mlbCalcEdge('" + cid + "')\"> "
                    "<b id='kc-e-" + cid + "'></b>"
                    "</div>"
                    "</div>"
                )
            html += "</div>"
        return html

    def _ai_analysis_section(self, ai_data: dict) -> str:
        if not ai_data:
            return (
                "<div style='color:var(--m);padding:1.5rem;font-size:13px;background:var(--s);"
                "border-radius:10px;text-align:center'>"
                "Analyse IA non disponible — verifiez que ANTHROPIC_API_KEY est configure."
                "</div>"
            )

        resume = ai_data.get("resume", "")
        bets = ai_data.get("bets", [])
        opportunites = ai_data.get("opportunites_manquees", "")
        conseil = ai_data.get("conseil_du_jour", "")

        html = "<div style='display:flex;flex-direction:column;gap:1rem'>"

        # Resume
        if resume:
            html += (
                "<div style='background:linear-gradient(135deg,#1a1f2e,#252b3b);border:1px solid #334;"
                "border-radius:12px;padding:1.2rem 1.5rem'>"
                "<div style='font-size:11px;font-weight:700;color:#7B93FF;letter-spacing:.1em;margin-bottom:.5rem'>RESUME DU JOUR</div>"
                "<div style='color:#E2E8F0;font-size:14px;line-height:1.6'>" + resume + "</div>"
                "</div>"
            )

        # Bet cards
        for b in bets:
            verdict = b.get("verdict", "")
            confiance = b.get("confiance", 3)
            bet_name = b.get("bet", "")
            analyse = b.get("analyse", "")
            risques = b.get("risques", "")
            suggestion = b.get("suggestion", "")

            if verdict == "JOUER":
                v_color = "#0F6E56"
                v_bg = "#E1F5EE"
                v_border = "#0F6E56"
            elif verdict == "JOUER AVEC PRUDENCE":
                v_color = "#B45309"
                v_bg = "#FAEEDA"
                v_border = "#B45309"
            else:
                v_color = "#B91C1C"
                v_bg = "#FEE2E2"
                v_border = "#B91C1C"

            stars = ("★" * confiance) + ("☆" * (5 - confiance))

            html += (
                "<div style='background:var(--s);border:1px solid var(--b);border-left:4px solid "
                + v_border + ";border-radius:12px;padding:1.2rem 1.5rem'>"
                "<div style='display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.8rem;gap:.5rem;flex-wrap:wrap'>"
                "<div style='font-size:14px;font-weight:700;color:var(--t)'>" + bet_name + "</div>"
                "<div style='display:flex;gap:.5rem;align-items:center;flex-shrink:0'>"
                "<span style='font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;"
                "color:" + v_color + ";background:" + v_bg + "'>" + verdict + "</span>"
                "<span style='font-size:12px;color:#F59E0B;letter-spacing:1px'>" + stars + "</span>"
                "</div>"
                "</div>"
            )
            if analyse:
                html += (
                    "<div style='font-size:13px;color:var(--m);line-height:1.6;margin-bottom:.6rem'>"
                    + analyse + "</div>"
                )
            if risques:
                html += (
                    "<div style='font-size:12px;background:#FEF3C7;border-radius:6px;padding:.5rem .8rem;"
                    "color:#92400E;margin-bottom:.5rem'>"
                    "<strong>⚠ Risques:</strong> " + risques + "</div>"
                )
            if suggestion:
                html += (
                    "<div style='font-size:12px;background:#EFF6FF;border-radius:6px;padding:.5rem .8rem;color:#1E40AF'>"
                    "<strong>💡 Suggestion:</strong> " + suggestion + "</div>"
                )
            html += "</div>"

        # Opportunites manquees
        if opportunites:
            html += (
                "<div style='background:var(--s);border:1px solid var(--b);border-radius:12px;padding:1.2rem 1.5rem'>"
                "<div style='font-size:11px;font-weight:700;color:#7B93FF;letter-spacing:.1em;margin-bottom:.5rem'>OPPORTUNITES MANQUEES</div>"
                "<div style='font-size:13px;color:var(--m);line-height:1.6'>" + opportunites + "</div>"
                "</div>"
            )

        # Conseil du jour
        if conseil:
            html += (
                "<div style='background:linear-gradient(135deg,#0F6E56,#0a5240);border-radius:12px;"
                "padding:1.2rem 1.5rem'>"
                "<div style='font-size:11px;font-weight:700;color:#6EE7B7;letter-spacing:.1em;margin-bottom:.5rem'>CONSEIL DU JOUR</div>"
                "<div style='font-size:14px;color:#fff;line-height:1.6'>" + conseil + "</div>"
                "</div>"
            )

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

    def _disclaimer(self, gen_display, odds_state=None):
        """
        Le bandeau de quota n'est pas cosmetique: quand la cle Odds API est
        epuisee ou refusee, le rapport s'affiche normalement mais SANS cotes,
        et un ladder sans cotes ressemble a un marche muet. La ligne ci-dessous
        dit laquelle des deux situations on regarde.
        """
        state  = odds_state or {}
        quota  = ""
        if state:
            rem = state.get("remaining")
            if not state.get("healthy", True):
                errs = "; ".join(state.get("errors", [])[:2]) or "cle indisponible"
                quota = ("<p class=\"upd\" style=\"color:#B45309\">Cotes API indisponibles — "
                         + errs + " · les cotes affichees viennent du calculateur manuel</p>")
            elif rem is not None:
                low = " style=\"color:#B45309\"" if rem < 100 else ""
                budget = state.get("day_budget")
                pace = ("" if budget is None else
                        " · jour " + str(state.get("spent_today", 0))
                        + "/" + str(budget) + " credits")
                quota = ("<p class=\"upd\"" + low + ">Quota Odds API: " + str(rem)
                         + " credit(s) restant(s) · " + str(state.get("credits_spent", 0))
                         + " depense(s) cette execution · " + str(state.get("cache_hits", 0))
                         + " reponse(s) du cache" + pace + "</p>")
        return (
            "<p class=\"disc\">"
            "Signal informatif et educatif uniquement. Aucun resultat garanti. "
            "Verifiez les cotes directement sur DraftKings avant de parier. "
            "Jouez de facon responsable. 18+"
            "</p>"
            "<p class=\"upd\" id=\"stat-gentime\">Genere le " + gen_display + "</p>"
            + quota
        )

    def _js_render(self):
        """JS functions: refreshData, renderAll, renderSignalTab, renderNBATab, renderMLBTab, renderPropsTab."""
        return (
            "var gSignal=window._SIGNAL||null;"

            "var GH_REPO='Mathv25/nhl-betting-signal';"
            "var GH_WORKFLOW='hourly_signal.yml';"

            "async function refreshData(){"
            "var btn=document.getElementById('refreshBtn');"
            "var orig=btn.textContent;"
            # Get or prompt for GitHub token
            "var token=localStorage.getItem('gh_workflow_token');"
            "if(!token){"
            "token=prompt('Entre ton GitHub Personal Access Token (Actions: write):\\n\\nCree un token sur github.com/settings/tokens avec la permission workflow.');"
            "if(!token)return;"
            "localStorage.setItem('gh_workflow_token',token);}"
            # Trigger workflow
            "btn.textContent='\u23f3 Generation...';"
            "btn.disabled=true;"
            "try{"
            "var r=await fetch('https://api.github.com/repos/'+GH_REPO+'/actions/workflows/'+GH_WORKFLOW+'/dispatches',{"
            "method:'POST',"
            "headers:{'Authorization':'token '+token,'Accept':'application/vnd.github.v3+json','Content-Type':'application/json'},"
            "body:JSON.stringify({ref:'main'})});"
            "if(r.status===204){"
            "btn.textContent='\u2713 Signal en generation (~2 min)';"
            "setTimeout(async function(){"
            "try{"
            "var r2=await fetch('signal.json?t='+Date.now());"
            "if(r2.ok){gSignal=await r2.json();renderAll(gSignal);}"
            "}catch(e){}"
            "btn.textContent=orig;btn.disabled=false;"
            "},130000);"
            "}else if(r.status===401||r.status===403){"
            "localStorage.removeItem('gh_workflow_token');"
            "btn.textContent='\u2717 Token invalide';"
            "setTimeout(function(){btn.textContent=orig;btn.disabled=false;},3000);"
            "}else{"
            "btn.textContent='\u2717 Erreur '+r.status;"
            "setTimeout(function(){btn.textContent=orig;btn.disabled=false;},3000);"
            "}"
            "}catch(e){"
            "btn.textContent='\u2717 Erreur reseau';"
            "setTimeout(function(){btn.textContent=orig;btn.disabled=false;},3000);}}"

            "function renderAll(d){"
            "renderHeaderGrid(d);renderSignalTab(d);renderPropsTab(d);renderNBATab(d);renderMLBTab(d);mlbCalcInit(d);}"

            "function _mlbPitchers(d){var out=[];(d.mlb_analysis||[]).forEach(function(g){(g.bets||[]).forEach(function(b){if(b.player_type==='pitcher'&&(b.k_curve||[]).length)out.push(b);});});return out;}"
            "function mlbCalcInit(d){var sel=document.getElementById('mlb-sel');if(!sel)return;"
            "var pitchers=_mlbPitchers(d);window._mlbPitcherList=pitchers;"
            "sel.innerHTML='<option value=\"\">Sélectionner un lanceur…</option>';"
            "pitchers.forEach(function(b,i){var opt=document.createElement('option');opt.value=i;"
            "opt.textContent=b.player+' — proj '+(b.adj_proj||0)+'K vs '+((b.opponent||'').split(' ').pop());"
            "sel.appendChild(opt);});}"
            "function mlbCalcLoad(){var sel=document.getElementById('mlb-sel');var idx=parseInt(sel.value);"
            "var curve=document.getElementById('mlb-calc-curve');var res=document.getElementById('mlb-calc-edge');"
            "document.getElementById('mlb-calc-odds').value='';if(res)res.textContent='';"
            "if(!curve)return;if(isNaN(idx)){curve.innerHTML='';return;}"
            "var b=(window._mlbPitcherList||[])[idx];if(!b){curve.innerHTML='';return;}"
            "window._mlbCalcCurve=b.k_curve||[];window._mlbCalcK=null;window._mlbCalcProb=null;"
            "curve.innerHTML=(b.k_curve||[]).filter(function(c){return c.k_exact>=3&&c.k_exact<=10;}).map(function(c){"
            "var isBest=Math.abs((c.line||0)-(b.line||0))<0.1;"
            "return '<div class=\"mlb-calc-cell'+(isBest?' sel':'')+'\" id=\"mcc-'+c.k_exact+'\" onclick=\"mlbCalcK('+c.k_exact+','+c.prob+')\">"
            "<div class=\"kn\">K≥'+c.k_exact+'</div><div class=\"kp\">'+c.prob+'%</div></div>';}).join('');}"
            "function mlbCalcK(k,prob){window._mlbCalcK=k;window._mlbCalcProb=prob;"
            "(window._mlbCalcCurve||[]).forEach(function(c){var el=document.getElementById('mcc-'+c.k_exact);if(el)el.classList.toggle('sel',c.k_exact===k);});"
            "mlbCalcRun();}"
            "function mlbCalcRun(){var prob=window._mlbCalcProb;var o=parseFloat(document.getElementById('mlb-calc-odds').value);"
            "var el=document.getElementById('mlb-calc-edge');if(!el)return;"
            "if(!prob||!o||o<=1){el.textContent='';return;}"
            "var impl=1/o*100;var edge=((prob-impl)/impl*100).toFixed(1);"
            "var col=edge>0?'#059669':'#DC2626';"
            "el.innerHTML='<span style=\"color:'+col+'\">K≥'+window._mlbCalcK+' · '+(edge>0?'+':'')+edge+'% edge</span>"
            "<span style=\"color:var(--m);font-size:11px;margin-left:8px\">b365 impl '+impl.toFixed(1)+'%</span>';}"
            "function mlbCalcSel(cid,k,prob){"
            "var el=document.getElementById('kc-'+cid);if(!el)return;"
            "el.style.display='flex';"
            "document.getElementById('kc-k-'+cid).textContent=k;"
            "document.getElementById('kc-p-'+cid).textContent=prob;"
            "document.getElementById('kc-i-'+cid).value='';"
            "document.getElementById('kc-e-'+cid).textContent='';}"

            "function mlbCalcEdge(cid){"
            "var p=parseFloat(document.getElementById('kc-p-'+cid).textContent);"
            "var o=parseFloat(document.getElementById('kc-i-'+cid).value);"
            "var el=document.getElementById('kc-e-'+cid);"
            "if(!o||o<=1){el.textContent='';return;}"
            "var impl=1/o*100;"
            "var edge=((p-impl)/impl*100).toFixed(1);"
            "var col=edge>0?'#0F6E56':'#DC2626';"
            "el.innerHTML='<b style=\"color:'+col+'\">'+(edge>0?'+':'')+edge+'% edge</b> (b365 impl '+impl.toFixed(1)+'%)';}"

            "function renderHeaderGrid(d){"
            "var el;"
            "el=document.getElementById('stat-date');if(el)el.textContent=d.date||'';"
            "el=document.getElementById('stat-games');if(el)el.textContent=d.total_games||0;"
            "el=document.getElementById('stat-value');if(el)el.textContent=d.total_value_bets||0;"
            "el=document.getElementById('stat-gentime');"
            "if(el&&d.generated_at){"
            "try{"
            "var dt=new Date(d.generated_at);"
            "el.textContent='Genere le '+dt.toLocaleString('fr-CA',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'America/Toronto'})+' ET';"
            "}catch(e){}}"
            # Stale signal warning
            "var stale=document.getElementById('stale-banner');"
            "if(!stale){stale=document.createElement('div');stale.id='stale-banner';"
            "stale.style.cssText='background:#FEF3C7;border-left:4px solid #F59E0B;color:#92400E;"
            "padding:10px 16px;font-size:13px;font-weight:500;margin-bottom:1rem;border-radius:8px;display:none;';"
            "var wrap=document.querySelector('.wrap');if(wrap)wrap.insertBefore(stale,wrap.firstChild);}"
            "try{"
            "var sigDate=d.date||'';"
            "var todayET=new Date().toLocaleDateString('fr-CA',{timeZone:'America/Toronto'});"
            "if(sigDate&&sigDate!==todayET){"
            "stale.textContent='\u26a0\ufe0f Signal du '+sigDate+' — les matchs d\\'aujourd\\'hui ne sont pas encore disponibles. Prochain refresh automatique dans l\\'heure.';"
            "stale.style.display='block';"
            "}else{stale.style.display='none';}}"
            "catch(e){}"
            "}"

            # ── Signal tab ───────────────────────────────────────────────────
            # ── Tableau MLB Moneyline / -1.5 ────────────────────────────────
            # Rendu sur l'onglet Signal: c'est la page d'atterrissage, et les
            # paris de match sont la sortie la plus actionnable du signal.
            # Retourne '' s'il n'y a rien à montrer.
            "function mlTableHTML(d){"
            "var now=Date.now();"
            "var mlg=(d.mlb_ml_analysis||[]).filter(function(g){"
            "if(!g.commence)return true;"
            "try{return new Date(g.commence).getTime()>now;}catch(e){return true;}});"
            "var rows=[];"
            "mlg.forEach(function(g){(g.bets||[]).forEach(function(b){"
            "if(b.tier==='\\ud83d\\udd34')return;"          # exclure les 🔴
            "rows.push(b);});});"
            "if(!rows.length)return '';"
            "var rank={'\\ud83d\\udd25':0,'\\ud83d\\udc8e':1,'\\ud83d\\udfe2':2,'\\ud83d\\udfe1':3};"
            "rows.sort(function(a,b){var ra=rank[a.tier],rb=rank[b.tier];"
            "if(ra===undefined)ra=9;if(rb===undefined)rb=9;"
            "if(ra!==rb)return ra-rb;"
            "return (b.valeur_pct||-999)-(a.valeur_pct||-999);});"
            "var h='<div class=\"sec\">MLB Moneyline / -1.5 — probabilité × cote</div>';"
            "h+='<div class=\"ml-tbl\">';"
            "h+='<div class=\"ml-tr ml-th\"><span>Équipe</span><span>Marché</span>"
            "<span>Prob</span><span>Cote</span><span>Value</span><span>Bet</span></div>';"
            "rows.forEach(function(b){"
            "var v=(b.valeur_pct==null?null:b.valeur_pct);"
            "var vc=v==null?'var(--m)':(v>=8?'#0F6E56':v>=3?'#2563EB':v>=0?'#BA7517':'#DC2626');"
            "var mk=b.marche==='moneyline'?'ML':'-1.5';"
            "h+='<div class=\"ml-tr\">';"
            "h+='<span class=\"ml-team\">'+(b.equipe||'')+'</span>';"
            "h+='<span>'+mk+'</span>';"
            "h+='<span>'+(b.probabilite||0).toFixed(1)+'%</span>';"
            "h+='<span>'+(b.cote||0).toFixed(2)+'</span>';"
            "h+='<span style=\"color:'+vc+';font-weight:700\">'+(v==null?'n/d':(v>0?'+':'')+v.toFixed(1)+'%')+'</span>';"
            "h+='<span>'+(b.tier||'')+' '+(b.label||'')+'</span>';"
            "h+='</div>';"
            "h+='<div class=\"ml-why\">'+(b.raison||'')"
            "+(b.facteurs_nets!=null?' · facteurs alignés: '+(b.facteurs_nets>0?'+':'')+b.facteurs_nets:'')"
            "+'</div>';"
            "});"
            "h+='</div>';"
            "h+='<div class=\"ml-note\">Value = probabilité × cote - 1. "
            "Probabilité = mélange modèle/marché (modèle sans historique de "
            "calibration — volontairement rétréci vers le marché). "
            "Les matchs déjà commencés sont masqués.</div>';"
            "return h;}"
            "function renderSignalTab(d){"
            "var now=Date.now();"
            # build map: "Away @ Home" -> commence_time
            "var ctMap={};"
            "(d.signals||[]).forEach(function(s){"
            "var key=s.game.away_team+' @ '+s.game.home_team;"
            "ctMap[key]=s.game.commence_time;});"
            "var sigs=(d.signals||[]).filter(function(s){"
            "try{return new Date(s.game.commence_time).getTime()>now;}catch(e){return true;}});"
            "var vb=(d.value_bets||[]).filter(function(b){"
            "var ct=ctMap[b.game||''];"
            "if(!ct)return true;"
            "try{return new Date(ct).getTime()>now;}catch(e){return true;}});"
            "var h='';"
            # Les paris de match MLB en premier: c'est ce qu'on vient chercher.
            "h+=mlTableHTML(d);"
            "h+='<div class=\"sec\">Bets recommandes - Edge minimum 5%</div>';"
            "if(!vb.length){h+='<p class=\"no-bets\">Aucun bet avec edge superieur a 5% aujourd\\'hui.</p>';}"
            "else{vb.forEach(function(b){"
            "var ep=b.edge_pct||0;"
            "var ec=ep>=8?'var(--g)':ep>=5?'var(--a)':'var(--r2)';"
            "var eb=ep>=8?'var(--g2)':ep>=5?'var(--a2)':'var(--r2b)';"
            "var et=ep>=8?'var(--g3)':ep>=5?'var(--a3)':'var(--r2d)';"
            "var bw=Math.min(Math.round(ep/20*100),100);"
            "var bc=ep>=8?'#10B981':ep>=5?'#F59E0B':'#EF4444';"
            "var note=b.note||'';"
            "h+='<div class=\"bc\">';"
            "h+='<div class=\"bh\"><div>';"
            "h+='<div class=\"bt\">'+(b.type||'')+'</div>';"
            "h+='<div class=\"bn\">'+(b.bet||'')+'</div>';"
            "h+='<div class=\"bg\">'+(b.game||'')+'</div>';"
            "if(note)h+='<div class=\"bg\" style=\"margin-top:4px;font-size:11px\">'+note+'</div>';"
            "h+='</div><span class=\"vd\" style=\"background:'+eb+';color:'+et+'\">'+(b.verdict||'')+'</span></div>';"
            "h+='<div class=\"bs\">';"
            "h+='<div class=\"stat\"><span class=\"sl\">Cote b365</span><span class=\"sv\">'+(Math.round((b.b365_odds||0)*100)/100)+'</span></div>';"
            "h+='<div class=\"stat\"><span class=\"sl\">Prob b365</span><span class=\"sv\">'+(Math.round((b.b365_implied||0)*10)/10)+'%</span></div>';"
            "h+='<div class=\"stat\"><span class=\"sl\">Prob modele</span><span class=\"sv\">'+(Math.round((b.our_prob||0)*10)/10)+'%</span></div>';"
            "h+='<div class=\"stat\" style=\"color:'+ec+'\"><span class=\"sl\">Edge</span><span class=\"sv\">+'+(Math.round(ep*10)/10)+'%</span></div>';"
            "h+='<div class=\"stat\"><span class=\"sl\">1/4 Kelly</span><span class=\"sv\">'+(Math.round((b.kelly_fraction||0)*10)/10)+'% BR</span></div>';"
            "h+='</div>';"
            "h+='<div class=\"edge-bar-wrap\">';"
            "h+='<div class=\"edge-bar-label\"><span>Force du signal</span>';"
            "h+='<span style=\"color:'+ec+';font-weight:700\">+'+(Math.round(ep*10)/10)+'% edge</span></div>';"
            "h+='<div class=\"edge-bar\"><div class=\"edge-bar-fill\" style=\"width:'+bw+'%;background:'+bc+'\"></div></div>';"
            "h+='</div></div>';});}"
            "h+='<div class=\"sec\" style=\"margin-top:1.5rem\">Tous les matchs</div>';"
            "h+='<div class=\"tbl-wrap\"><table>';"
            "h+='<thead><tr><th>Heure</th><th>Match</th><th>ML Vis/Dom</th><th>PL +/-1.5</th><th>Total O/U</th><th>Edges</th></tr></thead><tbody>';"
            "if(!sigs.length){h+='<tr><td colspan=\"6\" style=\"color:var(--m);text-align:center\">Aucun match</td></tr>';}"
            "else{sigs.forEach(function(s){"
            "var g=s.game;"
            "var ml=(g.markets||{}).moneyline||{};"
            "var tt=(g.markets||{}).totals||{};"
            "var pl=(g.markets||{}).puck_line||{};"
            "function fmt(v){return(v!==undefined&&v!==null&&v!=='--')?(typeof v==='number'?Math.round(v*100)/100:v):'--';}"
            "var ao=fmt((ml.away||{}).odds_decimal);"
            "var ho=fmt((ml.home||{}).odds_decimal);"
            "var ol=(tt.over||{}).line||'--';"
            "var oo=fmt((tt.over||{}).odds_decimal);"
            "var uo=fmt((tt.under||{}).odds_decimal);"
            "var pla=fmt((pl.away||{}).odds_decimal);"
            "var plh=fmt((pl.home||{}).odds_decimal);"
            "var ne=(s.edges||[]).length;"
            "var badge=ne?'<span class=\"eb\">'+ne+(ne>1?' edges':' edge')+'</span>':'';"
            "var t='--';"
            "try{var dd=new Date(g.commence_time);"
            "t=dd.toLocaleTimeString('fr-CA',{hour:'2-digit',minute:'2-digit',timeZone:'America/Toronto'})+' ET';"
            "}catch(e){}"
            "h+='<tr><td class=\"tm\">'+t+'</td>';"
            "h+='<td><strong>'+(g.away_team||'')+'</strong><br><small>@ '+(g.home_team||'')+'</small></td>';"
            "h+='<td class=\"num\">'+ao+'<br><small>'+ho+'</small></td>';"
            "h+='<td class=\"num\">'+pla+'<br><small>'+plh+'</small></td>';"
            "h+='<td class=\"num\">'+ol+'<br><small>O:'+oo+' U:'+uo+'</small></td>';"
            "h+='<td>'+badge+'</td></tr>';});}"
            "h+='</tbody></table></div>';"
            "document.getElementById('tab-signal').innerHTML=h;}"

            # ── NBA tab ──────────────────────────────────────────────────────
            "function renderNBATab(d){"
            "var now=Date.now();"
            "var nba=(d.nba_analysis||[]).filter(function(g){"
            "if(!g.commence_time)return true;"
            "try{return new Date(g.commence_time).getTime()>now;}catch(e){return true;}});"
            "var h='';"
            "if(!nba.length){h='<div style=\"color:var(--m);padding:1rem 0;font-size:13px\">Aucune analyse NBA disponible ou pas de matchs ce soir.</div>';}"
            "else{"
            "h='<div class=\"nba-header\">NBA Player Props \u2014 Analyse +EV</div>';"
            "nba.forEach(function(gd){"
            "var bets=gd.bets||[];if(!bets.length)return;"
            "h+='<div class=\"nba-game\">';"
            "h+='<div class=\"nba-matchup\">'+(gd.away_team||'')+' <span class=\"nba-at\">@</span> '+(gd.home_team||'')+'</div>';"
            "bets.forEach(function(b){"
            "var ep=b.edge_pct||0;"
            "var ec=ep>=15?'#0F6E56':'#BA7517';"
            "var eb=ep>=15?'#E1F5EE':'#FAEEDA';"
            "var dr=b.def_rank||15;"
            "var drc=dr>=25?'#B45309':dr<=5?'#0F6E56':'#6B7280';"
            "var tshort=(b.team||'').split(' ').pop();"
            "var oshort=(b.opponent||'').split(' ').pop();"
            "h+='<div class=\"nba-card\">';"
            "h+='<div class=\"nba-card-head\"><div>';"
            "h+='<span class=\"nba-player\">'+(b.player||'')+'</span>';"
            "h+='<span class=\"nba-meta\">'+tshort+' vs '+oshort+'</span>';"
            "h+='</div><div class=\"nba-edge\" style=\"color:'+ec+';background:'+eb+'\">+'+ep+'% edge</div></div>';"
            "h+='<div class=\"nba-bet-label\">'+(b.market||'')+'</div>';"
            "h+='<div class=\"nba-stats\">';"
            "h+='<div class=\"nba-stat\"><span>Moy last 10</span><strong>'+(b.avg10||0)+'</strong></div>';"
            "h+='<div class=\"nba-stat\"><span>Moy last 5</span><strong>'+(b.avg5||0)+'</strong></div>';"
            "h+='<div class=\"nba-stat\"><span>Proj. adj DEF</span><strong>'+(b.adj_proj||0)+'</strong></div>';"
            "h+='<div class=\"nba-stat\"><span>DEF adverse</span><strong style=\"color:'+drc+'\">#'+dr+' ligue</strong></div>';"
            "h+='<div class=\"nba-stat\"><span>Notre prob</span><strong style=\"color:'+ec+'\">'+( b.our_prob||0)+'%</strong></div>';"
            "h+='<div class=\"nba-stat\"><span>Cote est. b365</span><strong>'+(b.est_odds||0)+'</strong></div>';"
            "h+='<div class=\"nba-stat\"><span>b365 implied</span><strong>52.4%</strong></div>';"
            "h+='<div class=\"nba-stat\"><span>1/4 Kelly</span><strong>'+(b.kelly||0)+'% BR</strong></div>';"
            "h+='</div>';"
            "(b.context||[]).slice(0,2).forEach(function(n){h+='<div class=\"nba-note\">'+n+'</div>';});"
            "h+='</div>';});"
            "h+='</div>';});}"
            "document.getElementById('tab-nba').innerHTML=h;}"

            # ── MLB tab ──────────────────────────────────────────────────────
            "function renderMLBTab(d){"
            "var now=Date.now();"
            "var mlb=(d.mlb_analysis||[]).filter(function(g){"
            "if(!g.commence_time)return true;"
            "try{return new Date(g.commence_time).getTime()>now;}catch(e){return true;}});"
            "var h='';"
            # Le tableau Moneyline / -1.5 vit sur l'onglet Signal (page
            # d'atterrissage), pas ici \u2014 pas de duplication.
            "if(!mlb.length){h+='<div style=\"color:var(--m);padding:1rem 0;font-size:13px\">Aucune analyse de props MLB disponible.</div>';}"
            "else{"
            "h+='<div class=\"mlb-header\">MLB Player Props \u2014 Analyse +EV</div>';"
            "mlb.forEach(function(gd){"
            "var bets=gd.bets||[];if(!bets.length)return;"
            "h+='<div class=\"mlb-game\">';"
            "h+='<div class=\"mlb-matchup\">'+(gd.away_team||'')+' <span class=\"mlb-at\">@</span> '+(gd.home_team||'')+'</div>';"
            "bets.forEach(function(b){"
            "var ep=b.edge_pct||0;"
            "var ec=ep>=15?'#0F6E56':'#BA7517';"
            "var eb=ep>=15?'#E1F5EE':'#FAEEDA';"
            "var pt=b.player_type||'batter';"
            "var icon=pt==='pitcher'?'\u26be':'&#127951;';"
            "var lbl=pt==='pitcher'?'Lanceur':'Frappeur';"
            "var tshort=(b.team||'').split(' ').pop();"
            "var oshort=(b.opponent||'').split(' ').pop();"
            "var pf=b.park_factor||1.0;"
            "var pfc=pf>=1.08?'#B45309':pf<=0.92?'#0F6E56':'#6B7280';"
            "h+='<div class=\"mlb-card\">';"
            "h+='<div class=\"mlb-card-head\"><div>';"
            "h+='<span class=\"mlb-player\">'+icon+' '+(b.player||'')+'</span>';"
            "h+='<span class=\"mlb-meta\">'+lbl+' \u00b7 '+tshort+' vs '+oshort+'</span>';"
            "var isPit=b.player_type==='pitcher';"
            "var badgeCol=isPit?'#2563EB':ec;var badgeBg=isPit?'#EFF6FF':eb;"
            "var badgeTxt=isPit?('proj '+(b.adj_proj||0)+'K'):('+'+ep+'% edge');"
            "h+='</div><div class=\"mlb-edge\" style=\"color:'+badgeCol+';background:'+badgeBg+'\">'+badgeTxt+'</div></div>';"
            "h+='<div class=\"mlb-bet-label\">'+(b.market||'')+'</div>';"
            "h+='<div class=\"mlb-stats\">';"
            "h+='<div class=\"mlb-stat\"><span>Moy saison</span><strong>'+(b.season_avg||0)+'K</strong></div>';"
            "var mreg=b.adj_mult,mraw=b.adj_mult_raw,praw=b.adj_proj_raw;"
            "h+='<div class=\"mlb-stat\"><span>Proj. '+(praw!=null?'régressée':'ajustée')+'</span><strong>'+(b.adj_proj||0)+'K</strong>';"
            "if(mreg)h+='<span style=\"text-transform:none;font-weight:500\">x'+mreg.toFixed(3)+'</span>';"
            "h+='</div>';"
            "if(praw!=null&&isPit){var dlt=(praw-(b.adj_proj||0));"
            "h+='<div class=\"mlb-stat\"><span>Proj. brute (ancienne)</span><strong style=\"color:var(--m)\">'+praw+'K</strong>';"
            "if(mraw)h+='<span style=\"text-transform:none;font-weight:500\">x'+mraw.toFixed(3)+' · écart '+(dlt>=0?'+':'')+dlt.toFixed(2)+'K</span>';"
            "h+='</div>';}"
            "if(b.opp_k_rate!=null&&isPit){h+='<div class=\"mlb-stat\"><span>K% adverse'+(b.opp_k_source?' — '+b.opp_k_source:'')+'</span><strong>'+(b.opp_k_rate||0)+'%</strong>';"
            "if(b.league_k_rate)h+='<span style=\"text-transform:none;font-weight:500\">ligue '+b.league_k_rate+'%</span>';"
            "h+='</div>';}"
            "h+='<div class=\"mlb-stat\"><span>Park factor</span><strong style=\"color:'+pfc+'\">'+(b.park_factor||1.0)+'</strong></div>';"
            "if(!isPit){h+='<div class=\"mlb-stat\"><span>Notre prob</span><strong style=\"color:'+ec+'\">'+(b.our_prob||0)+'%</strong></div>';}"
            "if(!isPit){h+='<div class=\"mlb-stat\"><span>1/4 Kelly</span><strong>'+(b.kelly||0)+'% BR</strong></div>';}"
            "if(isPit){var mo=b.min_odds||0;"
            "if(mo){h+='<div class=\"mlb-stat\"><span>Cote MIN à exiger</span><strong style=\"color:#DC2626\">'+mo.toFixed(2)+'</strong></div>';}"
            "h+='<div class=\"mlb-stat\" style=\"color:var(--m);font-size:11px\">Sous cette cote = ne pas miser</div>';}"
            "h+='</div>';"
            "var kc=b.k_curve||[];if(kc.length&&b.player_type==='pitcher'){"
            "var cid=b.player.replace(/ /g,'_');"
            "h+='<div class=\"mlb-k-curve\"><span class=\"mlb-k-curve-title\">Prob K — cliquer un niveau puis entrer la cote bet365</span>';"
            "kc.forEach(function(c){"
            "var k=c.k_exact||0;if(k<3||k>10)return;"
            "var isBest=Math.abs((c.line||0)-(b.line||0))<0.1;"
            "var bg=isBest?'rgba(15,110,86,0.12)':'transparent';"
            "var bdr=isBest?'2px solid #0F6E56':'1px solid #E5E7EB';"
            "var prob=c.prob||0;"
            "h+='<div class=\"mlb-k-cell\" style=\"border:'+bdr+';background:'+bg+';cursor:pointer\""
            " onclick=\"mlbCalcSel(\\''+cid+'\\','+k+','+prob+')\">';"
            "h+='<div class=\"mlb-k-num\">K≥'+k+'</div>';"
            "h+='<div class=\"mlb-k-prob\">'+prob+'%</div>';"
            "h+='</div>';});"
            "h+='</div>';"
            "h+='<div class=\"mlb-k-calc\" id=\"kc-'+cid+'\" style=\"display:none\">';"
            "h+='K≥<b id=\"kc-k-'+cid+'\"></b> · Notre prob: <b id=\"kc-p-'+cid+'\"></b>% · ';"
            "h+='Cote bet365: <input id=\"kc-i-'+cid+'\" class=\"mlb-k-odds-input\" type=\"number\" step=\"0.01\" min=\"1.01\" placeholder=\"ex: 1.95\" oninput=\"mlbCalcEdge(\\''+cid+'\\')\">';"
            "h+=' <b id=\"kc-e-'+cid+'\"></b></div>';}"
            "(b.context||[]).slice(0,4).forEach(function(n){h+='<div class=\"mlb-note\">'+n+'</div>';});"
            "h+='</div>';});"
            "h+='</div>';});}"
            "var pw=d.power_analysis||[];"
            "if(pw.length){"
            "h+='<div class=\"mlb-header\" style=\"margin-top:1.5rem\">🔥 Frappeurs — Candidats 4+ Bases</div>';"
            "pw.forEach(function(gd){"
            "var bats=gd.power_batters||[];if(!bats.length)return;"
            "h+='<div class=\"mlb-game\">';"
            "h+='<div class=\"mlb-matchup\">'+(gd.away_team||'')+' <span class=\"mlb-at\">@</span> '+(gd.home_team||'')+'</div>';"
            "bats.slice(0,6).forEach(function(b){"
            "var cid=b.player.replace(/ /g,'_');"
            "var hot=b.hot_streak||0;"
            "var hotStr=hot>0.3?'↑ En feu':hot<-0.3?'↓ En baisse':'→ Stable';"
            "var hotCol=hot>0.3?'#0F6E56':hot<-0.3?'#DC2626':'#6B7280';"
            "h+='<div class=\"mlb-card\">';"
            "h+='<div class=\"mlb-card-head\"><div>';"
            "h+='<span class=\"mlb-player\">🏏 '+b.player+'</span>';"
            "h+='<span class=\"mlb-meta\">'+(b.team||'').split(' ').pop()+'</span>';"
            "h+='</div><div class=\"mlb-edge\" style=\"color:#7C3AED;background:#F5F3FF\">P(4+TB) '+(b.p4||0)+'%</div></div>';"
            "h+='<div class=\"mlb-stats\">';"
            "h+='<div class=\"mlb-stat\"><span>Moy TB blend</span><strong>'+(b.mean_tb||0)+'</strong></div>';"
            "h+='<div class=\"mlb-stat\"><span>Rolling '+(b.games||0)+'j</span><strong>'+(b.rolling_avg||0)+'</strong></div>';"
            "h+='<div class=\"mlb-stat\"><span>Saison</span><strong>'+(b.season_avg||0)+'</strong></div>';"
            "h+='<div class=\"mlb-stat\"><span>HR/match</span><strong>'+(b.hr_rate||0)+'</strong></div>';"
            "h+='<div class=\"mlb-stat\"><span>Tendance</span><strong style=\"color:'+hotCol+'\">'+hotStr+'</strong></div>';"
            "h+='</div>';"
            "if(b.opponent||(b.context&&b.context.length)){"
            "h+='<div style=\"margin:6px 0;padding:8px 10px;background:#F5F3FF;border-radius:8px;font-size:12px;color:#4C1D95\">';"
            "if(b.opponent)h+='<b>vs '+b.opponent+'</b><br>';"
            "(b.context||[]).forEach(function(x){h+='<span style=\"display:inline-block;margin:2px 4px 0 0;padding:2px 6px;background:#EDE9FE;border-radius:4px\">'+x+'</span>';});"
            "h+='</div>';}"
            "h+='<div class=\"mlb-k-curve\"><span class=\"mlb-k-curve-title\">P(TB ≥ N) — cliquer, entrer cote bet365</span>';"
            "(b.curve||[]).forEach(function(c){"
            "h+='<div class=\"mlb-k-cell\" style=\"border:1px solid var(--b);cursor:pointer\" onclick=\"mlbCalcSel(\\''+cid+'\\','+c.n+','+c.prob+')\">';"
            "h+='<div class=\"mlb-k-num\">TB≥'+c.n+'</div>';"
            "h+='<div class=\"mlb-k-prob\">'+c.prob+'%</div>';"
            "h+='</div>';});"
            "h+='</div>';"
            "h+='<div class=\"mlb-k-calc\" id=\"kc-'+cid+'\" style=\"display:none\">';"
            "h+='TB≥<b id=\"kc-k-'+cid+'\"></b> · Notre prob: <b id=\"kc-p-'+cid+'\"></b>% · ';"
            "h+='Cote bet365: <input id=\"kc-i-'+cid+'\" class=\"mlb-k-odds-input\" type=\"number\" step=\"0.01\" min=\"1.01\" placeholder=\"ex: 5.00\" oninput=\"mlbCalcEdge(\\''+cid+'\\')\">';"
            "h+=' <b id=\"kc-e-'+cid+'\"></b></div>';"
            "h+='</div>';});"
            "h+='</div>';});}"
            "document.getElementById('tab-mlb').innerHTML=h;}"

            # ── Props tab ────────────────────────────────────────────────────
            "function _rc(r){return r<=4?'#0F6E56':r<=10?'#2563EB':r<=22?'#6B7280':'#B45309';}"
            "function _rl(r){return r<=4?'Elite':r<=10?'Bonne':r<=22?'Moyenne':'Faible';}"
            "function _pec(e){return e>=15?'#0F6E56':e>=8?'#BA7517':'#9CA3AF';}"

            "function renderPropsTab(d){"
            "var props=d.props_analysis||[];var h='';"
            "if(!props.length){h='<div style=\"color:var(--m);padding:1rem 0;font-size:13px\">Aucune analyse joueurs disponible.</div>';}"
            "else{props.forEach(function(an){"
            "var home=an.home_team||'';var away=an.away_team||'';"
            "var hg=an.home_goalie||{};var ag=an.away_goalie||{};"
            "var bets=an.bets||[];var retour=an.retour_de_flamme||[];"
            "var hshots=an.home_def_shots||31.0;var ashots=an.away_def_shots||31.0;"
            "var hga=an.home_def_ga||3.10;var aga=an.away_def_ga||3.10;"
            "var hsr=an.home_shots_rank||16;var asr=an.away_shots_rank||16;"
            "var hgr=an.home_ga_rank||16;var agr=an.away_ga_rank||16;"
            "h+='<div class=\"pg\">';"
            "h+='<div class=\"ph\">';"
            "h+='<div class=\"pm\"><span class=\"pm-away\">'+away+'</span>';"
            "h+=' <span class=\"pm-at\">@</span> <span class=\"pm-home\">'+home+'</span></div>';"
            "h+='<div class=\"matchup-grid\">';"
            # home def column
            "h+='<div class=\"matchup-col\">';"
            "h+='<div class=\"mc-title\">DEF '+home.slice(0,3).toUpperCase()+'</div>';"
            "h+='<div class=\"mc-stat\"><span style=\"color:'+_rc(hsr)+'\">'+_rl(hsr)+' (#'+hsr+')</span> shots</div>';"
            "h+='<div class=\"mc-stat\"><span style=\"color:'+_rc(hgr)+'\">'+_rl(hgr)+' (#'+hgr+')</span> buts</div>';"
            "h+='<div class=\"mc-val\"><strong>'+hshots+'</strong> shots/m accordes \u00b7 <strong>'+hga+'</strong> GA/m</div>';"
            "h+='</div>';"
            # away def column
            "h+='<div class=\"matchup-col\">';"
            "h+='<div class=\"mc-title\">DEF '+away.slice(0,3).toUpperCase()+'</div>';"
            "h+='<div class=\"mc-stat\"><span style=\"color:'+_rc(asr)+'\">'+_rl(asr)+' (#'+asr+')</span> shots</div>';"
            "h+='<div class=\"mc-stat\"><span style=\"color:'+_rc(agr)+'\">'+_rl(agr)+' (#'+agr+')</span> buts</div>';"
            "h+='<div class=\"mc-val\"><strong>'+ashots+'</strong> shots/m accordes \u00b7 <strong>'+aga+'</strong> GA/m</div>';"
            "h+='</div>';"
            # goalies column
            "h+='<div class=\"matchup-col\"><div class=\"mc-title\">Gardiens</div>';"
            "[[hg,'DOM'],[ag,'VIS']].forEach(function(pair){"
            "var gg=pair[0];var side=pair[1];"
            "if(gg.name){"
            "var sv=gg.sv_pct||0;"
            "var svc=sv>=0.915?'#0F6E56':sv<0.900?'#B45309':'#6B7280';"
            "h+='<div class=\"mc-goalie\"><span class=\"mc-side\">'+side+'</span> <strong>'+gg.name+'</strong>';"
            "h+=' <span style=\"color:'+svc+'\">SV% '+sv+'</span> \u00b7 GAA '+(gg.gaa||'--')+'</div>';"
            "}});"
            "h+='</div>';"
            "h+='</div></div>';"
            # bets
            "if(!bets.length){h+='<div class=\"no-bets\" style=\"margin:0 0 1rem\">Aucun bet +EV identifie (edge < 8%)</div>';}"
            "else{"
            "h+='<div class=\"player-bets\">';"
            "bets.forEach(function(b){"
            "var edge=b.edge_pct||0;var prob=b.our_prob||0;"
            "var kelly=b.kelly||0;var market=b.market||'';"
            "var mdetail=b.market_detail||'';var name=b.name||'';"
            "var pos=b.position||'';var team=b.team||'';"
            "var opp=b.opponent||'';var toi=b.toi||'--';"
            "var notes=b.context_notes||[];var all_mkts=b.all_markets||[];"
            "var dk_impl=b.dk_implied||52.4;"
            "var ec2=edge>=15?'#0F6E56':'#BA7517';"
            "var eb2=edge>=15?'#E1F5EE':'#FAEEDA';"
            "var s_pg=b.shots_pg||0;var s_adj=b.shots_adj||0;var s_line=b.shots_line||0;"
            "var s_prob=b.shots_prob||0;var s_edge=b.shots_edge||0;"
            "var l5s=b.last5_shots||0;var l10s=b.last10_shots||0;"
            "var avg5s=Math.round(l5s/5*10)/10;var avg10s=l10s?Math.round(l10s/10*10)/10:s_pg;"
            "var g_pg=b.goals_pg||0;var g_adj=b.goals_adj||0;"
            "var g_prob=b.goals_prob||0;var g_edge=b.goals_edge||0;"
            "var l5g=b.last5_goals||0;var sg=b.season_goals||0;"
            "var p_pg=b.points_pg||0;var p_adj=b.points_adj||0;"
            "var p_prob=b.points_prob||0;var p_edge=b.points_edge||0;"
            "var l5p=b.last5_points||0;var sp=b.season_points||0;"
            "var opp_sr=b.opp_shots_rank||16;var opp_gr=b.opp_ga_rank||16;"
            "var est_odds=b.est_odds||'n/d';"
            "h+='<div class=\"pb\">';"
            "h+='<div class=\"pb-head\">';"
            "h+='<div class=\"pb-info\">';"
            "h+='<span class=\"pb-name\">'+name+'</span>';"
            "h+='<span class=\"pb-pos\">'+pos+'</span>';"
            "h+='<span class=\"pb-team\">'+team.slice(0,3).toUpperCase()+' vs '+opp.slice(0,3).toUpperCase()+' \u00b7 '+toi+' TOI</span>';"
            "h+='</div><div class=\"pb-season\">'+sg+' buts \u00b7 '+sp+' pts cette saison</div></div>';"
            "h+='<div class=\"pb-main-bet\" style=\"border-left-color:'+ec2+'\">';"
            "h+='<div class=\"pbm-label\">&#128204; MEILLEUR BET</div>';"
            "h+='<div class=\"pbm-market\" style=\"color:'+ec2+'\">'+market+'</div>';"
            "h+='<div class=\"pbm-detail\">'+mdetail+'</div>';"
            "h+='<div class=\"pbm-odds\">';"
            "h+='<div class=\"pbm-odd\"><span>Cote est. b365</span><strong>'+est_odds+'</strong></div>';"
            "h+='<div class=\"pbm-odd\"><span>Notre prob</span><strong style=\"color:'+ec2+'\">'+prob+'%</strong></div>';"
            "h+='<div class=\"pbm-odd\"><span>b365 implied</span><strong>'+dk_impl+'%</strong></div>';"
            "h+='<div class=\"pbm-odd edge-highlight\" style=\"background:'+eb2+';color:'+ec2+'\"><span>Edge</span><strong>+'+edge+'%</strong></div>';"
            "h+='<div class=\"pbm-odd\"><span>1/4 Kelly</span><strong>'+kelly+'% BR</strong></div>';"
            "h+='</div></div>';"
            "h+='<div class=\"pb-shots\">';"
            "h+='<div class=\"pbs-title\">&#127919; Shots on Goal</div>';"
            "h+='<div class=\"pbs-grid\">';"
            "h+='<div class=\"pbs-col\">';"
            "h+='<div class=\"pbs-stat\"><span>Moy 10m (pond.)</span><strong>'+s_pg+'</strong></div>';"
            "h+='<div class=\"pbs-stat\"><span>Adj DEF adverse</span><strong>'+s_adj+'</strong></div>';"
            "h+='<div class=\"pbs-stat\"><span>Ligne DK estimee</span><strong>'+s_line+'</strong></div>';"
            "h+='</div>';"
            "h+='<div class=\"pbs-col\">';"
            "h+='<div class=\"pbs-stat\"><span>Last 5 ('+avg5s+'/m)</span><strong>'+l5s+' shots</strong></div>';"
            "h+='<div class=\"pbs-stat\"><span>Last 10 ('+avg10s+'/m)</span><strong>'+l10s+' shots</strong></div>';"
            "h+='<div class=\"pbs-stat\"><span>Prob Over '+(s_line||'?')+'</span>';"
            "h+='<strong style=\"color:'+_pec(s_edge)+'\">'+s_prob+'% (edge +'+s_edge+'%)</strong></div>';"
            "h+='</div>';"
            "h+='<div class=\"pbs-col\">';"
            "var osr_c=opp_sr>=25?'#B45309':opp_sr<=8?'#0F6E56':'#6B7280';"
            "var ogr_c=opp_gr>=25?'#B45309':opp_gr<=8?'#0F6E56':'#6B7280';"
            "h+='<div class=\"pbs-stat\"><span>DEF adverse shots</span><strong style=\"color:'+osr_c+'\">#'+opp_sr+' ligue</strong></div>';"
            "h+='<div class=\"pbs-stat\"><span>DEF adverse buts</span><strong style=\"color:'+ogr_c+'\">#'+opp_gr+' ligue</strong></div>';"
            "h+='<div class=\"pbs-stat\"><span>Buts saison</span><strong>'+sg+' buts</strong></div>';"
            "h+='</div></div>';"
            "h+='<div class=\"pbs-others\">';"
            "h+='<span>Buts: moy '+g_pg+'/m \u00b7 adj '+g_adj+' \u00b7 last5: '+l5g+' \u00b7 prob '+g_prob+'% (edge +'+g_edge+'%)</span>';"
            "h+=' &nbsp;|&nbsp; ';"
            "h+='<span>Pts: moy '+p_pg+'/m \u00b7 adj '+p_adj+' \u00b7 last5: '+l5p+' \u00b7 prob '+p_prob+'% (edge +'+p_edge+'%)</span>';"
            "h+='</div></div>';"
            "if(notes.length){h+='<div class=\"pb-context\">';notes.forEach(function(n){h+='<div class=\"pb-note\">'+n+'</div>';});h+='</div>';}"
            "var other_mkts=all_mkts.filter(function(m){return m.label!==market;});"
            "if(other_mkts.length){"
            "h+='<div class=\"pb-others-bets\">Autres bets +EV: ';"
            "other_mkts.forEach(function(m){"
            "var mc2=m.edge>=15?'#0F6E56':'#BA7517';"
            "h+='<span class=\"pb-other-bet\" style=\"color:'+mc2+'\">'+m.label+' (+'+m.edge+'% edge \u00b7 '+m.prob+'% prob)</span> ';"
            "});h+='</div>';}"
            "h+='</div>';});"
            "h+='</div>';}"
            # retour de flamme
            "if(retour.length){"
            "h+='<div class=\"retour-section\">';"
            "h+='<div class=\"retour-title\">&#129482; Retour de flamme \u2014 Regression vers la moyenne</div>';"
            "h+='<div class=\"retour-subtitle\">Joueurs en dessous de leur moyenne last 5 \u00b7 DK va probablement baisser la ligne \u00b7 Edge sur le Over base sur la vraie moyenne</div>';"
            "retour.forEach(function(r){"
            "var rdrop=r.drop_pct||0;var redge=r.edge_pct||0;"
            "var drop_c=rdrop>=40?'#A32D2D':'#B45309';"
            "var edge_c=redge>=15?'#0F6E56':'#BA7517';"
            "h+='<div class=\"retour-card\">';"
            "h+='<div class=\"retour-head\"><div>';"
            "h+='<span class=\"retour-name\">'+(r.name||'')+'</span>';"
            "h+='<span class=\"retour-meta\">'+(r.position||'')+' \u00b7 '+(r.team||'').slice(0,3).toUpperCase()+' vs '+(r.opponent||'').slice(0,3).toUpperCase()+' \u00b7 '+(r.toi||'--')+' TOI</span>';"
            "h+='</div><div class=\"retour-drop\" style=\"color:'+drop_c+'\">-'+rdrop+'% depuis last 5</div></div>';"
            "h+='<div class=\"retour-stats\">';"
            "h+='<div class=\"retour-stat\"><span>Moy last 10</span><strong>'+(r.avg10_shots||0)+' shots/m</strong></div>';"
            "h+='<div class=\"retour-stat\"><span>Moy last 5</span><strong style=\"color:'+drop_c+'\">'+(r.avg5_shots||0)+' shots/m</strong></div>';"
            "h+='<div class=\"retour-stat\"><span>Ligne DK estimee</span><strong>'+(r.dk_line_est||0)+' shots</strong></div>';"
            "h+='<div class=\"retour-stat\"><span>Shots proj. (moy reelle)</span><strong>'+(r.shots_adj||0)+'</strong></div>';"
            "h+='<div class=\"retour-stat\"><span>DEF adverse</span><strong style=\"color:'+_rc(r.opp_shots_rank||16)+'\">#'+(r.opp_shots_rank||16)+' ligue</strong></div>';"
            "h+='<div class=\"retour-stat edge-cell\" style=\"color:'+edge_c+'\"><span>Edge</span><strong>+'+redge+'%</strong></div>';"
            "h+='<div class=\"retour-stat\"><span>Cote est. b365</span><strong>'+(r.est_odds||0)+'</strong></div>';"
            "h+='<div class=\"retour-stat\"><span>Notre prob</span><strong>'+(r.our_prob||0)+'%</strong></div>';"
            "h+='<div class=\"retour-stat\"><span>1/4 Kelly</span><strong>'+(r.kelly||0)+'% BR</strong></div>';"
            "h+='</div>';"
            "h+='&#128204; Bet: Shots Over '+(r.dk_line_est||0)+' \u00b7 Logique: moy reelle '+(r.avg10_shots||0)+'/m \u2192 DK va coter bas sur la forme recente';"
            "h+='</div>';});"
            "h+='</div>';}"
            "h+='</div>';});}"
            "document.getElementById('tab-props').innerHTML=h;}"
        )

    def _script(self):
        return (
            "<script>"
            + self._js_render() +
            "function showTab(id,btn){"
            "document.querySelectorAll('[id^=\"tab-\"]').forEach(function(el){el.style.display='none';});"
            "document.getElementById(id).style.display='block';"
            "document.querySelectorAll('.tab').forEach(function(b){b.classList.remove('active');});"
            "btn.classList.add('active');"
            "if(id==='tab-perf'){loadPerf();}"
            "}"

            "function loadPerf(){"
            # bets.json = paris REELLEMENT pris (track.py). Absent tant qu'aucun
            # pari n'est logue: on ne fait pas echouer l'onglet pour autant.
            "fetch('bets.json?t='+Date.now())"
            ".then(function(r){return r.ok?r.json():null;})"
            ".catch(function(){return null;})"
            ".then(function(tracked){window._TRACKED=tracked;})"
            ".then(function(){return fetch('results.json?t='+Date.now());})"
            ".then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})"
            ".then(function(data){renderPerf(data);})"
            ".catch(function(){"
            "var t=renderTracked(window._TRACKED);"
            "document.getElementById('perf-content').innerHTML=t||"
            "\"<div class='perf-empty'><div class='perf-empty-icon'>📊</div>"
            "<div class='perf-empty-title'>Aucune donnee de performance</div>"
            "<div class='perf-empty-sub'>Le backtester resout automatiquement les bets chaque matin.</div></div>\";});}"


            "function renderTracked(t){"
            "if(!t||!t.stats||!t.stats.n_bets)return '';"
            "var s=t.stats,y=s.yield||{},r=s.record||{},c=s.clv||{};"
            "var h=\"<div class='trk'>\";"
            "h+=\"<div class='perf-title'>Paris suivis (mises reelles)</div>\";"
            "h+=\"<div class='trk-sub'>\"+s.n_bets+\" pari(s) &middot; \"+s.n_counted"
            "+\" regle(s)\"+(s.n_pending?\" &middot; \"+s.n_pending+\" en attente\":'')"
            "+(s.n_push?\" &middot; \"+s.n_push+\" push (hors calcul)\":'')+\"</div>\";"

            # Tuiles: yield + IC, WR toujours accompagne de la cote moyenne, CLV.
            "if(y.yield_pct===null||y.yield_pct===undefined){"
            "h+=\"<div class='trk-note'>Aucun pari regle: pas de rendement a calculer.</div>\";"
            "}else{"
            "var yc=y.yield_pct>=0?'#1D9E75':'#A32D2D';"
            "h+=\"<div class='perf-grid'>\";"
            "h+=\"<div class='perf-box'><div class='perf-label'>Yield</div>\";"
            "h+=\"<div class='perf-val' style='color:\"+yc+\"'>\"+(y.yield_pct>=0?'+':'')+y.yield_pct.toFixed(1)+\"%</div>\";"
            "h+=\"<div class='trk-mini'>\"+y.profit.toFixed(2)+\"u / \"+y.staked.toFixed(2)+\"u mises</div></div>\";"
            "if(y.ci_low!==null&&y.ci_low!==undefined){"
            "h+=\"<div class='perf-box'><div class='perf-label'>IC 95% du yield</div>\";"
            "h+=\"<div class='perf-val' style='font-size:15px'>\"+(y.ci_low>=0?'+':'')+y.ci_low.toFixed(1)"
            "+\"% a \"+(y.ci_high>=0?'+':'')+y.ci_high.toFixed(1)+\"%</div>\";"
            "h+=\"<div class='trk-mini'>\"+(!y.reliable?\"echantillon trop petit (\"+y.n+\" paris, ~30 requis)\""
            ":(y.excludes_zero?\"exclut 0: signal\":\"contient 0: indistinguable du hasard\"))+\"</div></div>\";}"
            "if(r.win_rate!==null&&r.win_rate!==undefined){"
            "h+=\"<div class='perf-box'><div class='perf-label'>WR &amp; cote moyenne</div>\";"
            "h+=\"<div class='perf-val' style='font-size:15px'>\"+r.win_rate.toFixed(1)+\"% @ \"+r.avg_odds.toFixed(2)+\"</div>\";"
            "var bec=r.wr_vs_breakeven>=0?'#1D9E75':'#A32D2D';"
            "h+=\"<div class='trk-mini'>rentabilite a \"+r.breakeven_wr.toFixed(1)+\"% &middot; \";"
            "h+=\"<span style='color:\"+bec+\"'>\"+(r.wr_vs_breakeven>=0?'+':'')+r.wr_vs_breakeven.toFixed(1)+\" pts</span></div></div>\";}"
            "if(c.n){"
            "var cc=c.avg_clv_pct>=0?'#1D9E75':'#A32D2D';"
            "h+=\"<div class='perf-box'><div class='perf-label'>CLV moyen</div>\";"
            "h+=\"<div class='perf-val' style='color:\"+cc+\"'>\"+(c.avg_clv_pct>=0?'+':'')+c.avg_clv_pct.toFixed(2)+\"%</div>\";"
            "h+=\"<div class='trk-mini'>\"+c.pct_positive.toFixed(0)+\"% pris sous la fermeture &middot; \"+c.n+\" paris</div></div>\";}"
            "h+=\"</div>\";}"
            "if(c.n_missing)h+=\"<div class='trk-note'>\"+c.n_missing+\" pari(s) sans cote de fermeture — <code>python track.py close</code></div>\";"

            # Courbe de calibration: annonce vs observe, avec le n de chaque tranche.
            "var cal=s.calibration||[];"
            "if(cal.length){"
            "h+=\"<div class='perf-section-title'>Calibration — probabilite annoncee contre resultat observe</div>\";"
            "h+=\"<div class='trk-cal'>\";"
            "cal.forEach(function(b){"
            "var gc=Math.abs(b.gap)<=5?'#1D9E75':Math.abs(b.gap)<=10?'#BA7517':'#A32D2D';"
            "var wexp=Math.max(0,Math.min(100,b.expected));"
            "var wobs=Math.max(0,Math.min(100,b.observed));"
            "h+=\"<div class='trk-cal-row\"+(b.thin?' trk-thin':'')+\"'>\";"
            "h+=\"<span class='trk-cal-b'>\"+b.bucket+\"%</span>\";"
            "h+=\"<span class='trk-cal-n'>n=\"+b.n+(b.thin?' ·mince':'')+\"</span>\";"
            "h+=\"<span class='trk-cal-bars'>\";"
            "h+=\"<span class='trk-bar trk-bar-exp' style='width:\"+wexp+\"%'></span>\";"
            "h+=\"<span class='trk-bar trk-bar-obs' style='width:\"+wobs+\"%'></span>\";"
            "h+=\"</span>\";"
            "h+=\"<span class='trk-cal-v'>\"+b.expected.toFixed(0)+\"% → \"+b.observed.toFixed(0)+\"%</span>\";"
            "h+=\"<span class='trk-cal-gap' style='color:\"+gc+\"'>\"+(b.gap>=0?'+':'')+b.gap.toFixed(1)+\"</span>\";"
            "h+=\"</div>\";});"
            "h+=\"</div>\";"
            "h+=\"<div class='trk-legend'><span class='trk-key trk-bar-exp'></span>annonce par le modele\";"
            "h+=\"<span class='trk-key trk-bar-obs'></span>observe\";"
            "h+=\" &middot; une tranche sous 20 paris est marquee <i>mince</i>: son ecart n'est pas interpretable.</div>\";}"

            # ROI par marche: jamais sans WR ni cote moyenne.
            "var mk=s.by_market||[];"
            "if(mk.length){"
            "h+=\"<div class='perf-section-title'>Par marche</div><div class='perf-edge-table'>\";"
            "mk.forEach(function(m){"
            "var pc=m.roi_pct>=0?'#1D9E75':'#A32D2D';"
            "h+=\"<div class='perf-edge-row'>\";"
            "h+=\"<span class='perf-edge-label'>\"+m.market+\"</span>\";"
            "h+=\"<span class='perf-edge-n'>\"+m.n+\" paris</span>\";"
            "h+=\"<span class='perf-edge-wr'>\"+m.win_rate.toFixed(1)+\"% @ \"+m.avg_odds.toFixed(2)+\"</span>\";"
            "h+=\"<span class='perf-edge-profit' style='color:\"+pc+\"'>\"+(m.roi_pct>=0?'+':'')+m.roi_pct.toFixed(1)+\"%\";"
            "h+=(m.reliable?'':\"<span class='trk-flag'>peu fiable</span>\")+\"</span>\";"
            "h+=\"</div>\";});"
            "h+=\"</div>\";}"
            "h+=\"</div>\";"
            "return h;}"
            "function renderPerf(data){"
            "var s=data.summary||{};"
            "var bets=data.bets||[];"
            "var total=s.total||0;"
            "var wr=s.win_rate||0;"
            "var profit=s.profit||0;"
            "var roi=s.roi||0;"
            "var by_edge=s.by_edge||{};"
            "var by_sport=s.by_sport||{};"
            "var updated=s.last_updated||'';"
            "if(total===0){"
            "var t0=renderTracked(window._TRACKED);"
            "document.getElementById('perf-content').innerHTML=(t0||'')+"
            "\"<div class='perf-empty'><div class='perf-empty-icon'>⏳</div>"
            "<div class='perf-empty-title'>En attente de resultats du modele</div>"
            "<div class='perf-empty-sub'>Des bets ont ete enregistres mais aucun match n'est encore resolu.</div></div>\";"
            "return;}"
            "var pc=profit>=0?'#1D9E75':'#A32D2D';"
            "var rc2=roi>=0?'#1D9E75':'#A32D2D';"
            "var ps=profit>=0?'+':'';"
            "var rs2=roi>=0?'+':'';"
            "var wrc=wr>=55?'#1D9E75':wr>=50?'#BA7517':'#A32D2D';"
            "var h=\"<div class='perf-wrap'>\";"
            "h+=renderTracked(window._TRACKED)||'';"
            "h+=\"<div class='perf-title'>Performance cumulee du modele</div>\";"
            "h+=\"<div class='perf-grid'>\";"
            "h+=\"<div class='perf-box'><div class='perf-label'>Bets resolus</div><div class='perf-val'>\"+total+\"</div></div>\";"
            "h+=\"<div class='perf-box'><div class='perf-label'>Win Rate</div><div class='perf-val' style='color:\"+wrc+\"'>\"+wr+\"%</div></div>\";"
            "h+=\"<div class='perf-box'><div class='perf-label'>Profit (unites)</div><div class='perf-val' style='color:\"+pc+\"'>\"+ps+profit+\"u</div></div>\";"
            "h+=\"<div class='perf-box'><div class='perf-label'>ROI</div><div class='perf-val' style='color:\"+rc2+\"'>\"+rs2+roi+\"%</div></div>\";"
            "h+=\"</div>\";"

            # Par sport
            "var sportKeys=Object.keys(by_sport);"
            "var sportLabels={'nhl':'🏒 NHL','nba':'🏀 NBA','mlb':'⚾ MLB'};"
            "if(sportKeys.length>1){"
            "h+=\"<div class='perf-section-title'>Par sport</div><div class='perf-edge-table'>\";"
            "sportKeys.forEach(function(sp){"
            "var info=by_sport[sp];"
            "var n=info.n||0;var w=info.wins||0;var p=info.profit||0;"
            "var wrl=n>0?Math.round(w/n*1000)/10:0;"
            "var epc=p>=0?'#1D9E75':'#A32D2D';"
            "var eps=p>=0?'+':'';"
            "var lbl=sportLabels[sp]||sp.toUpperCase();"
            "h+=\"<div class='perf-edge-row'>\";"
            "h+=\"<span class='perf-edge-label'>\"+lbl+\"</span>\";"
            "h+=\"<span class='perf-edge-n'>\"+n+\" bets</span>\";"
            "h+=\"<span class='perf-edge-wr'>\"+wrl+\"% WR</span>\";"
            "h+=\"<span class='perf-edge-profit' style='color:\"+epc+\"'>\"+eps+p+\"u</span>\";"
            "h+=\"</div>\";"
            "});"
            "h+=\"</div>\";}"

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
            "var recent=resolved.slice().sort(function(a,b){return(b.date||'').localeCompare(a.date||'');}).slice(0,30);"
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
            # Auto-bascule sur l'onglet MLB si la NHL est vide (hors-saison) mais que MLB a des bets
            "(function(){function go(){try{var s=window._SIGNAL||{};"
            "var mlb=(s.mlb_analysis||[]).reduce(function(n,g){return n+((g.bets||[]).length);},0);"
            "var nhl=s.total_value_bets||0;"
            "if(nhl===0&&mlb>0){var b=null;document.querySelectorAll('.tab').forEach(function(x){if(x.textContent.trim()==='MLB')b=x;});if(b)showTab('tab-mlb',b);}"
            "}catch(e){}}"
            "if(document.readyState!=='loading')go();else document.addEventListener('DOMContentLoaded',go);})();"
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
            # ── Tableau Moneyline / -1.5 ──────────────────────────────────
            ".ml-tbl{background:var(--s);border:1px solid var(--b);border-radius:var(--r);"
            "overflow:hidden;margin-bottom:1.5rem}"
            ".ml-tr{display:grid;grid-template-columns:1.7fr .6fr .7fr .7fr .8fr 1.3fr;"
            "gap:6px;align-items:center;padding:9px 12px;font-size:13px;"
            "border-top:1px solid var(--b)}"
            ".ml-th{background:var(--bg);font-size:11px;font-weight:600;color:var(--m);"
            "text-transform:uppercase;letter-spacing:.4px;border-top:none}"
            ".ml-team{font-weight:600;color:var(--t)}"
            ".ml-why{padding:0 12px 9px;font-size:11px;color:var(--m);line-height:1.45}"
            ".ml-note{font-size:11px;color:var(--m);margin:-1rem 0 1.5rem;line-height:1.5}"
            "@media(max-width:620px){.ml-tr{grid-template-columns:1.4fr .5fr .6fr .6fr .7fr;"
            "font-size:12px}.ml-tr>span:last-child{grid-column:1/-1;color:var(--m)}}"
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
            ".mlb-k-curve{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;align-items:flex-end}"
            ".mlb-k-curve-title{font-size:10px;font-weight:700;letter-spacing:.08em;color:var(--m);"
            "text-transform:uppercase;width:100%;margin-bottom:2px}"
            ".mlb-k-cell{display:flex;flex-direction:column;align-items:center;padding:6px 8px;"
            "border-radius:6px;min-width:48px;transition:opacity .15s}"
            ".mlb-k-cell:hover{opacity:.8}"
            ".mlb-k-num{font-size:10px;font-weight:700;color:var(--m);letter-spacing:.05em}"
            ".mlb-k-prob{font-size:13px;font-weight:700;color:var(--t);margin:2px 0}"
            ".mlb-k-ev{font-size:11px;font-weight:700;line-height:1.2}"
            ".mlb-k-book{font-size:9px;color:var(--m);letter-spacing:.02em;"
            "text-transform:uppercase;line-height:1.3}"
            ".mlb-k-calc{display:flex;align-items:center;gap:8px;margin-top:8px;font-size:12px;"
            "color:var(--m);flex-wrap:wrap}"
            ".mlb-k-odds-input{width:110px;padding:4px 8px;border:1px solid var(--b);"
            "border-radius:5px;font-size:12px;background:var(--bg);color:var(--t);outline:none}"
            ".mlb-k-odds-input:focus{border-color:var(--accent)}"
            ".mlb-calc-box{background:var(--s);border:1px solid var(--b);border-radius:var(--r);padding:1rem 1.25rem;margin-bottom:1rem}"
            ".mlb-calc-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}"
            ".mlb-calc-select{flex:1;min-width:180px;padding:7px 10px;border:1px solid var(--b);border-radius:6px;background:var(--bg);color:var(--t);font-size:13px;outline:none}"
            ".mlb-calc-select:focus{border-color:var(--accent)}"
            ".mlb-calc-curve{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}"
            ".mlb-calc-cell{display:flex;flex-direction:column;align-items:center;padding:8px 10px;border-radius:6px;min-width:52px;border:1px solid var(--b);cursor:pointer;transition:all .15s}"
            ".mlb-calc-cell:hover,.mlb-calc-cell.sel{border-color:var(--accent);background:rgba(37,99,235,.08)}"
            ".mlb-calc-cell .kn{font-size:10px;color:var(--m);font-weight:700;letter-spacing:.05em}"
            ".mlb-calc-cell .kp{font-size:14px;font-weight:700;color:var(--t)}"
            ".mlb-calc-result{display:flex;align-items:center;gap:10px;flex-wrap:wrap}"
            ".mlb-calc-odds-in{width:130px;padding:7px 10px;border:1px solid var(--b);border-radius:6px;font-size:13px;background:var(--bg);color:var(--t);outline:none}"
            ".mlb-calc-odds-in:focus{border-color:var(--accent)}"
            ".mlb-calc-edge{font-size:15px;font-weight:700;min-width:120px}"
            # ── General ───────────────────────────────────────────────────
            ".disc{font-size:11px;color:var(--m);margin-top:2rem;padding-top:1rem;border-top:1px solid var(--b);line-height:1.8}"
            ".upd{font-size:11px;color:var(--m);text-align:right;margin-top:.5rem}"
            # Paris suivis (bets.json)
            ".trk{margin-bottom:1.5rem;padding-bottom:1.25rem;border-bottom:1px solid var(--b)}"
            ".trk-sub{font-size:12px;color:var(--m);margin:-.35rem 0 .75rem}"
            ".trk-mini{font-size:10px;color:var(--m);margin-top:3px;line-height:1.35}"
            ".trk-note{font-size:11px;color:var(--m);margin:.5rem 0}"
            ".trk-note code{background:var(--bg2,#F3F4F6);padding:1px 4px;border-radius:3px;font-size:10px}"
            ".trk-cal{display:flex;flex-direction:column;gap:3px}"
            ".trk-cal-row{display:flex;align-items:center;gap:8px;font-size:11px;padding:3px 0}"
            ".trk-thin{opacity:.62}"
            ".trk-cal-b{width:52px;font-weight:700;color:var(--t)}"
            ".trk-cal-n{width:74px;color:var(--m);font-size:10px}"
            ".trk-cal-bars{flex:1;min-width:80px;display:flex;flex-direction:column;gap:2px}"
            ".trk-bar{display:block;height:5px;border-radius:3px;min-width:2px}"
            ".trk-bar-exp{background:#9CA3AF}"
            ".trk-bar-obs{background:#0F6E56}"
            ".trk-cal-v{width:96px;text-align:right;color:var(--t);font-variant-numeric:tabular-nums}"
            ".trk-cal-gap{width:46px;text-align:right;font-weight:700;font-variant-numeric:tabular-nums}"
            ".trk-legend{font-size:10px;color:var(--m);margin-top:.5rem;display:flex;"
            "align-items:center;gap:5px;flex-wrap:wrap}"
            ".trk-key{display:inline-block;width:14px;height:5px;border-radius:3px;margin-right:2px}"
            ".trk-flag{font-size:9px;color:var(--m);margin-left:5px;text-transform:uppercase;"
            "letter-spacing:.03em;font-weight:600}"
            "@media(max-width:560px){.trk-cal-bars{display:none}.trk-cal-n{width:58px}}"
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
