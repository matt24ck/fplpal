"""Cheap CI smoke: engine modules import and pure functions work with no data
volume, no network, and no credentials."""

from __future__ import annotations

from fastapi.testclient import TestClient
from synthetic import BOOTSTRAP, FIXTURES

from engine.config.season import load_season
from engine.features.historical_gw import CANONICAL, FLOAT_COLS, INT_COLS, NULLABLE_INT_COLS
from engine.ingest.played_gw import HISTORY_FIELDS


def test_season_config_loads_and_validates():
    rules = load_season("2026-27")
    assert rules.squad.size == 15
    assert sum(rules.squad.positions.values()) == 15
    assert set(rules.scoring.defensive_contribution.threshold) >= {"DEF", "MID", "FWD"}


def test_canonical_schema_is_consistent():
    assert len(CANONICAL) == len(set(CANONICAL))
    stat_cols = [*NULLABLE_INT_COLS, *INT_COLS, *FLOAT_COLS]
    assert len(stat_cols) == len(set(stat_cols))
    assert set(stat_cols) < set(CANONICAL)


def test_played_ingest_covers_every_stat_column():
    # every stat column the canonical table carries has an API source field
    assert set(HISTORY_FIELDS) == {*NULLABLE_INT_COLS, *INT_COLS, *FLOAT_COLS}


def test_pipeline_builds_future_rows_from_bootstrap():
    from engine.pipeline import build_future_rows

    future, avail = build_future_rows(BOOTSTRAP, FIXTURES, horizon=1)
    assert list(future.columns) == CANONICAL
    # next event is GW2 with one fixture: teams 1 and 4, AM element dropped
    assert set(future["gw"]) == {2}
    assert set(future["element"]) == {10, 11, 15}
    assert future["minutes"].eq(0).all()  # cold-start shape: no stats yet
    assert avail[10] == 1.0


def test_api_app_serves_health_without_live_data():
    from api.app import app

    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert "ok" in r.json()
