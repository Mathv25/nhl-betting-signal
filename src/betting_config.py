"""
Reglages des books — config/betting.json.

Un seul reglage fait foi pour « ou puis-je miser »: ALLOWED_BOOKS. Il remplace
la variable d'environnement MY_BOOKS (retiree le 2026-09-23). Tout signal dont
le prix ne vient pas d'un de ces books n'est qu'une information.

  ALLOWED_BOOKS     books ou un signal peut etre « a miser »
  REFERENCE_BOOK    book de reference pour la probabilite juste (Pinnacle)
  SHARP_BOOKS       repli si la reference est absente: mediane no-vig de ces
                    books. Attention: circa n'est pas dans The Odds API.
  EXCHANGES         jamais utilises, ni comme prix ni comme reference
  DEVIG_METHOD      "shin" (defaut), "power" ou "multiplicative"
  SUSPECT_EDGE_PCT  au-dela, « A VERIFIER (prix suspect) », jamais « a miser »
"""
from __future__ import annotations

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULTS = {
    "ALLOWED_BOOKS":    ["bet365"],
    "REFERENCE_BOOK":   "pinnacle",
    "SHARP_BOOKS":      ["circa", "lowvig", "betonlineag"],
    "EXCHANGES":        ["smarkets", "matchbook", "betfair_ex_uk", "betfair_ex_eu", "betfair_ex_au"],
    "DEVIG_METHOD":     "shin",
    "SUSPECT_EDGE_PCT": 8.0,
}

_cache = None


def path() -> str:
    return os.environ.get("BETTING_CONFIG") or os.path.join(_HERE, "..", "config", "betting.json")


def load() -> dict:
    global _cache
    if _cache is None:
        cfg = dict(DEFAULTS)
        try:
            with open(path(), encoding="utf-8") as f:
                cfg.update({k: v for k, v in json.load(f).items() if not k.startswith("_")})
        except (OSError, ValueError):
            pass
        for key in ("ALLOWED_BOOKS", "SHARP_BOOKS", "EXCHANGES"):
            cfg[key] = [str(b).strip().lower() for b in cfg.get(key) or [] if str(b).strip()]
        cfg["REFERENCE_BOOK"] = str(cfg.get("REFERENCE_BOOK") or "").lower()
        _cache = cfg
    return _cache


def reset() -> None:
    global _cache
    _cache = None


def allowed_books() -> list:
    return load()["ALLOWED_BOOKS"]


def is_exchange(book: str) -> bool:
    b = (book or "").lower()
    return b in load()["EXCHANGES"] or b.startswith("betfair_ex")


def suspect_edge_pct() -> float:
    return float(load()["SUSPECT_EDGE_PCT"])
