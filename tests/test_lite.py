"""Version lite NHL: retrait de marge, cote a exiger, parsing, reglement. Aucun appel reseau."""
import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lite"))
import bets  # noqa: E402
import nhl_lite  # noqa: E402

NOW = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)


def test_devig_power_somme_a_1():
    for odds in ([1.91, 1.91], [1.50, 2.70], [1.12, 6.50], [2.0, 2.0]):
        p = nhl_lite.devig_power(odds)
        assert sum(p) == pytest.approx(1, abs=1e-9)
    # le favori garde plus que sa part proportionnelle (methode puissance)
    fav = nhl_lite.devig_power([1.12, 6.50])[0]
    assert fav > (1 / 1.12) / (1 / 1.12 + 1 / 6.50)


def test_cote_a_exiger():
    r = nhl_lite.price_row(0.5, 0.03)
    assert r["fair"] == 2.0 and r["need"] == 2.06
    assert nhl_lite.price_row(0.6, 0.0)["need"] == pytest.approx(1 / 0.6, abs=1e-3)


def test_commence_time_to_6h_et_le_lendemain():
    assert nhl_lite.commence_time_to(NOW) == "2026-10-08T10:00:00Z"  # EDT = UTC-4


def _main_event(start="2026-10-07T23:00:00Z"):
    return {"id": "e1", "commence_time": start, "away_team": "Montréal Canadiens",
            "home_team": "Toronto Maple Leafs", "bookmakers": [{"key": "pinnacle", "markets": [
                {"key": "h2h", "outcomes": [{"name": "Montréal Canadiens", "price": 2.40},
                                            {"name": "Toronto Maple Leafs", "price": 1.62}]},
                {"key": "spreads", "outcomes": [{"name": "Montréal Canadiens", "price": 1.45, "point": 1.5},
                                                {"name": "Toronto Maple Leafs", "price": 2.80, "point": -1.5}]},
                {"key": "totals", "outcomes": [{"name": "Over", "price": 1.95, "point": 6.0},
                                               {"name": "Under", "price": 1.87, "point": 6.0}]}]}]}


def test_parse_main():
    games = nhl_lite.parse_main([_main_event(), _main_event("2026-10-07T15:00:00Z")], 0.03, now=NOW)
    assert len(games) == 1  # match deja commence ignore
    g = games[0]
    assert g["date"] == "2026-10-07"
    assert [l["market"] for l in g["lines"]] == ["ML", "ML", "Puck line", "Puck line", "Total", "Total"]
    for i in (0, 2, 4):
        assert g["lines"][i]["p"] + g["lines"][i + 1]["p"] == pytest.approx(1, abs=2e-4)
    pl = g["lines"][3]
    assert pl["selection"] == "Toronto Maple Leafs" and pl["line"] == -1.5 and pl["source"] == "Pinnacle"
    assert pl["need"] == pytest.approx(1.03 / pl["p"], abs=2e-3)


def _sog_book(key, player, point, over, under):
    return {"key": key, "markets": [{"key": "player_shots_on_goal", "outcomes": [
        {"name": "Over", "description": player, "point": point, "price": over},
        {"name": "Under", "description": player, "point": point, "price": under}]}]}


def test_parse_sog_pinnacle_prioritaire():
    ev = {"bookmakers": [_sog_book("pinnacle", "Cole Caufield", 3.5, 2.10, 1.75),
                         _sog_book("draftkings", "Cole Caufield", 3.5, 1.50, 2.50)]}
    rows = nhl_lite.parse_sog(ev, 0.03)
    over = next(r for r in rows if r["selection"] == "Over")
    assert over["source"] == "Pinnacle"
    assert over["p"] == pytest.approx(nhl_lite.devig_power([2.10, 1.75])[0], abs=1e-4)
    assert sum(r["p"] for r in rows) == pytest.approx(1, abs=2e-4)


def test_parse_sog_consensus_mediane():
    ev = {"bookmakers": [
        _sog_book("pinnacle", "Cole Caufield", 3.5, 2.10, 1.75),  # autre seuil
        _sog_book("draftkings", "Cole Caufield", 2.5, 1.60, 2.30),
        _sog_book("fanduel", "Cole Caufield", 2.5, 1.70, 2.15),
        _sog_book("betmgm", "Cole Caufield", 2.5, 1.80, 2.00),
        {"key": "betrivers", "markets": [{"key": "player_shots_on_goal", "outcomes": [
            {"name": "Over", "description": "Cole Caufield", "point": 2.5, "price": 1.10}]}]},  # Over seul
    ]}
    rows = [r for r in nhl_lite.parse_sog(ev, 0.03) if r["line"] == 2.5 and r["selection"] == "Over"]
    assert len(rows) == 1
    assert rows[0]["source"] == "consensus 3 books"
    assert rows[0]["p"] == pytest.approx(nhl_lite.devig_power([1.70, 2.15])[0], abs=1e-4)


# ── Journal / reglement ──────────────────────────────────────────────────

