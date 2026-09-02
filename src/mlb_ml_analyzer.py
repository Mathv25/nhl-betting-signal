"""
MLB Moneyline / Run Line (-1.5) — modèle de probabilité et évaluation de valeur.

PRINCIPE DIRECTEUR: la probabilité ne suffit pas, c'est le couple
(probabilité, cote) qui décide. Une équipe à 65% à 1.40 est un mauvais pari
(65% × 1.40 = 0.91 → -9%). Une équipe à 55% à 2.00 est un bon pari
(55% × 2.00 = 1.10 → +10%). Tout le module est construit autour de ça.

CHAÎNE DE CALCUL
  1. Manches attendues du partant (ip_per_gs), reste au bullpen.
  2. Runs alloués/9 = FIP du partant (pondéré forme récente) sur ses manches
     + FIP du bullpen (pénalisé par la fatigue) sur le reste.
  3. Ajustement pour l'offense adverse via l'OPS index CONTRE LA MAIN du
     partant (substitut du wRC+), élasticité OPS→runs ≈ 1.8.
  4. Ajustement parc + défense + avantage du domicile.
  5. Runs de chaque équipe → loi binomiale négative (les runs MLB sont
     surdispersés: var/moyenne ≈ 2.1, une Poisson sous-estime les blowouts).
  6. Convolution des deux lois → distribution de la marge → P(gagne),
     P(gagne par 2+) pour le -1.5.
  7. RÉTRÉCISSEMENT VERS LE MARCHÉ. Ce modèle n'a AUCUN historique de
     calibration. Le modèle de retraits au bâton du même projet était
     surconfiant de 4 à 14 points même après calibration. On ne répète pas
     l'erreur: la probabilité publiée est un mélange modèle/marché.
  8. Valeur = p × cote - 1, puis classement 🔥 / 🟢 / 🟡 / 🔴.
"""
import math
from datetime import datetime

import requests

import mlb_team_model as tm
import odds_api

# ── Paramètres du modèle ────────────────────────────────────────────────────

# Poids accordé au modèle vs au marché. 0.35 = conservateur, assumé.
# À RELEVER seulement quand le backtest montre que le modèle bat la fermeture.
W_MODEL = 0.35

# Élasticité OPS → runs. Les runs varient à peu près comme OPS^1.8.
OPS_ELASTICITY = 1.8

# Marge du bookmaker supposée quand on ne peut pas déviger à deux voies
# (cas du run line: le +1.5 n'est pas toujours coté par le même book).
ASSUMED_VIG = 0.045

# Les runs alloués dépassent les runs mérités (erreurs, runs non mérités).
UNEARNED_FACTOR = 1.075

# Surdispersion des runs par équipe par match: variance / moyenne.
# Empirique MLB: moyenne ≈ 4.5, écart-type ≈ 3.1 → var/moyenne ≈ 2.1.
RUNS_DISPERSION = 2.1

# Avantage du domicile, en runs, calibré pour reproduire le taux de victoire à
# domicile observé en MLB (~53% ces dernières saisons, en baisse historique).
# Vérifié: +0.30 run → 52.9% à talent égal. (+0.16 ne donnait que 51.5%.)
HOME_RUNS_EDGE = 0.30

# Pondération forme récente du partant (5 départs) vs saison.
# 5 départs = ~30 manches: informatif mais très bruité → poids minoritaire.
W_RECENT_SP = 0.30

# Plancher de cote pour un 🔥. Sous 1.50, il faudrait revendiquer >66% de
# probabilité vraie — ce modèle n'a pas la précision pour ça.
MIN_ODDS_ML = 1.50

# Seuils de valeur (p × cote - 1, en %).
V_FIRE  = 8.0    # 🔥
V_SOLID = 3.0    # 🟢
V_PLAY  = 0.0    # 🟡  (sous 0 → 🔴)

# ── 💎 "No brainer" ─────────────────────────────────────────────────────────
# Palier de CONVICTION, pas de valeur pure: le modèle est très confiant ET le
# prix reste payant. Sert à ne pas rater les spots évidents dont la valeur
# calculée est modeste (2-7%) parce que le marché les a déjà vus en partie.
#
# La garde essentielle est NB_MIN_VALUE = 0: une conviction forte à prix
# négatif reste un 🔴. Sans ça on recrée le piège du « 65% à 1.40 », juste
# déplacé à 1.60 (qui exige quand même 62.5% de probabilité vraie).
NB_MIN_ODDS       = 1.60   # plancher demandé: rien sous 1.60
NB_MIN_MODEL_PROB = 0.60   # conviction du MODÈLE brut, avant rétrécissement
NB_MIN_ALIGNED    = 4      # « plusieurs facteurs dans la même direction »
NB_MIN_VALUE      = 0.0    # jamais de -EV, peu importe la conviction

# Run line -1.5: exigences supplémentaires. On ne veut PAS d'un -1.5 sur un
# match serré, même si l'équipe est favorite.
RL_MIN_VALUE     = 5.0    # valeur minimale pour publier un -1.5
RL_MIN_RUN_DIFF  = 0.85   # différentiel de runs attendu minimum
RL_MIN_ALIGNED   = 3      # nombre de facteurs devant aller dans le même sens

