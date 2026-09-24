"""
Version unique des modeles — ecrite dans chaque ligne de data/predictions.csv
(colonne version_modele).

REGLE: tout changement de modele (parametre, formule, source de donnees qui
change les probabilites) incremente MODEL_VERSION et ajoute une ligne au
CHANGELOG. Le test tests/test_model_version.py calcule une empreinte des
parametres (fingerprint()) et echoue si elle ne correspond plus a
FINGERPRINT: on ne peut pas changer un parametre sans incrementer la version.

Format: AAAA.MM.JJ.n (n = numero du changement dans la journee).
"""
from __future__ import annotations

import hashlib
import json

MODEL_VERSION = "2026.09.24.3"

CHANGELOG = [
    ("2026.09.23.1", "K: binomiale negative (c=0.926, r=56.9), calibration par barreau; "
                     "NFL: reference Pinnacle Shin; LNH: lignes du modele Poisson"),
    ("2026.09.24.1", "Version unique pour tous les marches (auparavant une etiquette par source)"),
    ("2026.09.24.2", "Melange modele-marche avant l'edge et la mise, w=0.3 par defaut "
                     "(MLB ML: 0.35 -> 0.30); props K et LNH melanges avec la reference no-vig"),
    ("2026.09.24.3", "Mises: Kelly 0.25 sur p_final, 1.5% par pari, 3% par soir; seuil LNH "
                     "saisi a la main 15% -> 3% (coherent avec « > 8% = A VERIFIER »)"),
]

# Empreinte des parametres a la version courante. A mettre a jour AVEC la
# version: python3 -c "import model_version as m; print(m.fingerprint())"
FINGERPRINT = "7917affd697f"


def parameters() -> dict:
    """Parametres qui changent les probabilites publiees, par modele."""
    import mlb_k_distribution as KD
    import edge_calculator as EC
    import betting_config as BC
    cfg = BC.load()
    return {
        "k": {"mu": KD.K_MU_FACTOR, "r": KD.K_NB_R},
        "blend_w": cfg.get("BLEND_W"),
        "nhl": {"min_edge": EC.MIN_EDGE_PCT, "manual_edge": EC.MANUAL_EDGE_PCT},
        "staking": cfg.get("STAKING"),
        "devig": cfg["DEVIG_METHOD"],
        "reference": cfg["REFERENCE_BOOK"],
    }


def fingerprint() -> str:
    blob = json.dumps(parameters(), sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]
