"""
Onglet NFL (refait 2026-10-04): ne chercher que la ou bet365 laisse de la
valeur.

  1. Lignes principales (ML / spread / total): bet365 y garde ~4.5-5 % de
     marge, aucune ligne n'atteint jamais la cote a exiger. Une seule ligne
     repliee; les probabilites Pinnacle restent dans les donnees.
  2. Props a ligne ajustee (priorite): la ligne bet365 differe souvent de
     celle de Pinnacle. Mediane implicite tiree de Pinnacle, puis p a la
     ligne bet365 par la distribution empirique (nfl_prop_model).
  3. Cotes boostees: jambe simple ou multi-matchs = produit des p Pinnacle;
     meme match = informatif (correle).

En haut: une seule liste « A MISER », triee par edge, toutes sources
confondues, avec la mise (1/4 Kelly plafonne, bankroll reglable).

Tout le HTML/JS propre a l'onglet est ici; report_generator n'expose que
deux points d'accroche (nfxStatus / nfxKelly) dans le code de saisie commun.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from html import escape

import pytz

import nfl_prop_model as M

STAKING = {"KELLY_FRACTION": 0.25, "MAX_BET_PCT": 2.0, "BANKROLL": 1000.0}


def staking() -> dict:
    """Mises NFL: config/betting.json → NFL_STAKING, sinon STAKING ci-dessus."""
    s = dict(STAKING)
    try:
        import betting_config
        s.update({k: float(v) for k, v in (betting_config.load().get("NFL_STAKING") or {}).items()
                  if not k.startswith("_")})
    except Exception:
        pass
    return s


def _a(v) -> str:
    return escape(str(v), quote=True)


def _et_day(ct: str) -> str:
    try:
        return (datetime.fromisoformat(str(ct).replace("Z", "+00:00"))
                .astimezone(pytz.timezone("America/Toronto")).strftime("%Y-%m-%d"))
    except (ValueError, AttributeError):
        return ""


def _imminent(ct: str, hours: int = 24) -> bool:
    try:
        dt = datetime.fromisoformat(str(ct).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    now = datetime.now(pytz.utc)
    return now <= dt <= now + timedelta(hours=hours)


# ── Props: lignes affichees ────────────────────────────────────────────────

def prop_rows(lines: list, cal: dict) -> list:
    """
    Lignes Pinnacle enrichies de la mediane implicite. Masquees: mediane
    < MIN_MEDIAN (l'ecart de ligne n'y vaut rien) ou marche non calibre.
    """
    out = []
    for ln in lines or []:
        cm = (cal.get("markets") or {}).get(ln.get("marche", ""))
        if not cm or not ln.get("p_over"):
            continue
        m = M.implied_median(cm, float(ln["ligne"]), float(ln["p_over"]))
        if m is None or m < M.MIN_MEDIAN:
            continue
        out.append(dict(ln, mediane=round(m, 2), valide=M.is_validated(cm, m)))
    return out


def _props_html(rows: list) -> str:
    if not rows:
        return ("<div class=\"nfx-empty\">Aucune prop Pinnacle exploitable (relevé du dimanche "
                "matin, matchs à total ≥ 47).</div>")
    out = ["<p class=\"nfx-intro\">Lisez chez bet365 la <b>ligne</b>, le <b>côté</b> et la "
           "<b>cote</b>. p = P(résultat au-delà de la ligne bet365) selon la distribution "
           "historique des verges autour de la médiane implicite Pinnacle. <b>À MISER</b> si "
           "edge ≥ " + f"{M.MIN_EDGE * 100:g}" + " %, p ≥ " + f"{M.MIN_PROB * 100:g}"
           + " % et cote entre " + f"{M.MIN_ODDS:.2f}" + " et " + f"{M.MAX_ODDS:.2f}"
           + ". Edge &gt; " + f"{M.SUSPECT_EDGE * 100:g}" + " %: « À VÉRIFIER » (ligne "
           "périmée, blessure, joueur inactif?). Seuls les joueurs à médiane &gt; "
           + f"{M.MIN_MEDIAN:g}" + " verges sont affichés.</p>"]
    par_match: dict = {}
    for r in rows:
        par_match.setdefault((r.get("commence", ""), r.get("game", "")), []).append(r)
    for (ct, game), grp in sorted(par_match.items()):
        out.append("<details class=\"nfx-game\"" + (" open" if _imminent(ct) else "")
                   + "><summary><b>" + escape(game) + "</b> <span class=\"nfl-kick\" data-kick=\""
                   + _a(ct) + "\">—</span> · " + str(len(grp)) + " props</summary>")
        for r in sorted(grp, key=lambda x: (x.get("marche", ""), -x["mediane"])):
            L = float(r["ligne"])
            badge = ("" if r["valide"] else
                     " <span class=\"nfx-info\" title=\"tranche non validée hors échantillon\">informatif</span>")
            out.append(
                "<div class=\"rec-row nfx-row nfx-prop\" data-nfx=\"1\" data-src=\"props\" data-sport=\"nfl\""
                " data-marche=\"" + _a(r["marche"]) + "\" data-joueur=\"" + _a(r["joueur"]) + "\""
                " data-mediane=\"" + f"{r['mediane']:.2f}" + "\" data-valide=\"" + ("1" if r["valide"] else "0") + "\""
                " data-ref_ligne=\"" + f"{L:g}" + "\" data-ref_pover=\"" + f"{r['p_over']:.4f}" + "\""
                " data-ligne_reference=\"" + f"{L:g}" + "\""
                " data-selection=\"" + _a(f"{r['joueur']} Over {L:g}") + "\" data-ligne=\"" + f"{L:g}" + "\""
                " data-prob=\"\" data-prob_marche_novig=\"\""
                " data-date=\"" + _et_day(ct) + "\" data-commence_time=\"" + _a(ct) + "\""
                " data-match=\"" + _a(game) + "\" data-event_id=\"" + _a(r.get("event_id", "")) + "\">"
                "<div class=\"nfx-l1\"><b>" + escape(r["joueur"]) + "</b> <span class=\"nfx-mk\">"
                + escape(r.get("marche_lbl", "")) + "</span>" + badge + "</div>"
                "<div class=\"nfx-l2\">Pinnacle <b>" + f"{L:g}" + "</b> · O " + f"{r['p_over'] * 100:.0f}"
                + " % / U " + f"{r['p_under'] * 100:.0f}" + " % · médiane implicite <b>"
                + f"{r['mediane']:.1f}" + "</b></div>"
                "<div class=\"nfx-in\">"
                "<select class=\"pl-side\" onchange=\"nfxPropUpd(this)\"><option>Over</option><option>Under</option></select>"
                "<input class=\"pl-line\" type=\"text\" inputmode=\"decimal\" value=\"" + f"{L:g}"
                + "\" title=\"ligne bet365\" oninput=\"nfxPropUpd(this)\">"
                "<input class=\"rec-odds\" type=\"number\" step=\"0.01\" min=\"1.01\" placeholder=\"cote bet365\" oninput=\"nfxPropUpd(this)\">"
                "<span class=\"nfx-p\"></span> <span class=\"rec-out\"></span> "
                "<input class=\"rec-stake\" type=\"number\" step=\"0.05\" min=\"0\" value=\"0\" oninput=\"this.dataset.manual=1\"> %"
                " <button class=\"rec-btn\" onclick=\"recSave(this)\" disabled>Enregistrer</button></div>"
                "</div>")
        out.append("</details>")
    return "".join(out)


# ── Lignes principales: repliees ───────────────────────────────────────────

def _main_lines_html(games: list) -> str:
    rows = []
    for g in sorted(games or [], key=lambda x: x.get("commence") or ""):
        px = g.get("prices") or {}
        cells = " · ".join(f"{escape(lab)} {v.get('fair_odds', 0):.2f}"
                           for lab, v in sorted(px.items(), key=lambda kv: kv[1].get("market", ""))
                           if v.get("fair_odds"))
        rows.append("<div class=\"nfx-main\"><b>" + escape(f"{g.get('away_team', '')} @ {g.get('home_team', '')}")
                    + "</b> <span class=\"nfl-kick\" data-kick=\"" + _a(g.get("commence", "")) + "\">—</span>"
                    "<div class=\"nfx-l2\">cotes justes Pinnacle: " + (cells or "—") + "</div></div>")
    return ("<details class=\"nfx-sec\"><summary>Lignes principales : marché efficace, pas de pari "
            "attendu sur bet365</summary><p class=\"nfx-intro\">bet365 garde ~4,5-5 % de marge sur "
            "ML / spread / total: la cote à exiger n'est jamais atteinte. Cotes justes (Pinnacle "
            "sans marge) pour référence seulement.</p>" + "".join(rows) + "</details>")


# ── Boosts ─────────────────────────────────────────────────────────────────

def boost_legs(st: dict) -> dict:
    """Jambes possibles d'un boost, avec leur probabilite juste Pinnacle."""
    legs = {}
    for g in st.get("games") or []:
        match = f"{g.get('away_team', '')} @ {g.get('home_team', '')}"
        for lab, px in (g.get("prices") or {}).items():
            p = (px.get("prob") or 0) / 100.0
            if 0 < p < 1:
                legs[f"{lab} ({match})"] = {
                    "selection": lab, "marche": px.get("market", ""), "p": round(p, 4),
                    "match": match, "commence_time": g.get("commence", ""),
                    "event_id": g.get("event_id", "")}
    for ln in (st.get("props") or {}).get("lines") or []:
        for side, p in (("Over", ln.get("p_over")), ("Under", ln.get("p_under"))):
            if not p or not (0 < p < 1):
                continue
            sel = f"{ln['joueur']} {side} {ln['ligne']:g}"
            legs[f"{sel} {ln.get('marche_lbl', '')}"] = {
                "selection": sel, "marche": ln.get("marche", ""), "p": round(p, 4),
                "match": ln.get("game", ""), "commence_time": ln.get("commence", ""),
                "event_id": ln.get("event_id", ""), "joueur": ln["joueur"], "ligne": ln["ligne"]}
    return legs