# Facteurs de parc pour les RUNS (différents des facteurs orientés retraits
# utilisés dans mlb_props_analyzer — ici c'est la production de runs).
RUN_PARK_FACTORS = {
    "Coors Field":                  1.28,
    "Great American Ball Park":     1.09,
    "Fenway Park":                  1.07,
    "Globe Life Field":             1.05,
    "Chase Field":                  1.04,
    "Citizens Bank Park":           1.04,
    "Yankee Stadium":               1.03,
    "Wrigley Field":                1.02,
    "Camden Yards":                 1.02,
    "Oriole Park at Camden Yards":  1.02,
    "Truist Park":                  1.01,
    "Rogers Centre":                1.01,
    "Angel Stadium":                1.00,
    "Progressive Field":            1.00,
    "Nationals Park":               1.00,
    "Busch Stadium":                0.99,
    "loanDepot park":               0.98,
    "Target Field":                 0.98,
    "Minute Maid Park":             0.98,
    "Daikin Park":                  0.98,
    "Comerica Park":                0.97,
    "American Family Field":        0.99,
    "PNC Park":                     0.97,
    "Kauffman Stadium":             0.97,
    "Dodger Stadium":               0.96,
    "Guaranteed Rate Field":        1.01,
    "Rate Field":                   1.01,
    "Citi Field":                   0.96,
    "Oracle Park":                  0.94,
    "Petco Park":                   0.94,
    "T-Mobile Park":                0.93,
    "George M. Steinbrenner Field": 1.03,
    "Sutter Health Park":           1.02,
}


# ── Lois de probabilité ─────────────────────────────────────────────────────

def _nb_pmf(mean: float, k_max: int = 24) -> list:
    """
    Loi binomiale négative de moyenne `mean` et de variance
    `mean * RUNS_DISPERSION`, évaluée de 0 à k_max.

    Paramétrage: var = mean + mean^2/r  →  r = mean / (dispersion - 1).
    Une Poisson (dispersion = 1) sous-estimerait fortement les matchs à
    grande marge, ce qui biaiserait le -1.5 vers le bas.
    """
    mean = max(mean, 0.25)
    disp = max(RUNS_DISPERSION, 1.01)
    r = mean / (disp - 1.0)
    p = r / (r + mean)          # P(succès)
    pmf = []
    # P(0) = p^r, puis récurrence P(k) = P(k-1) * (r+k-1)/k * (1-p)
    cur = p ** r
    for k in range(k_max + 1):
        if k == 0:
            pmf.append(cur)
        else:
            cur = cur * (r + k - 1) / k * (1 - p)
            pmf.append(cur)
    total = sum(pmf)
    return [x / total for x in pmf]


def _margin_distribution(mean_a: float, mean_b: float, k_max: int = 24) -> dict:
    """
    Distribution de (runs A - runs B) par convolution des deux lois.
    Retourne {marge: probabilité}.
    """
    pa = _nb_pmf(mean_a, k_max)
    pb = _nb_pmf(mean_b, k_max)
    dist: dict = {}
    for i, ppa in enumerate(pa):
        if ppa < 1e-9:
            continue
        for j, ppb in enumerate(pb):
            if ppb < 1e-9:
                continue
            dist[i - j] = dist.get(i - j, 0.0) + ppa * ppb
    return dist


def _win_probs(mean_a: float, mean_b: float) -> dict:
    """
    P(A gagne), P(A gagne par 2+), P(B gagne), P(B gagne par 2+).

    Le baseball n'a pas de match nul: une égalité après 9 manches va en
    manches supplémentaires. On répartit l'égalité 50/50 pour le moneyline.
    Pour le -1.5 l'égalité ne couvre PAS — les prolongations se terminent
    presque toujours par 1 ou 2 runs, et majoritairement par 1.
    """
    dist = _margin_distribution(mean_a, mean_b)
    p_tie   = dist.get(0, 0.0)
    p_a_win = sum(p for m, p in dist.items() if m > 0)
    p_b_win = sum(p for m, p in dist.items() if m < 0)
    p_a_2   = sum(p for m, p in dist.items() if m >= 2)
    p_b_2   = sum(p for m, p in dist.items() if m <= -2)
    return {
        "p_a_ml":  p_a_win + 0.5 * p_tie,
        "p_b_ml":  p_b_win + 0.5 * p_tie,
        "p_a_rl":  p_a_2,
        "p_b_rl":  p_b_2,
        "p_tie":   p_tie,
    }


# ── Runs attendus ───────────────────────────────────────────────────────────

def _effective_sp_fip(sp: dict) -> float:
    """FIP du partant, mélange saison / 5 derniers départs."""
    season = sp.get("fip") or tm.LEAGUE["fip"]
    rec = sp.get("recent") or {}
    if rec.get("games", 0) >= 3 and rec.get("fip") is not None:
        return round((1 - W_RECENT_SP) * season + W_RECENT_SP * rec["fip"], 3)
    return season


def _bullpen_fatigue_penalty(usage: dict) -> float:
    """
    Pénalité en points de FIP appliquée au bullpen selon sa charge récente.

    Un bullpen qui a lancé beaucoup de manches sur 3 jours envoie ses
    meilleurs bras au repos et ses moins bons au monticule.
    """
    if not usage:
        return 0.0
    ip_per_g = usage.get("rel_ip_per_g", 3.2)
    pen = 0.0
    if ip_per_g >= 5.0:
        pen += 0.45
    elif ip_per_g >= 4.2:
        pen += 0.25
    elif ip_per_g >= 3.6:
        pen += 0.10
    if usage.get("closer_used_b2b"):
        pen += 0.20
    return round(pen, 3)