def _payload(**kw):
    pl = {"date": "2026-10-06", "away": "Montréal Canadiens", "home": "Toronto Maple Leafs",
          "market": "ML", "selection": "Montréal Canadiens", "line": "", "odds": 2.50,
          "stake": 1, "p": 0.42, "source": "Pinnacle"}
    pl.update(kw)
    return json.dumps(pl)


SCORE = {"games": [
    {"id": 99, "gameState": "OFF",
     "awayTeam": {"name": {"default": "Canadiens"}, "score": 4},
     "homeTeam": {"name": {"default": "Maple Leafs"}, "score": 2}},
    {"id": 98, "gameState": "LIVE",
     "awayTeam": {"name": {"default": "Bruins"}, "score": 1},
     "homeTeam": {"name": {"default": "Sabres"}, "score": 0}}]}
BOX = {"playerByGameStats": {
    "awayTeam": {"forwards": [{"name": {"default": "C. Caufield"}, "sog": 5}],
                 "defense": [{"name": {"default": "L. Hutson"}, "sog": 2}]},
    "homeTeam": {"forwards": [{"name": {"default": "A. Matthews"}, "sog": 3}], "defense": []}}}


def fake_fetch(url):
    return BOX if url.endswith("/boxscore") else SCORE


def test_reglement_4_marches_et_void(tmp_path):
    path = str(tmp_path / "b.csv")
    bets.add(_payload(), path)                                                     # ML gagne
    bets.add(_payload(market="Puck line", selection="Toronto Maple Leafs", line=1.5, odds=1.9), path)  # 2-4 +1.5: perd
    bets.add(_payload(market="Total", selection="Under", line=6.0, odds=1.9), path)   # 6 = 6: void
    bets.add(_payload(market="SOG", selection="Over", line=3.5, player="Cole Caufield", odds=2.1), path)  # 5: gagne
    bets.add(_payload(market="SOG", selection="Under", line=2.5, player="Lane Hutson", odds=1.8, stake=2), path)  # 2: gagne
    bets.add(_payload(market="SOG", selection="Over", line=1.5, player="Juraj Slafkovsky"), path)  # absent: void
    bets.add(_payload(away="Boston Bruins", home="Buffalo Sabres", selection="Boston Bruins"), path)  # LIVE: attente
    assert bets.grade(path, fetch=fake_fetch) == 6
    res = {(r["market"], r["player"] or r["selection"]): (r["status"], float(r["profit"] or 0))
           for r in bets.load(path)}
    assert res[("ML", "Montréal Canadiens")] == ("win", 1.5)
    assert res[("Puck line", "Toronto Maple Leafs")] == ("loss", -1.0)
    assert res[("Total", "Under")] == ("void", 0.0)
    assert res[("SOG", "Cole Caufield")] == ("win", 1.1)
    assert res[("SOG", "Lane Hutson")] == ("win", 1.6)
    assert res[("SOG", "Juraj Slafkovsky")] == ("void", 0.0)
    assert res[("ML", "Boston Bruins")] == ("pending", 0.0)

    out = str(tmp_path / "bets.json")
    s = bets.stats(path, out)["total"]
    assert s["record"] == "3-1-2" and s["pending"] == 1
    assert s["profit"] == pytest.approx(3.2)
    assert s["roi"] == pytest.approx(3.2 / 5)
    assert set(json.load(open(out))["by_market"]) == {"ML", "Puck line", "Total", "SOG"}


def test_puck_line_favori_moins_1_5():
    row = {"market": "Puck line", "selection": "Montréal Canadiens", "line": "-1.5",
           "away": "Montréal Canadiens", "home": "Toronto Maple Leafs", "player": ""}
    assert bets.settle(row, SCORE["games"][0]) == "win"  # 4-2


def test_resaisie_remplace(tmp_path):
    path = str(tmp_path / "b.csv")
    bets.add(_payload(odds=2.4), path)
    bets.add(_payload(odds=2.55, stake=2), path)
    rows = bets.load(path)
    assert len(rows) == 1 and rows[0]["odds"] == "2.55" and rows[0]["stake"] == "2.0"


@pytest.mark.parametrize("kw", [
    {"odds": 1.0}, {"odds": 51}, {"stake": 0}, {"stake": 11}, {"market": "Props"},
    {"market": "Total", "selection": "Over", "line": ""},
    {"market": "SOG", "selection": "Over", "line": 2.5, "player": ""},
    {"market": "Total", "selection": "Montréal Canadiens", "line": 6.0},
    {"date": "07/10/2026"}, {"home": ""},
])
def test_saisies_invalides(tmp_path, kw):
    with pytest.raises(ValueError):
        bets.add(_payload(**kw), str(tmp_path / "b.csv"))
    assert not os.path.exists(str(tmp_path / "b.csv"))


def test_team_match():
    assert bets.team_match("Canadiens", "Montréal Canadiens")
    assert bets.team_match("Blues", "St Louis Blues")
    assert not bets.team_match("Blues", "Columbus Blue Jackets")
    assert not bets.team_match("Jets", "Columbus Blue Jackets")
