    def _props_section(self, props_by_game):
        if not props_by_game:
            return "<div style='color:var(--m);padding:1rem 0;font-size:13px'>Aucune analyse joueurs disponible.</div>"

        DEF_LABELS = {
            "elite": ("Elite (top 4)",    "#0F6E56"),
            "good":  ("Bonne (top 10)",   "#2563EB"),
            "avg":   ("Moyenne",           "#6B7280"),
            "weak":  ("Faible (bot 10)",  "#B45309"),
        }

        html = ""
        for analysis in props_by_game:
            home  = analysis.get("home_team", "")
            away  = analysis.get("away_team", "")
            hg    = analysis.get("home_goalie", {})
            ag    = analysis.get("away_goalie", {})
            props = analysis.get("props", [])
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
                "DEF " + home[:3].upper() + ": " + hdef_label + " · " + str(hshots) + " shots/m · " + str(hga) + " but/m"
                "</span>"
                "<span class=\"db\" style=\"color:" + adef_color + ";border-color:" + adef_color + "\">"
                "DEF " + away[:3].upper() + ": " + adef_label + " · " + str(ashots) + " shots/m · " + str(aga) + " but/m"
                "</span>"
                "</div></div>"
            )

            # Gardiens
            goalie_pairs = [(hg, "DOM — " + home), (ag, "VIS — " + away)]
            goalie_html = ""
            for g, label in goalie_pairs:
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

            # Cards joueurs
            if props:
                html += "<div class=\"pcards\">"
                for p in props:
                    name   = p.get("name", "")
                    pos    = p.get("position", "")
                    team   = p.get("team", "")
                    opp    = p.get("opponent", "")
                    toi    = p.get("toi", "--")
                    ng     = p.get("n_games", 0)
                    reason = p.get("reason", "")

                    # Shots
                    spg  = p.get("shots_pg", 0)
                    sadj = p.get("shots_pg_adj", 0)
                    sln  = p.get("shots_line", 0)
                    sopc = p.get("shots_over_pct", 0)
                    l5s  = p.get("last5_shots", 0)

                    # Buts
                    gpg  = p.get("goals_pg", 0)
                    gadj = p.get("goals_pg_adj", 0)
                    gopc = p.get("goals_over_pct", 0)
                    l5g  = p.get("last5_goals", 0)

                    # Points
                    ppg  = p.get("points_pg", 0)
                    padj = p.get("points_pg_adj", 0)
                    popc = p.get("points_over_pct", 0)
                    l5p  = p.get("last5_points", 0)

                    def pct_color(v):
                        if v >= 70: return "#0F6E56"
                        if v >= 58: return "#BA7517"
                        return "#6B7280"

                    def rec(v, line):
                        if v >= 70: return "✅ OVER " + str(line)
                        if v >= 58: return "⚠️ OVER " + str(line)
                        return "— skip"

                    shots_trend = ""
                    if ng >= 5:
                        avg5 = round(l5s / 5, 1)
                        if avg5 > spg * 1.1:
                            shots_trend = " 🔥 " + str(avg5) + "/m last 5"
                        elif avg5 < spg * 0.85:
                            shots_trend = " ❄️ " + str(avg5) + "/m last 5"

                    html += (
                        "<div class=\"pc\">"
                        "<div class=\"pch\">"
                        "<div>"
                        "<span class=\"pname\">" + name + "</span>"
                        "<span class=\"ppos\">" + pos + "</span>"
                        "</div>"
                        "<div class=\"pteam\">" + team[:3].upper() + " vs " + opp[:3].upper() + " · TOI " + toi + " (" + str(ng) + "m)</div>"
                        "</div>"

                        "<div class=\"pstats\">"

                        # Shots
                        "<div class=\"pstat\">"
                        "<div class=\"pstat-title\">🎯 Shots on Goal</div>"
                        "<div class=\"pstat-row\">"
                        "<span>Moy 10m: <strong>" + str(spg) + "</strong>" + shots_trend + "</span>"
                        "<span>Adj vs DEF: <strong>" + str(sadj) + "</strong></span>"
                        "<span>Last 5: <strong>" + str(l5s) + " shots</strong></span>"
                        "</div>"
                        "<div class=\"pstat-rec\" style=\"color:" + pct_color(sopc) + "\">"
                        rec(sopc, sln) + " &nbsp;·&nbsp; " + str(sopc) + "% prob"
                        "</div>"
                        "</div>"

                        # Buts
                        "<div class=\"pstat\">"
                        "<div class=\"pstat-title\">🚨 Buts</div>"
                        "<div class=\"pstat-row\">"
                        "<span>Moy 10m: <strong>" + str(round(gpg, 2)) + "</strong></span>"
                        "<span>Adj vs DEF: <strong>" + str(round(gadj, 2)) + "</strong></span>"
                        "<span>Last 5: <strong>" + str(l5g) + " buts</strong></span>"
                        "</div>"
                        "<div class=\"pstat-rec\" style=\"color:" + pct_color(gopc) + "\">"
                        rec(gopc, 0.5) + " &nbsp;·&nbsp; " + str(gopc) + "% prob"
                        "</div>"
                        "</div>"

                        # Points
                        "<div class=\"pstat\">"
                        "<div class=\"pstat-title\">📊 Points</div>"
                        "<div class=\"pstat-row\">"
                        "<span>Moy 10m: <strong>" + str(round(ppg, 2)) + "</strong></span>"
                        "<span>Adj vs DEF: <strong>" + str(round(padj, 2)) + "</strong></span>"
                        "<span>Last 5: <strong>" + str(l5p) + " pts</strong></span>"
                        "</div>"
                        "<div class=\"pstat-rec\" style=\"color:" + pct_color(popc) + "\">"
                        rec(popc, 0.5) + " &nbsp;·&nbsp; " + str(popc) + "% prob"
                        "</div>"
                        "</div>"

                        "</div>"  # /pstats

                        "<div class=\"preason\">💡 " + reason + "</div>"
                        "</div>"  # /pc
                    )
                html += "</div>"  # /pcards

            html += "</div>"  # /pg

        return html