def _defense_adjustment(defense: dict) -> float:
    """
    Multiplicateur de runs alloués selon la défense. Signal FAIBLE — cette API
    ne donne que fielding% et range factor (ni DRS, ni OAA, ni cadrage du
    receveur). Amplitude volontairement plafonnée à ±1.5%.
    """
    if not defense:
        return 1.0
    fp = defense.get("fielding_pct", 0.984)
    delta = (0.984 - fp) * 10.0      # +0.001 de fielding% ≈ -1% de runs
    return round(min(max(1.0 + delta, 0.985), 1.015), 4)


def _park_factor(venue_name: str) -> float:
    if not venue_name:
        return 1.0
    return RUN_PARK_FACTORS.get(venue_name, 1.0)


def expected_runs(off: dict, off_recent: dict, opp_sp: dict, opp_bp: dict,
                  opp_bp_usage: dict, opp_defense: dict,
                  park: float, is_home: bool) -> dict:
    """
    Runs attendus pour l'équipe dont l'offense est `off`, contre le partant
    `opp_sp` et le bullpen `opp_bp`.
    """
    lg_fip = tm.LEAGUE["fip"]
    lg_rpg = tm.LEAGUE["runs_per_g"]

    sp_fip = _effective_sp_fip(opp_sp)
    ip_sp  = min(max(opp_sp.get("ip_per_gs", 5.3), 3.0), 7.5)

    bp_fip = (opp_bp or {}).get("fip", lg_fip) + _bullpen_fatigue_penalty(opp_bp_usage)
    ip_bp  = max(9.0 - ip_sp, 1.0)

    # Runs alloués par 9 manches par la combinaison partant + bullpen.
    blended_fip = (sp_fip * ip_sp + bp_fip * ip_bp) / (ip_sp + ip_bp)

    # Base: on convertit un FIP en runs attendus relativement à la ligue.
    base_runs = lg_rpg * (blended_fip / lg_fip) * UNEARNED_FACTOR

    # Qualité de l'offense contre CETTE main, via l'OPS index (substitut wRC+).
    ops_idx = (off or {}).get("ops_index", 1.0)
    off_mult = ops_idx ** OPS_ELASTICITY

    # Forme récente de l'offense, poids faible (la qualité sous-jacente prime).
    if off_recent and off_recent.get("runs_per_g"):
        form_ratio = off_recent["runs_per_g"] / lg_rpg
        form_mult  = 1.0 + 0.15 * (form_ratio - 1.0)
        off_mult  *= min(max(form_mult, 0.93), 1.07)

    runs = base_runs * off_mult * park * _defense_adjustment(opp_defense)
    if is_home:
        runs += HOME_RUNS_EDGE

    return {
        "runs":        round(max(runs, 1.2), 3),
        "sp_fip_eff":  sp_fip,
        "bp_fip_eff":  round(bp_fip, 3),
        "ip_sp":       round(ip_sp, 2),
        "blended_fip": round(blended_fip, 3),
        "off_mult":    round(off_mult, 4),
        "ops_index":   ops_idx,
    }


# ── Facteurs alignés ────────────────────────────────────────────────────────

def aligned_factors(team_side: dict, opp_side: dict) -> dict:
    """
    Compte les facteurs qui pointent dans la même direction pour une équipe.

    C'est le cœur de la thèse: « je cherche les situations où plusieurs
    facteurs vont dans la même direction ». Un avantage de 4 facteurs sur 5
    est un signal bien plus fiable qu'un seul gros avantage.
    """
    factors = []

    # 1. Avantage au partant (FIP effectif, plus bas = meilleur)
    d_sp = opp_side["sp_fip_eff"] - team_side["sp_fip_eff"]
    if abs(d_sp) >= 0.25:
        factors.append({
            "nom": "Lanceur partant", "pour": d_sp > 0, "ampleur": round(abs(d_sp), 2),
            "detail": f"FIP {team_side['sp_fip_eff']:.2f} vs {opp_side['sp_fip_eff']:.2f}",
        })

    # 2. K-BB% du partant
    d_kbb = (team_side["sp_k_bb"] or 0) - (opp_side["sp_k_bb"] or 0)
    if abs(d_kbb) >= 0.03:
        factors.append({
            "nom": "K-BB% partant", "pour": d_kbb > 0, "ampleur": round(abs(d_kbb) * 100, 1),
            "detail": f"{team_side['sp_k_bb']:.1%} vs {opp_side['sp_k_bb']:.1%}",
        })

    # 3. Offense contre la main adverse (avantage de platoon inclus)
    d_off = team_side["ops_index"] - opp_side["ops_index"]
    if abs(d_off) >= 0.02:
        factors.append({
            "nom": "Offense vs la main", "pour": d_off > 0, "ampleur": round(abs(d_off) * 100, 1),
            "detail": (f"OPS idx {team_side['ops_index']:.3f} vs "
                       f"{opp_side['ops_index']:.3f}"),
        })

    # 4. Puissance (ISO)
    d_iso = (team_side["iso"] or 0) - (opp_side["iso"] or 0)
    if abs(d_iso) >= 0.015:
        factors.append({
            "nom": "Puissance (ISO)", "pour": d_iso > 0, "ampleur": round(abs(d_iso), 3),
            "detail": f"ISO {team_side['iso']:.3f} vs {opp_side['iso']:.3f}",
        })

    # 5. Bullpen (FIP effectif, fatigue incluse)
    d_bp = opp_side["bp_fip_eff"] - team_side["bp_fip_eff"]
    if abs(d_bp) >= 0.25:
        factors.append({
            "nom": "Bullpen", "pour": d_bp > 0, "ampleur": round(abs(d_bp), 2),
            "detail": f"FIP {team_side['bp_fip_eff']:.2f} vs {opp_side['bp_fip_eff']:.2f}",
        })

    # 6. Vulnérabilité aux retraits: une offense qui frappe dans le vide contre
    #    un partant à haut taux de K est un facteur aggravant.
    if opp_side.get("sp_k_pct") and team_side.get("k_pct"):
        if team_side["k_pct"] >= 0.245 and opp_side["sp_k_pct"] >= 0.25:
            factors.append({
                "nom": "K% offense vs partant", "pour": False,
                "ampleur": round(team_side["k_pct"] * 100, 1),
                "detail": (f"notre K% {team_side['k_pct']:.1%} contre un partant "
                           f"à {opp_side['sp_k_pct']:.1%} de K"),
            })

    pour  = sum(1 for f in factors if f["pour"])
    contre = sum(1 for f in factors if not f["pour"])
    return {"facteurs": factors, "pour": pour, "contre": contre,
            "net": pour - contre}