def _boost_html(st: dict) -> str:
    legs = boost_legs(st)
    if not legs:
        return "<div class=\"nfx-empty\">Aucune cote de référence pour composer un boost.</div>"
    opts = "".join("<option value=\"" + _a(k) + "\">" for k in sorted(legs))
    leg_in = "".join("<input class=\"bo-leg\" list=\"nfl-legs\" placeholder=\"jambe " + str(i + 1)
                     + (" (facultatif)" if i else "") + "\" oninput=\"boostUpd(this)\">" for i in range(4))
    return ("<p class=\"nfx-intro\">edge = cote boostée × p − 1 (p = produit des probabilités "
            "Pinnacle). <b>À MISER</b> dès " + f"{M.BOOST_MIN_EDGE * 100:g}" + " %. Jambes d'un "
            "<b>même match</b>: corrélées, informatif seulement. <b>bet365 plafonne souvent la "
            "mise d'un boost</b>: ajustez-la.</p>"
            "<datalist id=\"nfl-legs\">" + opts + "</datalist>"
            "<script>var NFL_LEGS=" + json.dumps(legs, ensure_ascii=False).replace("</", "<\\/") + ";</script>"
            "<div class=\"rec-row nfl-boost\" data-nfx=\"1\" data-src=\"boost\" data-sport=\"nfl\" "
            "data-marche=\"nfl_boost\" data-prob=\"\" data-date=\"\">"
            "<div class=\"bo-legs\">" + leg_in + "</div><div class=\"bo-info\"></div>"
            "<div class=\"nfx-in\">cote boostée <input class=\"rec-odds\" type=\"number\" step=\"0.01\" min=\"1.01\" "
            "placeholder=\"bet365\" oninput=\"boostUpd(this)\"> <span class=\"rec-out\"></span> "
            "<input class=\"rec-stake\" type=\"number\" step=\"0.05\" min=\"0\" value=\"0\" "
            "oninput=\"this.dataset.manual=1\"> % <button class=\"rec-btn\" onclick=\"recSave(this)\">"
            "Enregistrer</button></div></div>")


