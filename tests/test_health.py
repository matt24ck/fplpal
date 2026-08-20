"""/health freshness: the ``healthy`` flag flips when the hourly snapshot or
the nightly pipeline stops moving — the silent-stale failure a bare uptime
ping would miss. Pure-function tests plus the endpoint with a faked store."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from api.app import _freshness

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_fresh_data_is_not_stale():
    f = _freshness("2026-08-21T02:31:00+00:00", "20260821T110500Z", now=NOW)
    assert not f["stale"]
    assert f["computed_age_hours"] == 9.5
    assert f["snapshot_age_hours"] == 0.9


def test_stalled_pipeline_is_stale():
    f = _freshness("2026-08-20T02:31:00+00:00", "20260821T110500Z", now=NOW)  # 33.5h old
    assert f["stale"]


def test_stalled_snapshot_job_is_stale():
    f = _freshness("2026-08-21T02:31:00+00:00", "20260821T020500Z", now=NOW)  # ~10h old
    assert f["stale"]


def test_missing_snapshot_is_stale():
    assert _freshness("2026-08-21T02:31:00+00:00", None, now=NOW)["stale"]


def test_maintenance_window_grace():
    # a 4h snapshot gap (FPL 'Game Updating') stays healthy; 26h pipeline cap
    f = _freshness("2026-08-21T02:31:00+00:00", "20260821T080500Z", now=NOW)
    assert not f["stale"]


def test_health_endpoint_healthy_and_stale(monkeypatch):
    from fastapi.testclient import TestClient

    import api.app as app_mod

    now = datetime.now(UTC)
    prov = {
        "season": "2026-27",
        "gw_window": [1, 6],
        "data_snapshot": "x",
        "computed_at": now.isoformat(),
    }
    monkeypatch.setattr(app_mod, "get_store", lambda: SimpleNamespace(provenance=prov))
    fake_path = SimpleNamespace(stem=now.strftime("%Y%m%dT%H%M%SZ") + ".json")
    monkeypatch.setattr(app_mod, "latest_snapshot", lambda name: (fake_path, {}))
    body = TestClient(app_mod.app).get("/health").json()
    assert body["ok"] is True and body["healthy"] is True
    assert body["season"] == "2026-27"

    # pipeline frozen 30h ago -> healthy flips, endpoint still 200
    prov["computed_at"] = (now - timedelta(hours=30)).isoformat()
    monkeypatch.setattr(app_mod, "get_store", lambda: SimpleNamespace(provenance=prov))
    resp = TestClient(app_mod.app).get("/health")
    assert resp.status_code == 200 and resp.json()["healthy"] is False


def test_health_endpoint_no_data(monkeypatch):
    from fastapi.testclient import TestClient

    import api.app as app_mod

    def boom():
        raise FileNotFoundError("no live data")

    monkeypatch.setattr(app_mod, "get_store", boom)
    body = TestClient(app_mod.app).get("/health").json()
    assert body["ok"] is False and body["healthy"] is False