# ── Valeur et classement ───────────────────────────────────────────────────

def devig_two_way(odds_a: float, odds_b: float) -> tuple:
    """
    Probabilités du marché sans la marge du bookmaker (méthode
    multiplicative). Sans ça, la somme des probabilités implicites dépasse
    100% et on surestime systématiquement la probabilité du marché.
    """
    if not odds_a or not odds_b or odds_a <= 1 or odds_b <= 1:
        return None, None
    ia, ib = 1 / odds_a, 1 / odds_b
    tot = ia + ib
    return ia / tot, ib / tot


def market_probs(odds_entry: dict, home: str, away: str) -> tuple:
    """
    Probabilité no-vig du marché sur le moneyline: (p_home, p_away, source).

    Pourquoi pas simplement devig_two_way sur les meilleures cotes: la
    meilleure cote home et la meilleure cote away viennent souvent de deux
    books différents. Leur somme implicite peut descendre sous 100%, et
    normaliser ce mélange penche vers le book qui a l'écart le plus généreux —
    on s'attribue une partie de l'écart entre books comme s'il venait du
    marché. On devigge donc DANS un book: Pinnacle en priorité (marge la plus
    faible), sinon la médiane des books qui cotent les deux côtés.

    Repli sur devig_two_way (meilleures cotes) quand le détail par book manque,
    pour rester compatible avec les entrées de cotes plus anciennes.
    """
    books = [
        {"book": bk, "over_odds": prices.get(home), "under_odds": prices.get(away)}
        for bk, prices in ((odds_entry or {}).get("ml_books") or {}).items()
    ]
    agg = odds_api.summarize_two_way([b for b in books if b["over_odds"] and b["under_odds"]])
    if agg["n_novig"]:
        p_home = agg["baseline_prob"] / 100.0
        return p_home, 1.0 - p_home, agg["baseline_source"]

    ml = (odds_entry or {}).get("ml", {})
    p_home, p_away = devig_two_way(ml.get(home), ml.get(away))
    return p_home, p_away, "meilleures cotes (multi-books)"


def blend_with_market(p_model: float, p_market: float) -> float:
    """
    Rétrécissement vers le marché. Le marché MLB moneyline est très efficace;
    un modèle sans historique de calibration ne devrait pas s'en écarter
    librement. Si le marché est indisponible, on rétrécit vers 50%.
    """
    if p_market is None:
        return 0.5 + W_MODEL * (p_model - 0.5)
    return W_MODEL * p_model + (1 - W_MODEL) * p_market


def value_pct(prob: float, odds: float) -> float:
    """Valeur = p × cote - 1, en pourcentage. C'est LE critère de décision."""
    if not odds or odds <= 1:
        return None
    return round((prob * odds - 1) * 100, 1)


def is_no_brainer(model_prob: float, odds: float, value: float,
                  aligned_net: int) -> bool:
    """
    💎 « No brainer »: le modèle est franchement confiant, plusieurs facteurs
    pointent dans le même sens, et le prix paie encore.

    `model_prob` est la probabilité BRUTE du modèle (avant rétrécissement vers
    le marché) — c'est elle qui mesure la conviction. `value` est calculée sur
    la probabilité finale, elle, et doit rester positive.
    """
    if value is None or odds is None:
        return False
    return (odds >= NB_MIN_ODDS
            and model_prob >= NB_MIN_MODEL_PROB
            and aligned_net >= NB_MIN_ALIGNED
            and value >= NB_MIN_VALUE)


