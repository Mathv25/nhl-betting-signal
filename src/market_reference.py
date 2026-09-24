"""
Probabilite de reference du marche, commune a tous les sports.

Pinnacle devigge (config DEVIG_METHOD, Shin par defaut), sinon la mediane
no-vig des books sharp (SHARP_BOOKS), sinon rien. On devigge DANS un book,
jamais entre deux books; les exchanges sont ignores. Extrait de
nfl_analyzer (2026-09-24) pour servir aussi la LNH et le melange
modele-marche (blend.py).
"""
from __future__ import annotations

import betting_config
import odds_api


def reference_pair(per_book: dict, side_a: str, side_b: str, method: str = None) -> dict:
    """
    Probabilites justes d'un marche a deux issues + la cote chez mes books.

    `per_book` = {book: {issue: cote}}. Retourne
        {side_a: p, side_b: 1 - p, source, n_books, ref_books, mine: {issue: (cote, book)}}
    ou {} s'il n'y a pas de reference (ni Pinnacle ni book sharp cotant les
    deux faces). On devigge DANS un book, jamais entre deux books.
    """
    cfg    = betting_config.load()
    method = method or cfg["DEVIG_METHOD"]

    def p_of(book):
        pr = per_book.get(book) or {}
        oa, ob = pr.get(side_a), pr.get(side_b)
        if not (oa and ob) or betting_config.is_exchange(book):
            return None
        d = odds_api.devig([oa, ob], method)
        return d[0] if d else None

    ref = cfg["REFERENCE_BOOK"]
    p_a = p_of(ref)
    if p_a is not None:
        source, used = f"{ref} ({method})", [ref]
    else:
        vals = [(bk, p_of(bk)) for bk in cfg["SHARP_BOOKS"]]
        vals = [(bk, v) for bk, v in vals if v is not None]
        if not vals:
            return {}
        ordered = sorted(v for _, v in vals)
        mid = len(ordered) // 2
        p_a = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        used = [bk for bk, _ in vals]
        source = f"mediane sharp {method} ({', '.join(used)})"

    mine = {}
    for side in (side_a, side_b):
        prices = [(bk, pr.get(side)) for bk, pr in per_book.items()
                  if pr.get(side) and not betting_config.is_exchange(bk)]
        m_odds, m_book = odds_api.best_at_my_books(prices)
        if m_odds:
            mine[side] = (m_odds, m_book)

    return {
        side_a:      round(p_a, 6),
        side_b:      round(1.0 - p_a, 6),
        "source":    source,
        "n_books":   len(used),
        "ref_books": used,
        "mine":      mine,
    }


def per_book_from_event(event: dict, market_key: str, point=None) -> dict:
    """
    {book: {issue: cote}} d'un evenement The Odds API pour un marche.
    `point`: pour spreads/totals, ne garde que les issues a ce point (valeur
    absolue pour les spreads, dont les deux faces portent des signes opposes).
    """
    out = {}
    for bm in event.get("bookmakers", []):
        for mkt in bm.get("markets", []):
            if mkt.get("key") != market_key:
                continue
            for oc in mkt.get("outcomes", []):
                pt = oc.get("point")
                if point is not None:
                    if pt is None:
                        continue
                    ref = abs(float(pt)) if market_key == "spreads" else float(pt)
                    if abs(ref - point) > 1e-6:
                        continue
                name = oc.get("name", "")
                if market_key == "spreads" and pt is not None:
                    name = f"{name} {float(pt):+g}"
                if name and oc.get("price"):
                    out.setdefault(bm.get("key", ""), {})[name] = oc["price"]
    return out