# ── Assemblage ─────────────────────────────────────────────────────────────

def render(state: dict, cal: dict = None) -> str:
    st = state or {}
    cal = cal if cal is not None else M.load_calibration()
    props = st.get("props") or {}
    rows = prop_rows(props.get("lines") or [], cal)
    sk = staking()
    head = ["<div class=\"sec\">🏈 NFL — là où bet365 laisse de la valeur</div><div class=\"nfx\">"]
    if st.get("stale") or props.get("stale"):
        head.append("<div class=\"nfl-stale\">Cotes relevées plus tôt — "
                    + escape(str(props.get("reason") or st.get("reason", "")))
                    + ". Les prix ont pu bouger.</div>")
    head.append(
        "<div class=\"nfx-top\"><div class=\"nfx-top-h\">À MISER <span class=\"nfx-n\" id=\"nfx-n\">0</span>"
        "<label class=\"nfx-bk\">bankroll <input id=\"nfx-bankroll\" type=\"text\" inputmode=\"decimal\" "
        "oninput=\"nfxBankroll(this)\"> $</label></div>"
        "<div id=\"nfx-amiser\"><div class=\"nfx-empty\">Rien pour l'instant: saisissez les lignes et "
        "cotes bet365 ci-dessous (props, boosts). Mise = ¼ Kelly, plafonnée à "
        + f"{sk['MAX_BET_PCT']:g}" + " % de la bankroll.</div></div></div>")
    body = [
        _main_lines_html(st.get("games") or []),
        "<details class=\"nfx-sec\" open><summary>Props — écarts de ligne (" + str(len(rows))
        + " joueurs)</summary>" + _props_html(rows) + "</details>",
        "<details class=\"nfx-sec\"><summary>Cotes boostées</summary>" + _boost_html(st) + "</details>",
        "<details class=\"nfx-sec\" id=\"nfx-suivi\" ontoggle=\"if(this.open)nfxSuivi()\"><summary>Suivi — "
        "paris NFL ouverts (fermeture / CLV)</summary><div id=\"nfx-suivi-c\" class=\"nfx-empty\">"
        "Chargement…</div></details>",
        "</div>",
        "<script>var NFL_CAL=" + json.dumps(cal.get("markets") or {}, separators=(",", ":"))
        + ";var NFL_ST=" + json.dumps(sk) + ";var NFX_RULES=" + json.dumps({
            "min_edge": M.MIN_EDGE, "min_prob": M.MIN_PROB, "min_odds": M.MIN_ODDS,
            "max_odds": M.MAX_ODDS, "suspect": M.SUSPECT_EDGE, "boost": M.BOOST_MIN_EDGE})
        + ";</script>",
        "<style>" + CSS + "</style><script>" + JS + "</script>",
    ]
    return "".join(head + body)