def classify_ml(prob: float, odds: float, value: float, aligned_net: int,
                model_prob: float = None) -> dict:
    """
    Classement demandé:
      🔥 meilleur bet  = meilleure combinaison probabilité + cote
      💎 no brainer    = conviction forte du modèle, cote >= 1.60, valeur >= 0
      🟢 solide        = bonne probabilité, prix moins intéressant
      🟡 jouable       = petit avantage seulement
      🔴 passe         = favori, mais trop cher
    """
    if value is None:
        return {"tier": "🔴", "label": "passe", "raison": "cote indisponible"}

    if value < V_PLAY:
        # Même une conviction énorme ne rachète pas un prix négatif.
        extra = ""
        if (model_prob is not None and model_prob >= NB_MIN_MODEL_PROB
                and odds >= NB_MIN_ODDS and aligned_net >= NB_MIN_ALIGNED):
            extra = (f" — le modèle aime ({model_prob:.0%}, {aligned_net} facteurs) "
                     f"mais le marché le paie déjà: il faudrait "
                     f"{1 / odds:.0%} pour être à l'équilibre")
        return {"tier": "🔴", "label": "passe",
                "raison": f"prix trop court: {prob:.0%} à {odds:.2f} = {value:+.1f}%{extra}"}

    nb = (model_prob is not None
          and is_no_brainer(model_prob, odds, value, aligned_net))

    if nb and value < V_FIRE:
        return {"tier": "💎", "label": "no brainer",
                "raison": (f"modèle {model_prob:.0%}, {aligned_net} facteurs alignés, "
                           f"cote {odds:.2f} ≥ {NB_MIN_ODDS} et valeur {value:+.1f}%")}

    if value >= V_FIRE:
        if odds < MIN_ODDS_ML:
            return {"tier": "🟢", "label": "solide",
                    "raison": (f"valeur {value:+.1f}% mais cote {odds:.2f} sous le "
                               f"plancher {MIN_ODDS_ML} — précision insuffisante "
                               f"pour revendiquer un favori si court")}
        if aligned_net >= 2:
            # Valeur élevée ET conviction: le meilleur cas possible, on le dit.
            suffixe = " — et no brainer" if nb else ""
            return {"tier": "🔥", "label": "meilleur bet",
                    "raison": (f"valeur {value:+.1f}% et {aligned_net} facteurs "
                               f"alignés{suffixe}")}
        return {"tier": "🟢", "label": "solide",
                "raison": f"valeur {value:+.1f}% mais facteurs peu alignés ({aligned_net})"}

    if value >= V_SOLID:
        # Pas de seuil de probabilité ici. L'ancienne version exigeait aussi
        # prob >= 55%, ce qui était incompatible avec le rétrécissement: comme
        # la probabilité finale est tirée vers un marché à ~50%, une valeur
        # positive n'arrive presque jamais avec 55%+. Résultat observé en
        # direct le 2026-08-25: tout le tableau s'écrasait en 🟡, aucun 🟢.
        # La barre d'EV (V_SOLID) est inchangée — seule l'étiquette change.
        return {"tier": "🟢", "label": "solide",
                "raison": (f"valeur {value:+.1f}% à {prob:.0%} de probabilité "
                           f"(cote {odds:.2f})")}

    return {"tier": "🟡", "label": "jouable",
            "raison": f"avantage marginal {value:+.1f}%"}


def classify_run_line(prob: float, odds: float, value: float,
                      run_diff: float, aligned_net: int) -> dict:
    """
    Le -1.5 change l'analyse: il faut un potentiel de blowout, pas juste un
    favori. On refuse explicitement le -1.5 sur un match qu'on croit serré.
    """
    if value is None:
        return {"tier": "🔴", "label": "passe", "raison": "cote indisponible"}
    if value < RL_MIN_VALUE:
        return {"tier": "🔴", "label": "passe",
                "raison": f"valeur {value:+.1f}% sous le seuil {RL_MIN_VALUE}% du -1.5"}
    if run_diff < RL_MIN_RUN_DIFF:
        return {"tier": "🔴", "label": "passe",
                "raison": (f"match trop serré: différentiel attendu "
                           f"{run_diff:+.2f} run < {RL_MIN_RUN_DIFF}")}
    if aligned_net < RL_MIN_ALIGNED:
        return {"tier": "🟡", "label": "jouable",
                "raison": (f"valeur {value:+.1f}% mais seulement {aligned_net} "
                           f"facteurs alignés (il en faut {RL_MIN_ALIGNED})")}
    return {"tier": "🔥", "label": "meilleur bet",
            "raison": (f"valeur {value:+.1f}%, différentiel {run_diff:+.2f} run, "
                       f"{aligned_net} facteurs alignés")}


# ── Orchestration ───────────────────────────────────────────────────────────

def fetch_slate(date_str: str = None) -> list:
    """
    Un seul appel au calendrier MLB donne: gamePk, IDs d'équipes, stade et
    IDs des partants probables. Les matchs sans partant annoncé (TBD) sont
    écartés — on ne modélise pas un match dont on ignore le lanceur.
    """
    if date_str is None:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
    try:
        r = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str,
                    "hydrate": "probablePitcher,venue"},
            headers=tm.HEADERS, timeout=tm.TIMEOUT,
        )
        data = r.json() if r.status_code == 200 else {}
    except Exception as e:
        print(f"  [MLB ML] Erreur calendrier: {e}")
        return []

    games, skipped = [], 0
    for d in data.get("dates", []):
        for g in d.get("games", []):
            t = g.get("teams", {})
            hp = (t.get("home") or {}).get("probablePitcher") or {}
            ap = (t.get("away") or {}).get("probablePitcher") or {}
            if not hp.get("id") or not ap.get("id"):
                skipped += 1
                continue
            games.append({
                "game_pk":    g.get("gamePk"),
                "venue":      (g.get("venue") or {}).get("name", ""),
                "commence":   g.get("gameDate", ""),
                "home_team":  ((t.get("home") or {}).get("team") or {}).get("name", ""),
                "away_team":  ((t.get("away") or {}).get("team") or {}).get("name", ""),
                "home_id":    ((t.get("home") or {}).get("team") or {}).get("id"),
                "away_id":    ((t.get("away") or {}).get("team") or {}).get("id"),
                "home_sp_id": hp.get("id"),
                "away_sp_id": ap.get("id"),
                "home_sp":    hp.get("fullName", ""),
                "away_sp":    ap.get("fullName", ""),
            })
    if skipped:
        print(f"  [MLB ML] {skipped} match(s) écarté(s): partant non annoncé")
    return games


