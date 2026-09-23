"""
AI Analyst — Expert betting analysis via Claude API.
Reçoit le signal complet et retourne une analyse experte structurée.
"""

import os
import json
import re

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# Choix du 2026-09-23: Sonnet 5, appele a chaque Actualiser. Effort « medium »:
# c'est un resume du signal, pas un calcul; monter a « high » si l'analyse
# parait superficielle.
MODEL  = "claude-sonnet-5"
EFFORT = "medium"


def _format_signal_for_prompt(data: dict) -> str:
    """Formate le signal en texte lisible pour le prompt."""
    lines = []
    date = data.get("date", "")
    lines.append(f"DATE: {date}")
    lines.append("")

    # ── NHL value bets ────────────────────────────────────────────────────────
    value_bets = data.get("value_bets", [])
    if value_bets:
        lines.append("=== BETS NHL (marchés) ===")
        for b in value_bets:
            lines.append(
                f"  • {b.get('bet','')} | {b.get('game','')} | "
                f"Cote {b.get('b365_odds','')} | "
                f"Prob modèle {b.get('our_prob','')}% | "
                f"Edge +{b.get('edge_pct','')}% | "
                f"Kelly {b.get('kelly_fraction','')}%"
            )
            if b.get("note"):
                lines.append(f"    Note: {b['note']}")
        lines.append("")

    # ── NHL props ─────────────────────────────────────────────────────────────
    props = data.get("props_analysis", [])
    if props:
        lines.append("=== PROPS JOUEURS NHL ===")
        for g in props:
            match = f"{g.get('away_team','')} @ {g.get('home_team','')}"
            hg = g.get("home_goalie", {})
            ag = g.get("away_goalie", {})
            if hg or ag:
                lines.append(f"  Match: {match}")
                if hg:
                    lines.append(f"    Gardien DOM: {hg.get('name','')} SV%={hg.get('sv_pct','')} GAA={hg.get('gaa','')}")
                if ag:
                    lines.append(f"    Gardien VIS: {ag.get('name','')} SV%={ag.get('sv_pct','')} GAA={ag.get('gaa','')}")
            for b in g.get("bets", []):
                ctx = " | ".join(b.get("context_notes", b.get("context", [])) or [])
                lines.append(
                    f"  • {b.get('name','')} — {b.get('market','')} | "
                    f"Proj {b.get('points_adj') or b.get('adj_proj','')} | "
                    f"Edge +{b.get('edge_pct','')}% | {ctx}"
                )
        lines.append("")

    # ── MLB ──────────────────────────────────────────────────────────────────
    mlb = data.get("mlb_analysis", [])
    if mlb:
        lines.append("=== BETS MLB ===")
        for g in mlb:
            match = f"{g.get('away_team','')} @ {g.get('home_team','')}"
            lines.append(f"  Match: {match}")
            for b in g.get("bets", []):
                ctx = " | ".join(b.get("context", []) or [])
                lines.append(
                    f"  • {b.get('player','')} ({b.get('team','')}) — {b.get('market','')} | "
                    f"Proj {b.get('adj_proj','')} | "
                    f"Edge +{b.get('edge_pct','')}% | "
                    f"vs {b.get('opp_pitcher','')} ({b.get('opp_pitcher_k','')} K/dep) | "
                    f"{ctx}"
                )
        lines.append("")

    # ── NBA ──────────────────────────────────────────────────────────────────
    nba = data.get("nba_analysis", [])
    if nba:
        lines.append("=== BETS NBA ===")
        for g in nba:
            match = f"{g.get('away_team','')} @ {g.get('home_team','')}"
            lines.append(f"  Match: {match}")
            for b in g.get("bets", []):
                ctx = " | ".join(b.get("context", []) or [])
                lines.append(
                    f"  • {b.get('player','')} ({b.get('team','')}) — {b.get('market','')} | "
                    f"Proj {b.get('adj_proj','')} | "
                    f"Edge +{b.get('edge_pct','')}% | {ctx}"
                )
        lines.append("")

    return "\n".join(lines)


