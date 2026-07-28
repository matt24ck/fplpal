"""Backtest harness: season configs and metric helpers (CI-safe, no data)."""

from __future__ import annotations

import pandas as pd

from backtest.harness import add_baselines, captain_quality, metric_suite
from engine.config.season import load_season


def test_historical_season_configs_load():
    for season in ("2023-24", "2024-25", "2025-26", "2026-27"):
        rules = load_season(season)
        assert rules.season == season
        assert rules.squad.size == 15
    # defensive contribution only scores from 2025-26
    assert load_season("2023-24").scoring.defensive_contribution.points == 0
    assert load_season("2024-25").scoring.defensive_contribution.points == 0
    assert load_season("2025-26").scoring.defensive_contribution.points == 2
    assert load_season("2026-27").scoring.defensive_contribution.points == 2


def _proj() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Two GWs, one position, 16 players — big enough for the rank/top-k
    helpers' cell minimums.

    Player 1 scores 2 then 10; the point-in-time form baseline for GW2 must
    therefore be 2 (never 10 — that would be lookahead)."""

    def pts_for(el: int, gw: int) -> int:
        if el == 1:
            return 2 if gw == 1 else 10
        if el == 2:
            return 5
        return 1 if el < 16 else 0

    rows = []
    for gw, fixture in ((1, 101), (2, 201)):
        for el in range(1, 17):
            rows.append(
                {
                    "season": "2025-26",
                    "gw": gw,
                    "fixture": fixture,
                    "kickoff_time": pd.Timestamp(f"2026-08-{20 + gw}T14:00:00Z"),
                    "element": el,
                    "code": 9000 + el,
                    "position": "MID",
                    "team": "Alpha",
                    "minutes": 90 if el < 16 else 0,
                    "starts": 1 if el < 16 else 0,
                    "clean_sheets": 0,
                    "p_cs": 0.3,
                    "p_start": 0.9 if el < 16 else 0.1,
                    "xpts": float(17 - el),  # player 1 is the model's top pick
                    "total_points": pts_for(el, gw),
                }
            )
    proj = pd.DataFrame(rows)
    pg = proj[["season", "gw", "fixture", "kickoff_time", "element", "total_points"]].copy()
    return proj, pg


def test_baselines_are_point_in_time():
    proj, pg = _proj()
    out = add_baselines(proj, pg)
    gw1 = out[out["gw"] == 1]
    assert (gw1["form4"] == 0).all() and (gw1["ppg"] == 0).all()  # cold start
    p1_gw2 = out[(out["gw"] == 2) & (out["element"] == 1)].iloc[0]
    assert p1_gw2["form4"] == 2.0  # only the GW1 score — no lookahead
    assert p1_gw2["ppg"] == 2.0


def test_captain_quality_prefers_model_pick():
    proj, pg = _proj()
    out = add_baselines(proj, pg)
    cq = captain_quality(out)
    # model captains element 1 (top xpts) both weeks: (2 + 10) / 2
    assert cq["captain_pts_per_gw"] == 6.0
    assert cq["captain_pts_hindsight_best"] == 7.5  # GW1 best is element 2's 5


def test_metric_suite_shape():
    proj, pg = _proj()
    m = metric_suite(add_baselines(proj, pg))
    assert m["rows"] == 32 and m["played_rows"] == 30
    assert set(m["rmse"]) == {"model", "form4", "ppg"}
    assert -1 <= m["rank_corr_played"]["model"] <= 1
    assert 0 <= m["top10_overlap"]["model"] <= 1
    assert m["start_brier"] is not None