def _build_side(team_id: int, opp_sp: dict, date_str: str) -> dict:
    """
    Rassemble tout ce qui décrit un côté du match. `opp_sp` sert à choisir le
    bon split offensif (vs droitier ou vs gaucher) — c'est là que vit
    l'avantage de platoon.
    """
    off = tm.get_team_offense(team_id, opp_sp["hand"])
    if not off:
        return None
    return {
        "team_id":    team_id,
        "off":        off,
        "off_recent": tm.get_team_offense_recent(team_id),
        "bp":         tm.get_bullpen(team_id),
        "bp_usage":   tm.get_bullpen_usage(team_id, ref_date=date_str),
        "defense":    tm.get_team_defense(team_id),
    }


def analyze_game(game: dict, odds_entry: dict = None, date_str: str = None) -> dict:
    """
    Analyse complète d'un match: probabilités moneyline et -1.5, valeur vs les
    cotes réelles, facteurs alignés, classement.

    `odds_entry` provient de MLBOddsFetcher.get_game_odds(). Sans cotes, on
    retourne quand même les probabilités mais AUCUN pari — la valeur est
    indéfinissable sans prix, et parier sans prix est exactement l'erreur que
    ce projet a déjà payée.
    """
    sp_home = tm.get_pitcher_profile(game["home_sp_id"])
    sp_away = tm.get_pitcher_profile(game["away_sp_id"])
    if not sp_home or not sp_away:
        return None

    side_home = _build_side(game["home_id"], sp_away, date_str)
    side_away = _build_side(game["away_id"], sp_home, date_str)
    if not side_home or not side_away:
        return None

    park = _park_factor(game.get("venue", ""))

    # Runs attendus: l'offense de chaque équipe contre le partant + bullpen adverse.
    er_home = expected_runs(
        side_home["off"], side_home["off_recent"], sp_away, side_away["bp"],
        side_away["bp_usage"], side_away["defense"], park, is_home=True,
    )
    er_away = expected_runs(
        side_away["off"], side_away["off_recent"], sp_home, side_home["bp"],
        side_home["bp_usage"], side_home["defense"], park, is_home=False,
    )

    probs = _win_probs(er_home["runs"], er_away["runs"])
    run_diff = round(er_home["runs"] - er_away["runs"], 3)

    # Résumés par côté pour le comptage de facteurs alignés.
    def _summ(side, own_sp, er):
        return {
            "sp_fip_eff": _effective_sp_fip(own_sp),
            "sp_k_bb":    own_sp.get("k_bb_pct"),
            "sp_k_pct":   own_sp.get("k_pct"),
            "bp_fip_eff": er["bp_fip_eff"],
            "ops_index":  side["off"]["ops_index"],
            "iso":        side["off"]["iso"],
            "k_pct":      side["off"]["k_pct"],
        }

    # Attention: er_home décrit les runs que HOME marque, donc le bullpen
    # pénalisé dedans est celui d'AWAY. Pour juger le bullpen de HOME, il faut
    # celui calculé dans er_away.
    summ_home = _summ(side_home, sp_home, er_away)
    summ_away = _summ(side_away, sp_away, er_home)

    al_home = aligned_factors(summ_home, summ_away)
    al_away = aligned_factors(summ_away, summ_home)

    out = {
        "game_pk":    game["game_pk"],
        # event_id The Odds API (vient de l'entree de cotes): la capture CLV en
        # a besoin pour retrouver ce match plus tard.
        "event_id":   (odds_entry or {}).get("event_id", ""),
        "home_team":  game["home_team"],
        "away_team":  game["away_team"],
        "venue":      game.get("venue", ""),
        "park_factor": park,
        "commence":   game.get("commence", ""),
        "starters": {
            "home": {"nom": sp_home["name"], "main": sp_home["hand"],
                     "fip": sp_home["fip"], "fip_eff": summ_home["sp_fip_eff"],
                     "k_bb_pct": sp_home["k_bb_pct"], "whip": sp_home["whip"],
                     "ip_par_depart": sp_home["ip_per_gs"],
                     "forme": sp_home.get("recent")},
            "away": {"nom": sp_away["name"], "main": sp_away["hand"],
                     "fip": sp_away["fip"], "fip_eff": summ_away["sp_fip_eff"],
                     "k_bb_pct": sp_away["k_bb_pct"], "whip": sp_away["whip"],
                     "ip_par_depart": sp_away["ip_per_gs"],
                     "forme": sp_away.get("recent")},
        },
        "runs_attendus": {"home": er_home["runs"], "away": er_away["runs"]},
        "run_diff":      run_diff,
        "bullpens": {
            "home": {"fip": (side_home["bp"] or {}).get("fip"),
                     "fip_fatigue": er_away["bp_fip_eff"],
                     "usage": side_home["bp_usage"]},
            "away": {"fip": (side_away["bp"] or {}).get("fip"),
                     "fip_fatigue": er_home["bp_fip_eff"],
                     "usage": side_away["bp_usage"]},
        },
        "offense": {
            "home": side_home["off"],
            "away": side_away["off"],
        },
        "prob_modele": {
            "home_ml": round(probs["p_a_ml"], 4),
            "away_ml": round(probs["p_b_ml"], 4),
            "home_rl": round(probs["p_a_rl"], 4),
            "away_rl": round(probs["p_b_rl"], 4),
        },
        "facteurs": {"home": al_home, "away": al_away},
        "bets": [],
    }

    if not odds_entry:
        out["note"] = "aucune cote disponible — probabilités seulement, aucun pari"
        return out

    ml_odds = odds_entry.get("ml", {})
    o_home = ml_odds.get(game["home_team"])
    o_away = ml_odds.get(game["away_team"])

    # Probabilités du marché sans la marge, puis rétrécissement.
    mkt_home, mkt_away, mkt_src = market_probs(odds_entry, game["home_team"],
                                               game["away_team"])
    p_home = blend_with_market(probs["p_a_ml"], mkt_home)
    p_away = blend_with_market(probs["p_b_ml"], mkt_away)
    # Renormaliser: les deux mélanges doivent sommer à 1.
    tot = p_home + p_away
    if tot > 0:
        p_home, p_away = p_home / tot, p_away / tot

    out["prob_marche"] = {
        "home_ml": round(mkt_home, 4) if mkt_home else None,
        "away_ml": round(mkt_away, 4) if mkt_away else None,
        "source":  mkt_src,
    }
    out["prob_finale"] = {"home_ml": round(p_home, 4), "away_ml": round(p_away, 4)}

    for team, prob, odds, al, pm in (
        (game["home_team"], p_home, o_home, al_home["net"], probs["p_a_ml"]),
        (game["away_team"], p_away, o_away, al_away["net"], probs["p_b_ml"]),
    ):
        if not odds:
            continue
        v = value_pct(prob, odds)
        cls = classify_ml(prob, odds, v, al, model_prob=pm)
        out["bets"].append({
            "marche":         "moneyline",
            "equipe":         team,
            "probabilite":    round(prob * 100, 1),
            "prob_modele":    round(pm * 100, 1),
            "cote":           odds,
            "valeur_pct":     v,
            "cote_equitable": round(1 / prob, 2) if prob > 0 else None,
            "facteurs_nets":  al,
            "no_brainer":     is_no_brainer(pm, odds, v, al),
            "tier":           cls["tier"],
            "label":          cls["label"],
            "raison":         cls["raison"],
        })

    # ── Run line -1.5 sur le favori du modèle ───────────────────────────────
    spreads = odds_entry.get("spreads", {})
    fav_team, fav_p_rl, fav_al = (
        (game["home_team"], probs["p_a_rl"], al_home["net"])
        if run_diff >= 0 else
        (game["away_team"], probs["p_b_rl"], al_away["net"])
    )
    rl_odds = (spreads.get(fav_team) or {}).get(-1.5)
    if rl_odds:
        # Le -1.5 doit être rétréci vers le marché EXACTEMENT comme le ML.
        # Sinon le même désaccord modèle/marché produit une valeur damée sur le
        # ML et une valeur brute sur le -1.5: observé en direct le 2026-08-25,
        # Giants ML +4.0% contre Giants -1.5 +27.4% sur un seul et même écart.
        # Les deux marchés devenaient incomparables et le -1.5 systématiquement
        # gonflé.
        #
        # Le +1.5 n'est pas toujours coté par le même book, donc pas de
        # dévigage à deux voies propre: on estime la probabilité du marché
        # depuis le seul prix offert, en retirant une marge typique.
        p_mkt_rl = 1.0 / (rl_odds * (1.0 + ASSUMED_VIG))
        p_rl = blend_with_market(fav_p_rl, p_mkt_rl)
        v_rl = value_pct(p_rl, rl_odds)
        cls = classify_run_line(p_rl, rl_odds, v_rl, abs(run_diff), fav_al)
        out["bets"].append({
            "marche":         "run_line_-1.5",
            "equipe":         fav_team,
            "probabilite":    round(p_rl * 100, 1),
            "prob_modele":    round(fav_p_rl * 100, 1),
            "prob_marche":    round(p_mkt_rl * 100, 1),
            "cote":           rl_odds,
            "valeur_pct":     v_rl,
            "cote_equitable": round(1 / p_rl, 2) if p_rl > 0 else None,
            "facteurs_nets":  fav_al,
            "run_diff":       abs(run_diff),
            "tier":           cls["tier"],
            "label":          cls["label"],
            "raison":         cls["raison"],
        })

    return out