SYSTEM_PROMPT = """Tu es un analyste sportif expert en paris sportifs avec 15 ans d'expérience.
Tu analyses les signaux de valeur identifiés par un modèle quantitatif et fournis une évaluation critique.

Tes analyses sont:
- Directes et concises (pas de rembourrage)
- Basées sur les données fournies + ton expertise contextuelle
- Critiques: tu signales les risques et les failles du modèle
- Orientées action: chaque section se termine par une recommandation claire

Format de réponse STRICT (JSON uniquement, aucun texte avant ou après):
{
  "resume": "2-3 phrases sur la journée — qualité globale du signal",
  "bets": [
    {
      "bet": "nom exact du bet (ex: Shohei Ohtani Retraits au bâton Over 7.5)",
      "verdict": "JOUER" | "JOUER AVEC PRUDENCE" | "PASSER",
      "confiance": 1-5,
      "analyse": "2-3 phrases: pourquoi ce bet est fort/faible, facteurs clés",
      "risques": "1-2 risques spécifiques à surveiller",
      "suggestion": "amélioration concrète ou alternative si disponible"
    }
  ],
  "opportunites_manquees": "Bets potentiels que le modèle n'a pas identifiés mais qui méritent attention",
  "conseil_du_jour": "Un conseil actionnable pour la journée"
}"""


def run_analysis(signal_data: dict) -> dict:
    """
    Appelle Claude API et retourne l'analyse experte.
    Retourne {} si l'API n'est pas disponible.
    """
    if not HAS_ANTHROPIC:
        print("  [AI Analyst] anthropic non installé — pip install anthropic")
        return {}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  [AI Analyst] ANTHROPIC_API_KEY manquant")
        return {}

    # Vérifier qu'il y a des bets à analyser
    has_content = (
        signal_data.get("value_bets") or
        any(g.get("bets") for g in signal_data.get("props_analysis", [])) or
        any(g.get("bets") for g in signal_data.get("mlb_analysis", [])) or
        any(g.get("bets") for g in signal_data.get("mlb_ml_analysis", [])) or
        any(g.get("bets") for g in signal_data.get("nba_analysis", []))
    )
    if not has_content:
        print("  [AI Analyst] Aucun bet à analyser")
        return {"resume": "Aucun bet à valeur identifié aujourd'hui.", "bets": [], "conseil_du_jour": "Journée de repos."}

    signal_text = _format_signal_for_prompt(signal_data)

    print(f"  [AI Analyst] Appel Claude API ({MODEL})...")
    client = anthropic.Anthropic(api_key=api_key)
    try:
        message = client.messages.create(
            model=MODEL,
            # Sonnet 5 reflechit par defaut (adaptive), et la reflexion compte
            # dans max_tokens: 2000 tronquait la reponse avant le JSON.
            max_tokens=16000,
            output_config={"effort": EFFORT},
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Voici le signal de paris sportifs du jour. "
                        "Analyse chaque bet et fournis tes recommandations:\n\n"
                        + signal_text
                    ),
                }
            ],
        )
    except anthropic.AuthenticationError:
        print("  [AI Analyst] ANTHROPIC_API_KEY refusee (401) — verifier le secret du depot")
        return {}
    except anthropic.RateLimitError:
        print("  [AI Analyst] Limite de debit atteinte (429) — analyse sautee pour ce run")
        return {}
    except anthropic.APIStatusError as e:
        print(f"  [AI Analyst] Erreur API {e.status_code}: {e.message} (request {e.request_id})")
        return {}
    except anthropic.APIConnectionError as e:
        print(f"  [AI Analyst] Reseau injoignable: {e}")
        return {}

    if message.stop_reason == "refusal":
        print("  [AI Analyst] Requete declinee par le modele (refusal)")
        return {}
    if message.stop_reason == "max_tokens":
        print("  [AI Analyst] Reponse tronquee (max_tokens) — JSON probablement incomplet")

    # Le premier bloc peut etre un bloc de reflexion: on prend le texte.
    raw = "".join(b.text for b in message.content if b.type == "text").strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        print(f"  [AI Analyst] Réponse non-JSON reçue (request {message._request_id})")
        return {}
    try:
        result = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"  [AI Analyst] JSON illisible: {e}")
        return {}
    n_bets = len(result.get("bets", []))
    print(f"  [AI Analyst] Analyse complète — {n_bets} bets évalués")
    return result


if __name__ == "__main__":
    # Test avec signal.json local
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "../docs/signal.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    result = run_analysis(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