# ── JS de l'onglet (fonctions globales, prefixe nfx) ───────────────────────
# nfxProbAt est le miroir de nfl_prop_model.prob_at: meme interpolation entre
# tranches, meme convention de push. test_nfl_tab compare les deux.
JS = r"""
function nfxNum(v){v=String(v==null?'':v).trim().replace(',','.');var x=parseFloat(v);return isNaN(x)?NaN:x;}
function nfxCenter(b){return b.hi<1e8?(b.lo+b.hi)/2:b.lo*1.25;}
function nfxWeights(cm,m){var bs=(cm&&cm.buckets)||[];if(!bs.length)return [];
var cs=bs.map(nfxCenter);if(m<=cs[0])return [[bs[0],1]];if(m>=cs[cs.length-1])return [[bs[bs.length-1],1]];
for(var i=0;i<bs.length-1;i++){if(cs[i]<=m&&m<=cs[i+1]){var t=(m-cs[i])/(cs[i+1]-cs[i]);return [[bs[i],1-t],[bs[i+1],t]];}}
return [[bs[bs.length-1],1]];}
function nfxBL(q,r){var lo=0,hi=q.length;while(lo<hi){var md=(lo+hi)>>1;if(q[md]<r)lo=md+1;else hi=md;}return lo;}
function nfxBR(q,r){var lo=0,hi=q.length;while(lo<hi){var md=(lo+hi)>>1;if(q[md]<=r)lo=md+1;else hi=md;}return lo;}
function nfxSurv(b,r){var q=b.q,n=q.length-1;if(r<q[0])return 1;if(r>=q[n])return 0;
var lo=nfxBL(q,r),hi=nfxBR(q,r);if(hi>lo)return 1-(hi-1)/n;var i=lo-1;return 1-(i+(r-q[i])/(q[i+1]-q[i]))/n;}
function nfxSurvAt(cm,m,r){return nfxWeights(cm,m).reduce(function(a,w){return a+w[1]*nfxSurv(w[0],r);},0);}
function nfxProbAt(cm,m,L,side){if(!(m>0)||!nfxWeights(cm,m).length)return null;
var whole=Math.abs(L-Math.round(L))<1e-9,po,pu;
if(whole){po=nfxSurvAt(cm,m,(L+0.5)/m);pu=1-nfxSurvAt(cm,m,(L-0.5)/m);}else{po=nfxSurvAt(cm,m,L/m);pu=1-po;}
return side==='Over'?po:pu;}
function nfxKelly(p,o){if(!(o>1)||!(p>0&&p<1))return 0;var f=(p*o-1)/(o-1);if(f<=0)return 0;
return Math.min(f*NFL_ST.KELLY_FRACTION*100,NFL_ST.MAX_BET_PCT);}
function nfxStatus(row,e){var R=NFX_RULES,d=row.dataset;
if(d.marche==='nfl_boost'){if(d.correle==='1')return['informatif — jambes corrélées (même match)','#92400E'];
return e>=R.boost*100?['à miser','#0F6E56']:['sous le seuil','#6B7280'];}
var p=parseFloat(d.prob),o=parseFloat((row.querySelector('.rec-odds')||{}).value);
if(d.valide!=='1')return['informatif — tranche non validée','#92400E'];
if(e>R.suspect*100)return['À VÉRIFIER (ligne périmée, blessure, inactif ?)','#B45309'];
if(e>=R.min_edge*100&&p>=R.min_prob&&o>=R.min_odds&&o<=R.max_odds)return['à miser','#0F6E56'];
if(e>=R.min_edge*100&&p<R.min_prob)return['p < '+(R.min_prob*100)+' %','#6B7280'];
if(e>=R.min_edge*100)return['cote hors '+R.min_odds.toFixed(2)+'–'+R.max_odds.toFixed(2),'#6B7280'];
return['sous le seuil','#6B7280'];}
function nfxPropUpd(el){var row=el.closest('.rec-row');if(!row)return;var d=row.dataset;
var side=row.querySelector('.pl-side').value,L=nfxNum(row.querySelector('.pl-line').value);
var info=row.querySelector('.nfx-p'),b=row.querySelector('.rec-btn');
var p=isNaN(L)?null:nfxProbAt(NFL_CAL[d.marche],parseFloat(d.mediane),L,side);
if(p===null){d.prob='';info.textContent='ligne ?';if(b)b.disabled=true;recCalc(row.querySelector('.rec-odds'));nfxAMiser();return;}
p=Math.round(p*1e4)/1e4;d.prob=p;d.prob_modele=p;d.ligne=L;d.selection=d.joueur+' '+side+' '+L;
var exact=Math.abs(L-parseFloat(d.ref_ligne))<1e-9,po=parseFloat(d.ref_pover);
d.prob_marche_novig=exact?(side==='Over'?po:Math.round((1-po)*1e4)/1e4):'';
info.innerHTML='p <b>'+(p*100).toFixed(1)+' %</b> · juste <b>'+(1/p).toFixed(2)+'</b>';
if(b&&d.saved!=='1'){b.disabled=false;b.textContent='Enregistrer';}
recCalc(row.querySelector('.rec-odds'));nfxAMiser();}
function nfxBankrollVal(){var v=nfxNum(localStorage.getItem('nfl_bankroll'));return v>0?v:NFL_ST.BANKROLL;}
function nfxBankroll(inp){var v=nfxNum(inp.value);if(v>0)localStorage.setItem('nfl_bankroll',String(v));nfxAMiser();}
function nfxAMiser(){var box=document.getElementById('nfx-amiser');if(!box)return;var bk=nfxBankrollVal(),L=[];
[].slice.call(document.querySelectorAll('.rec-row[data-nfx="1"]')).forEach(function(r){
var o=parseFloat((r.querySelector('.rec-odds')||{}).value),p=parseFloat(r.dataset.prob);if(!(o>1)||!(p>0))return;
var e=(p*o-1)*100;if(nfxStatus(r,e)[0]!=='à miser')return;
var m=parseFloat(r.dataset.sugg||'0')||nfxKelly(p,o);
L.push({src:r.dataset.src==='boost'?'boost':'prop',sel:r.dataset.selection,match:r.dataset.match||'',o:o,p:p,e:e,m:m});});
L.sort(function(a,b){return b.e-a.e;});document.getElementById('nfx-n').textContent=L.length;
if(!L.length){box.innerHTML='<div class="nfx-empty">Rien à miser pour l\'instant: saisissez les lignes et cotes bet365 ci-dessous. Mise = ¼ Kelly, plafonnée à '+NFL_ST.MAX_BET_PCT+' % de la bankroll.</div>';return;}
box.innerHTML='<table class="nfx-t"><thead><tr><th>Source</th><th>Pari</th><th>Cote</th><th>p</th><th>Edge</th><th>Mise</th></tr></thead><tbody>'+
L.map(function(x){return '<tr><td>'+x.src+'</td><td><b>'+x.sel+'</b><div class="nfx-l2">'+x.match+'</div></td><td>'+x.o.toFixed(2)+'</td><td>'+(x.p*100).toFixed(1)+' %</td><td>+'+x.e.toFixed(1)+' %</td><td><b>'+x.m.toFixed(2)+' %</b> · '+(x.m*bk/100).toFixed(0)+' $</td></tr>';}).join('')+'</tbody></table>';}
function nfxSuivi(){var c=document.getElementById('nfx-suivi-c');if(!c)return;
fetch('performance.json?t='+Date.now()).then(function(r){return r.json();}).then(function(p){var L=p.nfl_ouverts||[];
if(!L.length){c.innerHTML='Aucun pari NFL ouvert.';return;}
c.className='';c.innerHTML='<p class="nfx-intro">CLV = cote prise ÷ cote bet365 à la fermeture − 1, <b>à la même ligne</b> (si la ligne a bougé, lisez la cote de votre ligne dans les lignes alternatives bet365, juste avant le coup d\'envoi).</p>'+
L.map(function(x){return '<div class="nfx-row" data-id="'+x.id.replace(/"/g,'')+'"><b>'+x.selection+'</b> · pris '+Number(x.cote_prise).toFixed(2)+(x.clv!=null&&x.clv!==''?' · CLV '+(100*x.clv).toFixed(1)+' %':'')+
' <input class="nfx-close" type="text" inputmode="decimal" placeholder="cote fermeture"> <button class="rec-btn" onclick="nfxClose(this)">Enregistrer</button></div>';}).join('');})
.catch(function(){c.textContent='performance.json indisponible.';});}
async function nfxClose(btn){var row=btn.closest('.nfx-row');var o=nfxNum(row.querySelector('.nfx-close').value);
if(!(o>1)){btn.textContent='cote ?';return;}var tk=ghToken();if(!tk){btn.textContent='✗ pas de token';return;}
btn.disabled=true;btn.textContent='⏳';
try{var r=await fetch('https://api.github.com/repos/'+GH_REPO+'/actions/workflows/record_prediction.yml/dispatches',{method:'POST',
headers:{'Authorization':'token '+tk,'Accept':'application/vnd.github.v3+json','Content-Type':'application/json'},
body:JSON.stringify({ref:'main',inputs:{payload:JSON.stringify({action:'fermeture',id:row.dataset.id,cote_fermeture:o})}})});
btn.textContent=r.status===204?'✓ Enregistré':'✗ '+r.status;if(r.status!==204)btn.disabled=false;}catch(e){btn.textContent='✗ réseau';btn.disabled=false;}}
function nfxPerf(p){var s=p.nfl_sources||{},k=Object.keys(s);var h='<div class="pj-group"><div class="perf-section-title">NFL — par source <span class="pj-n">CLV = indicateur principal</span></div>';
if(!k.length)h+='<div class="trk-note">Aucun pari NFL enregistré pour l\'instant.</div>';
else{h+='<table class="pj-tbl nfx-t"><thead><tr><th>Source</th><th>Paris</th><th>Réglés</th><th>CLV moyen</th><th>ROI</th><th>Réussite</th></tr></thead><tbody>';
k.forEach(function(n){var g=s[n];h+='<tr><td>'+n+'</td><td>'+g.n+'</td><td>'+g.n_regles+'</td><td>'+_pc(g.clv_moyen,1)+(g.n_clv?' (n='+g.n_clv+')':'')+'</td><td>'+_pc(g.roi,1)+'</td><td>'+(g.taux_reussite==null?'—':(100*g.taux_reussite).toFixed(0)+' %')+'</td></tr>';});h+='</tbody></table>';}
h+='<div id="nfx-calrep" class="trk-note">Rapport de calibration des props…</div></div>';
setTimeout(nfxCalReport,0);return h;}
function nfxCalReport(){var el=document.getElementById('nfx-calrep');if(!el)return;
fetch('nfl_calibration_report.json?t='+Date.now()).then(function(r){return r.json();}).then(function(r){var m=r.markets||{},meta=r.meta||{};
var h='<div class="perf-section-title">Calibration props NFL — hors échantillon</div><div class="trk-note">Calibré sur '+(meta.calibration||[]).join('+')+', testé sur '+meta.test+'. P prédite vs fréquence observée de « verges &gt; seuil × médiane ». Tranche « validée » = erreur moyenne ≤ 3 pts aux seuils 0,9× et 1,1× en validation croisée par saison; sinon informatif.</div>';
Object.keys(m).forEach(function(k){var x=m[k];h+='<div class="nfx-l1" style="margin-top:8px"><b>'+x.label+'</b> · '+x.n_train+' matchs calibration / '+x.n_test+' test · tranches: '+(x.tranches||[]).map(function(t){return t.tranche+(t.valide?' ✓':' ✗')+' ('+(t.erreur_cv==null?'—':(100*t.erreur_cv).toFixed(1)+' pts')+')';}).join(' · ')+'</div>';
h+='<table class="pj-tbl nfx-t"><thead><tr><th>Tranche</th><th>Seuil</th><th>n</th><th>Prédit</th><th>Observé</th><th>Écart</th></tr></thead><tbody>'+(x.lignes||[]).map(function(l){var bad=Math.abs(l.ecart)>l.ic95;
return '<tr'+(bad?' style="color:#B45309"':'')+'><td>'+l.tranche+'</td><td>'+l.seuil+'×</td><td>'+l.n+'</td><td>'+(100*l.p_predite).toFixed(1)+' %</td><td>'+(100*l.freq_observee).toFixed(1)+' %</td><td>'+(l.ecart>=0?'+':'')+(100*l.ecart).toFixed(1)+'</td></tr>';}).join('')+'</tbody></table>';});
el.className='';el.innerHTML=h;}).catch(function(){el.textContent='Rapport de calibration indisponible.';});}
document.addEventListener('input',function(ev){if(ev.target&&ev.target.closest&&ev.target.closest('.nfx'))setTimeout(nfxAMiser,0);});
document.addEventListener('DOMContentLoaded',function(){var i=document.getElementById('nfx-bankroll');if(i)i.value=nfxBankrollVal();
[].slice.call(document.querySelectorAll('.nfx-prop')).forEach(function(r){nfxPropUpd(r.querySelector('.pl-line'));});});
"""