TIER_RANK = {"🔥": 0, "💎": 1, "🟢": 2, "🟡": 3, "🔴": 4}


def analyze_slate(date_str: str = None, game_odds: dict = None) -> list:
    """
    Analyse tous les matchs du jour. `game_odds` = sortie de
    MLBOddsFetcher.get_game_odds(), indexée par event_id → on réapparie par
    nom d'équipe (les deux sources utilisent les noms complets MLB).
    """
    tm.load_league_context()
    games = fetch_slate(date_str)
    if not games:
        return []

    by_teams = {}
    for entry in (game_odds or {}).values():
        by_teams[(entry.get("home_team"), entry.get("away_team"))] = entry

    results = []
    for g in games:
        odds_entry = by_teams.get((g["home_team"], g["away_team"]))
        try:
            r = analyze_game(g, odds_entry, date_str)
        except Exception as e:
            print(f"  [MLB ML] {g['away_team']} @ {g['home_team']}: erreur {e}")
            continue
        if r:
            results.append(r)

    # Trier les paris de chaque match par qualité, puis les matchs par leur
    # meilleur pari — le 🔥 le plus élevé remonte en haut de la liste.
    for r in results:
        r["bets"].sort(key=lambda b: (TIER_RANK.get(b["tier"], 9),
                                      -(b["valeur_pct"] or -999)))
    results.sort(key=lambda r: (
        TIER_RANK.get(r["bets"][0]["tier"], 9) if r["bets"] else 9,
        -(r["bets"][0]["valeur_pct"] if r["bets"] and r["bets"][0]["valeur_pct"] else -999),
    ))
    return results


