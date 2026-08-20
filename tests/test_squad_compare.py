"""/squad/compare — rate 2-4 squads and diff them. Fully synthetic."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_squad_extract import SQUAD_CODES, FakeStore

# same legal shape as SQUAD_CODES but with two swaps: DEF 8->9, MID 14->15
VARIANT_CODES = [1, 2, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17, 18]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    from api import app as app_module
    from api import tools

    store = FakeStore()
    monkeypatch.setattr(app_module, "get_store", lambda: store)
    monkeypatch.setattr(tools, "get_store", lambda: store)
    return TestClient(app_module.app)


def test_compare_two_squads(client):
    r = client.post(
        "/squad/compare",
        json={
            "squads": [
                {"label": "Mine", "codes": SQUAD_CODES},
                {"codes": VARIANT_CODES},  # label defaults to Team B
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()

    labels = [s["label"] for s in body["squads"]]
    assert labels == ["Mine", "Team B"]
    for s in body["squads"]:
        assert len(s["starting_xi"]) == 11 and len(s["bench_in_order"]) == 4
        assert s["captain"] is not None

    assert body["verdict"]["best"] in labels
    assert body["verdict"]["margin_xpts"] >= 0

    shared = {p["code"] for p in body["shared"]}
    assert shared == set(SQUAD_CODES) & set(VARIANT_CODES)
    assert {p["code"] for p in body["differentials"]["Mine"]} == {8, 14}
    assert {p["code"] for p in body["differentials"]["Team B"]} == {9, 15}
    # differentials come sorted by projected points, best first
    mine = body["differentials"]["Mine"]
    assert mine[0]["xpts"] >= mine[-1]["xpts"]


def test_compare_identical_squads_has_no_differentials(client):
    r = client.post(
        "/squad/compare",
        json={
            "squads": [
                {"label": "A", "codes": SQUAD_CODES},
                {"label": "A", "codes": SQUAD_CODES},  # duplicate label gets suffixed too
            ]
        },
    )
    body = r.json()
    assert [s["label"] for s in body["squads"]] == ["A", "A (2)"]
    assert body["verdict"]["margin_xpts"] == 0
    assert body["differentials"]["A"] == [] and body["differentials"]["A (2)"] == []
    assert {p["code"] for p in body["shared"]} == set(SQUAD_CODES)


def test_compare_validates_squad_count_and_codes(client):
    one = {"squads": [{"codes": SQUAD_CODES}]}
    assert client.post("/squad/compare", json=one).status_code == 422

    five = {"squads": [{"codes": SQUAD_CODES}] * 5}
    assert client.post("/squad/compare", json=five).status_code == 422

    bad = {
        "squads": [
            {"label": "Good", "codes": SQUAD_CODES},
            {"label": "Bad", "codes": [*SQUAD_CODES[:14], 999]},
        ]
    }
    r = client.post("/squad/compare", json=bad)
    assert r.status_code == 404
    detail = str(r.json()["detail"])
    assert "Bad" in detail and "unknown player codes" in detail