CSS = (
    ".nfx-top{border:2px solid #10B981;border-radius:10px;padding:10px 12px;margin:8px 0 14px}"
    ".nfx-top-h{font-weight:800;font-size:14px;display:flex;align-items:center;gap:10px}"
    ".nfx-n{background:#10B981;color:#fff;border-radius:10px;padding:0 8px;font-size:12px}"
    ".nfx-bk{margin-left:auto;font-weight:400;font-size:12px;color:var(--m)}.nfx-bk input{width:80px}"
    ".nfx-sec{margin:10px 0;border:1px solid var(--b);border-radius:8px;padding:6px 10px}"
    ".nfx-sec>summary{cursor:pointer;font-weight:700;font-size:13px;padding:4px 0}"
    ".nfx-game{margin:6px 0 6px 6px}.nfx-game>summary{cursor:pointer;font-size:12px}"
    ".nfx-row{padding:6px 4px;border-top:1px solid var(--b);font-size:12px}"
    ".nfx-l1{font-size:12px}.nfx-l2{font-size:11px;color:var(--m)}"
    ".nfx-mk{font-size:10px;text-transform:uppercase;color:var(--m);margin-left:4px}"
    ".nfx-info{font-size:10px;background:#FEF3C7;color:#92400E;border-radius:4px;padding:1px 5px;margin-left:4px}"
    ".nfx-in{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:4px}"
    ".nfx-in input,.nfx-in select{width:74px}.nfx-in .rec-stake{width:58px}"
    ".nfx-intro{font-size:11px;color:var(--m);margin:4px 0 8px}.nfx-empty{font-size:12px;color:var(--m);padding:6px 0}"
    ".nfx-main{padding:4px 0;border-top:1px solid var(--b);font-size:12px}"
    ".nfx-t{width:100%;border-collapse:collapse;font-size:12px}.nfx-t th,.nfx-t td{text-align:left;padding:4px 6px;border-top:1px solid var(--b)}"
)
