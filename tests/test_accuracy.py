"""Live accuracy monitoring: deadline-gated freezing, scoring against
realized rows (DGW collapse, postponed-fixture disclosure, ep_next horizon
gating), and report idempotency — all on synthetic frames in tmp dirs (no
data volume, no network)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from engine.accuracy import freeze_projections, score_accuracy
from engine.ingest.snapshot import save_snapshot

SEASON = "2026-27"
DEADLINES = {
    1: "2026-08-21T17:30:00Z",
    2: "2026-08-28T17:30:00Z",
    3: "2026-09-04T17:30:00Z",
}
BEFORE_ALL = pd.Timestamp("2026-08-20T02:30:00Z")
AFTER_GW1 = pd.Timestamp("2026-08-27T02:30:00Z")  # GW1 played, GW2 still ahead

# element -> (code, position, fixture(s), xpts per fixture, ep_next)
# Fixtures 101/102 get played; 103 is postponed out of GW1 and never matches.
GW1_PLAYERS = {
    1: (1001, "MID", [101], [2.0], "1.5"),
    2: (1002, "MID", [101], [3.0], "2.5"),
    3: (1003, "MID", [101], [4.0], "3.5"),
    4: (1004, "MID", [102], [5.0], "4.5"),
    5: (1005, "MID", [102], [6.0], "5.5"),
    6: (1006, "MID", [102], [7.0], "6.5"),
    7: (1007, "MID", [102], [3.5], "2.0"),
    8: (1008, "MID", [101, 102], [4.0, 4.5], "9.0"),  # double gameweek
    9: (1009, "DEF", [101], [4.2], "4.0"),
    10: (1010, "MID", [102], [2.5], "1.0"),
    11: (1011, "FWD", [103], [5.0], "5.0"),  # postponed fixture
}
# realized: element -> (points per fixture, minutes per fixture)
GW1_ACTUALS = {
    1: ([6], [90]),
    2: ([2], [90]),
    3: ([5], [67]),
    4: ([2], [90]),
    5: ([9], [90]),
    6: ([2], [58]),
    7: ([0], [0]),  # projected but did not play
    8: ([4, 10], [90, 76]),
    9: ([7], [90]),  # DEF, clean sheet
    10: ([1], [80]),
}


def bootstrap(next_event: int) -> dict:
    return {
        "events": [
            {"id": gw, "deadline_time": dl, "is_next": gw == next_event}
            for gw, dl in DEADLINES.items()
        ],
        "elements": [{"id": el, "ep_next": ep} for el, (_, _, _, _, ep) in GW1_PLAYERS.items()],
    }


def projection_frame() -> pd.DataFrame:
    rows = []
    for el, (code, pos, fixtures, xpts, _) in GW1_PLAYERS.items():
        for fixture, xp in zip(fixtures, xpts):
            rows.append(
                {
                    "season": SEASON,
                    "gw": 1,
                    "fixture": fixture,
                    "element": el,
                    "code": code,
                    "player": f"Player {el}",
                    "team": "Alpha" if fixture == 101 else "Gamma",
                    "position": pos,
                    "price": 60,
                    "xpts": xp,
                    "p_cs": 0.4,
                    "p_start": 0.9,
                    "data_snapshot": "20260820T020000Z",
                    "computed_at": "2026-08-20T02:05:00Z",
                }  # fmt: skip
            )
    df = pd.DataFrame(rows)
    # GW2/GW3 windows: same pool, one fixture each, shifted ids
    for gw, bump in ((2, 100), (3, 200)):
        d = df[df["fixture"].isin([101, 102])].drop_duplicates("element").copy()
        d["gw"] = gw
        d["fixture"] = d["fixture"] + bump
        df = pd.concat([df, d], ignore_index=True)
    return df


def realized_frame() -> pd.DataFrame:
    rows = []
    for el, (points, minutes) in GW1_ACTUALS.items():
        code, pos, fixtures, _, _ = GW1_PLAYERS[el]
        for fixture, pts_f, min_f in zip(fixtures[: len(points)], points, minutes):
            rows.append(
                {
                    "season": SEASON,
                    "gw": 1,
                    "fixture": fixture,
                    "element": el,
                    "kickoff_time": pd.Timestamp("2026-08-22T14:00:00Z"),
                    "total_points": pts_f,
                    "minutes": min_f,
                    "clean_sheets": 1 if el == 9 else 0,
                    "starts": 1 if min_f >= 60 else 0,
                }  # fmt: skip
            )
    # GW2 realized for the same pool (fixture ids +100): points = element id,
    # so realized ranks vary and rank metrics stay defined
    for el in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
        _, _, fixtures, _, _ = GW1_PLAYERS[el]
        rows.append(
            {
                "season": SEASON,
                "gw": 2,
                "fixture": fixtures[0] + 100,
                "element": el,
                "kickoff_time": pd.Timestamp("2026-08-29T14:00:00Z"),
                "total_points": el,
                "minutes": 90,
                "clean_sheets": 0,
                "starts": 1,
            }  # fmt: skip
        )
    return pd.DataFrame(rows)


@pytest.fixture()
def dirs(tmp_path):
    live, acc, snaps, features = (
        tmp_path / "live", tmp_path / "accuracy", tmp_path / "snapshots", tmp_path / "features",
    )  # fmt: skip
    live.mkdir()
    features.mkdir()
    projection_frame().to_parquet(live / "projections_fixture.parquet", index=False)
    save_snapshot("bootstrap_static", bootstrap(next_event=1), snaps)
    return {"live": live, "acc": acc, "snaps": snaps, "features": features}


def freeze(dirs, now):
    return freeze_projections(
        live_dir=dirs["live"], acc_dir=dirs["acc"], snapshot_root=dirs["snaps"], now=now
    )


def test_freeze_only_future_deadlines_and_never_after(dirs):
    assert freeze(dirs, now=BEFORE_ALL) == [1, 2, 3]
    gw1 = pd.read_parquet(dirs["acc"] / "frozen" / "gw1.parquet")
    assert gw1["ep_next"].notna().all()
    assert float(gw1.loc[gw1["element"] == 8, "ep_next"].iloc[0]) == 9.0
    assert (gw1["ep_next_event"] == 1).all()
    assert gw1["deadline_time"].iloc[0] == DEADLINES[1]

    # after GW1's deadline a changed pipeline output must not touch gw1
    tampered = projection_frame()
    tampered["xpts"] = 99.0
    tampered.to_parquet(dirs["live"] / "projections_fixture.parquet", index=False)
    save_snapshot("bootstrap_static", bootstrap(next_event=2), dirs["snaps"])
    assert freeze(dirs, now=AFTER_GW1) == [2, 3]
    gw1_again = pd.read_parquet(dirs["acc"] / "frozen" / "gw1.parquet")
    assert float(gw1_again["xpts"].max()) < 99.0
    gw2 = pd.read_parquet(dirs["acc"] / "frozen" / "gw2.parquet")
    assert (gw2["xpts"] == 99.0).all() and (gw2["ep_next_event"] == 2).all()


def test_freeze_without_snapshot_or_projections_is_a_noop(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    assert freeze_projections(live_dir=live, acc_dir=tmp_path / "a", snapshot_root=tmp_path) == []
    projection_frame().to_parquet(live / "projections_fixture.parquet", index=False)
    assert freeze_projections(live_dir=live, acc_dir=tmp_path / "a", snapshot_root=tmp_path) == []
    assert not (tmp_path / "a" / "frozen").exists()


def test_pre_season_report_is_all_pending(dirs):
    freeze(dirs, now=BEFORE_ALL)
    report = score_accuracy(features_dir=dirs["features"], acc_dir=dirs["acc"])
    assert report["gws"] == [] and report["aggregate"] is None
    assert [p["gw"] for p in report["pending"]] == [1, 2, 3]
    assert report["pending"][0]["deadline_time"] == DEADLINES[1]
    assert json.loads((dirs["acc"] / "accuracy.json").read_text())["season"] == SEASON


def scored_dirs(dirs):
    """Freeze GW1 pre-deadline, re-freeze GW2 once GW1 is next-done (so its
    ep_next horizon is honest), land realized GW1+GW2 rows."""
    freeze(dirs, now=BEFORE_ALL)
    save_snapshot("bootstrap_static", bootstrap(next_event=2), dirs["snaps"])
    freeze(dirs, now=AFTER_GW1)
    realized_frame().to_parquet(dirs["features"] / "player_gw.parquet", index=False)
    return score_accuracy(features_dir=dirs["features"], acc_dir=dirs["acc"])


def test_scoring_matches_hand_computation(dirs):
    report = scored_dirs(dirs)
    assert [e["gw"] for e in report["gws"]] == [1, 2]
    assert [p["gw"] for p in report["pending"]] == [3]
    gw1 = report["gws"][0]

    # the postponed fixture is disclosed, its players excluded
    assert gw1["fixtures_frozen"] == 3 and gw1["fixtures_scored"] == 2
    assert gw1["players"] == 10 and gw1["played"] == 9

    # player-level frame: DGW element 8 collapses to xpts 8.5 vs 14 points
    xpts = {el: sum(GW1_PLAYERS[el][3]) for el in GW1_ACTUALS}
    actual = {el: sum(GW1_ACTUALS[el][0]) for el in GW1_ACTUALS}
    rmse = float(np.sqrt(np.mean([(xpts[e] - actual[e]) ** 2 for e in GW1_ACTUALS])))
    assert gw1["model"]["rmse"] == pytest.approx(rmse, abs=1e-3)

    # captain: model's top xPts is the DGW player (8.5) who returned 14;
    # ep_next agrees (9.0); hindsight best is also element 8
    assert gw1["captain"]["model"] == {"player": "Player 8", "points": 14}
    assert gw1["captain"]["ep_next"] == {"player": "Player 8", "points": 14}
    assert gw1["captain"]["hindsight"]["points"] == 14

    # clean-sheet Brier: the only 60+ GKP/DEF row is element 9 (CS kept):
    # one team cell, (0.4 - 1)^2
    assert gw1["cs_brier"] == pytest.approx((0.4 - 1.0) ** 2, abs=1e-4)
    # start Brier over the matched fixture rows (starts = played 60+)
    starts = [1 if m >= 60 else 0 for el in GW1_ACTUALS for m in GW1_ACTUALS[el][1]]
    assert gw1["start_brier"] == pytest.approx(
        float(np.mean([(0.9 - s) ** 2 for s in starts])), abs=1e-4
    )
    assert gw1["xpts_total_ratio"] == pytest.approx(
        sum(xpts.values()) / sum(actual.values()), abs=1e-3
    )

    # 8 played MIDs -> within-position Spearman exists; ep baseline scored too
    assert gw1["model"]["rank_corr"] is not None
    assert gw1["ep_next"]["rank_corr"] is not None
    # form entering GW1 is all zeros -> degenerate, no rank signal
    assert gw1["form4"]["rank_corr"] is None


def test_gw2_form_baseline_and_ep_horizon(dirs):
    report = scored_dirs(dirs)
    gw2 = report["gws"][1]
    # GW2 was re-frozen when it was the next event -> ep_next valid
    assert gw2["ep_next"]["rmse"] is not None

    detail = pd.read_parquet(dirs["acc"] / "player_detail.parquet")
    d2 = detail[detail["gw"] == 2].set_index("code")
    # form entering GW2 = mean of GW1 fixture rows: element 8 played twice
    assert d2.loc[1008, "form4"] == pytest.approx(7.0)  # (4 + 10) / 2
    assert d2.loc[1001, "form4"] == pytest.approx(6.0)
    assert d2.loc[1011, "form4"] == pytest.approx(0.0) if 1011 in d2.index else True

    agg = report["aggregate"]
    assert agg["gws_scored"] == 2
    assert agg["beat_ep_next_rank_corr"]["of"] == 2
    assert agg["captain_pts_per_gw"]["hindsight"] >= agg["captain_pts_per_gw"]["model"]


def test_stale_ep_horizon_is_not_scored(dirs):
    # freeze everything only pre-season: GW2's ep_next then belongs to GW1's
    # horizon and must be refused as a baseline
    freeze(dirs, now=BEFORE_ALL)
    realized_frame().to_parquet(dirs["features"] / "player_gw.parquet", index=False)
    report = score_accuracy(features_dir=dirs["features"], acc_dir=dirs["acc"])
    gw2 = report["gws"][1]
    assert gw2["ep_next"] == {"rmse": None, "mae": None, "rank_corr": None, "top10_overlap": None}
    assert gw2["captain"]["ep_next"] is None
    detail = pd.read_parquet(dirs["acc"] / "player_detail.parquet")
    assert detail.loc[detail["gw"] == 2, "ep_next"].isna().all()


def test_rescoring_is_idempotent(dirs):
    first = scored_dirs(dirs)
    second = score_accuracy(features_dir=dirs["features"], acc_dir=dirs["acc"])
    first.pop("scored_at"), second.pop("scored_at")
    assert first == second