def format_table(results: list, only_bets: bool = True) -> str:
    """
    Rend le tableau demandé:
      Équipe | Probabilité estimée | Cote | Value | Bet
    """
    rows = []
    for r in results:
        for b in r["bets"]:
            if only_bets and b["tier"] == "🔴":
                continue
            rows.append((r, b))
    if not rows:
        return "Aucun pari retenu — aucune combinaison probabilité/cote ne passe les seuils."

    out = [f"{'Équipe':26}{'Marché':16}{'Prob':>7}{'Cote':>7}{'Value':>8}  Bet",
           "-" * 82]
    for r, b in rows:
        mk = "ML" if b["marche"] == "moneyline" else "-1.5"
        v  = f"{b['valeur_pct']:+.1f}%" if b["valeur_pct"] is not None else "n/d"
        out.append(f"{b['equipe'][:25]:26}{mk:16}{b['probabilite']:>6.1f}%"
                   f"{b['cote']:>7.2f}{v:>8}  {b['tier']} {b['label']}")
    return "\n".join(out)


def _cli():
    """
    Utilisation:
      python3 src/mlb_ml_analyzer.py              # aujourd'hui
      python3 src/mlb_ml_analyzer.py 2026-08-25   # une date précise

    Les cotes exigent ODDS_API_KEY. Sans clé, seules les probabilités du
    modèle sont affichées — aucun pari, parce que sans prix il n'y a pas de
    valeur à évaluer.
    """
    import os
    import sys

    date_str = sys.argv[1] if len(sys.argv) > 1 else None

    game_odds = {}
    key = os.environ.get("ODDS_API_KEY")
    if key:
        try:
            from mlb_odds_fetcher import MLBOddsFetcher
            game_odds = MLBOddsFetcher(key).get_game_odds()
        except Exception as e:
            print(f"Cotes indisponibles ({e}) — probabilités seulement.")
    else:
        print("ODDS_API_KEY absente — probabilités seulement, aucun pari évalué.\n")

    results = analyze_slate(date_str, game_odds)
    if not results:
        print("Aucun match modélisable.")
        return

    if game_odds:
        print()
        print(format_table(results))
        print()

    for r in results:
        print(f"── {r['away_team']} @ {r['home_team']} · {r['venue']} "
              f"(parc {r['park_factor']:.2f})")
        sh, sa = r["starters"]["home"], r["starters"]["away"]
        for lbl, s in (("away", sa), ("home", sh)):
            f = s.get("forme") or {}
            forme = (f" · forme {f['games']}dép FIP {f['fip']:.2f}"
                     if f.get("games") and f.get("fip") else "")
            print(f"     {lbl:4} {s['nom']:20} {s['main']}HP  FIP {s['fip_eff']:.2f}"
                  f"  K-BB% {s['k_bb_pct']:.1%}  {s['ip_par_depart']:.1f} MPD{forme}")
        ra, rh = r["runs_attendus"]["away"], r["runs_attendus"]["home"]
        print(f"     runs attendus: {ra:.2f} — {rh:.2f}  (diff {r['run_diff']:+.2f})")
        pm = r["prob_modele"]
        line = (f"     modèle: {r['away_team']} {pm['away_ml']:.1%}"
                f" / {r['home_team']} {pm['home_ml']:.1%}")
        if r.get("prob_finale"):
            pf = r["prob_finale"]
            line += (f"   →  après marché: {pf['away_ml']:.1%}"
                     f" / {pf['home_ml']:.1%}")
        print(line)
        for b in r["bets"]:
            mk = "ML" if b["marche"] == "moneyline" else "-1.5"
            v = f"{b['valeur_pct']:+.1f}%" if b["valeur_pct"] is not None else "n/d"
            print(f"       {b['tier']} {mk:5} {b['equipe'][:22]:23} "
                  f"{b['probabilite']:.1f}% @ {b['cote']:.2f} → {v}  ({b['raison']})")
        for side in ("home", "away"):
            fa = r["facteurs"][side]
            if fa["facteurs"]:
                signe = "+" if fa["net"] > 0 else ""
                noms = ", ".join(
                    ("✓" if f["pour"] else "✗") + f["nom"] for f in fa["facteurs"])
                print(f"     facteurs {side} ({signe}{fa['net']}): {noms}")
        print()


if __name__ == "__main__":
    _cli()
