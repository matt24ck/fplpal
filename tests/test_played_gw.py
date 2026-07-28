"""Played-GW ingest: schema identity with the archive, idempotency, DGW
safety, and the pre-season clean no-op — all on synthetic payloads (no data
volume, no network)."""

from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import pytest
from synthetic import (
    ARCHIVE_DTYPES,
    BOOTSTRAP,
    FIXTURES,
    SUMMARIES,
    base_table,
    live_payload,
)

from engine.features.historical_gw import CANONICAL
from engine.ingest.played_gw import (
    append_rows,
    build_played_rows,
    finished_fixture_ids,
    validate_vs_live,
)

DONE = {101, 102, 103}


def test_pre_season_is_a_clean_noop():
    fresh = copy.deepcopy(BOOTSTRAP)
    for e in fresh["events"]:
        e["finished"] = e["data_checked"] = False
    fixtures = [{**f, "finished": False} for f in FIXTURES]
    assert finished_fixture_ids(fresh, fixtures) == set()


def test_only_data_checked_events_and_finished_fixtures_count():
    assert finished_fixture_ids(BOOTSTRAP, FIXTURES) == DONE  # event 2 excluded

    provisional = copy.deepcopy(BOOTSTRAP)
    provisional["events"][0]["data_checked"] = False  # finished but not confirmed
    assert finished_fixture_ids(provisional, FIXTURES) == set()

    postponed = [{**f, "finished": False} if f["id"] == 103 else f for f in FIXTURES]
    assert finished_fixture_ids(BOOTSTRAP, postponed) == {101, 102}


def test_rows_are_canonical_and_dgw_safe():
    rows = build_played_rows(BOOTSTRAP, FIXTURES, SUMMARIES, DONE)

    assert list(rows.columns) == CANONICAL
    # one row per player per fixture: DGW players get two rows
    assert len(rows) == 7
    assert rows.groupby("element")["fixture"].count().loc[12] == 2
    assert rows.groupby("element")["fixture"].count().loc[13] == 2
    # assistant-manager rows dropped, unused sub kept (minutes 0)
    assert 14 not in set(rows["element"])
    bench = rows[rows["element"] == 15].iloc[0]
    assert bench["minutes"] == 0 and bench["starts"] == 0
    # live team name aliased to the archive identity
    assert set(rows.loc[rows["element"] == 13, "team"]) == {"Ipswich"}
    assert bench["opponent"] == "Ipswich"
    # own team derived from the fixture side, not bootstrap
    away_leg = rows[(rows["element"] == 12) & (rows["fixture"] == 101)].iloc[0]
    assert away_leg["team_id"] == 2 and not away_leg["was_home"]
    # API string-floats became numbers; count fields are the raw counts
    assert float(rows["xg"].max()) == pytest.approx(0.12)
    assert int(rows.loc[rows["element"] == 11, "defensive_contribution"].iloc[0]) == 6


def test_dc_points_shape_is_rejected():
    tampered = copy.deepcopy(SUMMARIES)
    # awarded-points shape (0/2) instead of the raw CBIT count
    tampered[11]["history"][0]["defensive_contribution"] = 2
    with pytest.raises(ValueError, match="CBIT/CBIRT"):
        build_played_rows(BOOTSTRAP, FIXTURES, tampered, DONE)


def test_live_total_points_cross_check():
    rows = build_played_rows(BOOTSTRAP, FIXTURES, SUMMARIES, DONE)
    validate_vs_live(rows, live_payload(SUMMARIES))  # agreeing payload passes

    wrong = live_payload(SUMMARIES)
    wrong[1]["elements"][0]["stats"]["total_points"] += 1
    with pytest.raises(ValueError, match="total_points disagree"):
        validate_vs_live(rows, wrong)


def _seed(tmp_path: Path) -> Path:
    table = tmp_path / "player_gw.parquet"
    base_table().to_parquet(table, index=False)
    return table


def test_append_schema_identity_with_archive(tmp_path: Path):
    table = _seed(tmp_path)
    rows = build_played_rows(BOOTSTRAP, FIXTURES, SUMMARIES, DONE)
    append_rows(table, rows)

    out = pd.read_parquet(table)
    assert list(out.columns) == CANONICAL
    assert {c: str(t) for c, t in out.dtypes.items()} == ARCHIVE_DTYPES
    assert len(out) == 1 + 7  # base row intact
    assert not out.duplicated(["season", "element", "fixture"]).any()
    assert set(out["season"]) == {"2025-26", "2026-27"}


def test_append_is_idempotent(tmp_path: Path):
    table = _seed(tmp_path)
    rows = build_played_rows(BOOTSTRAP, FIXTURES, SUMMARIES, DONE)
    append_rows(table, rows)
    n_first = len(pd.read_parquet(table))
    append_rows(table, rows)  # re-run: replaces, never duplicates
    assert len(pd.read_parquet(table)) == n_first


def test_partial_gw_picked_up_by_later_run(tmp_path: Path):
    table = _seed(tmp_path)
    # run 1: only fixture 101 was finished (102/103 postponed mid-GW)
    append_rows(table, build_played_rows(BOOTSTRAP, FIXTURES, SUMMARIES, {101}))
    have = set(pd.read_parquet(table).query("season == '2026-27'")["fixture"].tolist())
    assert have == {101}
    # run 2: ingestion is keyed on fixtures — only the missing ones are new
    todo = DONE - have
    assert todo == {102, 103}
    append_rows(table, build_played_rows(BOOTSTRAP, FIXTURES, SUMMARIES, todo))
    out = pd.read_parquet(table)
    assert set(out.query("season == '2026-27'")["fixture"]) == DONE
    assert len(out) == 1 + 7
    assert not out.duplicated(["season", "element", "fixture"]).any()


REAL_ARCHIVE = Path(__file__).resolve().parents[1] / "data" / "features" / "player_gw.parquet"


@pytest.mark.skipif(not REAL_ARCHIVE.exists(), reason="data volume not present")
def test_recorded_dtypes_match_real_archive():
    real = pd.read_parquet(REAL_ARCHIVE)
    assert list(real.columns) == CANONICAL
    assert {c: str(t) for c, t in real.dtypes.items()} == ARCHIVE_DTYPES
