"""Real team import: FT banking walk, purchase-price reconstruction (incl.
free-hit reverts and pending transfers), sell-price rule, chip halves, and
the honest pre-deadline pending state — all on synthetic payloads."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import engine.ingest.team_state as ts
from engine.ingest.team_state import (
    build_team_state,
    chips_available_now,
    reconstruct_free_transfers,
    reconstruct_purchase_prices,
    sell_price,
)

# -- synthetic payloads ------------------------------------------------------
# 15-man squad: elements 1-2 GKP, 3-7 DEF, 8-12 MID, 13-15 FWD.
# Element 16 (MID) was wildcarded in for 8; 17 (FWD) is a pending buy for 14.


def _element(i: int, etype: int) -> dict:
    return {
        "id": i,
        "code": 9000 + i,
        "element_type": etype,
        "team": (i % 4) + 1,
        "first_name": f"P{i}",
        "second_name": f"Player{i}",
        "now_cost": 50 + i,  # e.g. el 3 -> 53
        "cost_change_start": 3 if i == 3 else 0,  # el 3 rose from 50
    }


BOOTSTRAP = {
    "teams": [{"id": i, "name": n} for i, n in
              [(1, "Alpha"), (2, "Beta"), (3, "Gamma"), (4, "Delta")]],
    "elements": [
        *[_element(i, 1) for i in (1, 2)],
        *[_element(i, 2) for i in (3, 4, 5, 6, 7)],
        *[_element(i, 3) for i in (8, 9, 10, 11, 12, 16)],
        *[_element(i, 4) for i in (13, 14, 15, 17)],
    ],
}  # fmt: skip

GW1_SQUAD = list(range(1, 16))
GW5_SQUAD = [i for i in GW1_SQUAD if i != 8] + [16]  # 8 -> 16 on the GW3 wildcard

ENTRY = {
    "id": 4242,
    "name": "Test XI",
    "player_first_name": "Mat",
    "player_last_name": "K",
    "current_event": 5,
    "started_event": 1,
    "summary_overall_points": 311,
    "summary_overall_rank": 123_456,
    "summary_event_points": 61,
    "last_deadline_bank": 15,
    "last_deadline_value": 1003,
}

HISTORY = {
    "current": [
        {"event": 1, "event_transfers": 0},
        {"event": 2, "event_transfers": 1},
        {"event": 3, "event_transfers": 1},  # wildcard week
        {"event": 4, "event_transfers": 1},  # free-hit week
        {"event": 5, "event_transfers": 0},
    ],
    "chips": [
        {"name": "wildcard", "event": 3},
        {"name": "freehit", "event": 4},
        {"name": "3xc", "event": 5},
    ],
}

TRANSFERS = [  # newest first, like the API serves it
    {"element_in": 17, "element_in_cost": 70, "element_out": 14, "element_out_cost": 60,
     "event": 6, "time": "2026-09-30T10:00:00Z"},  # pending for GW6
    {"element_in": 17, "element_in_cost": 69, "element_out": 13, "element_out_cost": 60,
     "event": 4, "time": "2026-09-24T10:00:00Z"},  # free hit — reverted
    {"element_in": 16, "element_in_cost": 62, "element_out": 8, "element_out_cost": 55,
     "event": 3, "time": "2026-09-17T10:00:00Z"},  # wildcard — permanent
    {"element_in": 9, "element_in_cost": 58, "element_out": 20, "element_out_cost": 50,
     "event": 2, "time": "2026-09-10T10:00:00Z"},
]  # fmt: skip


def _picks(els: list[int], captain: int, vice: int) -> dict:
    return {
        "active_chip": None,
        "entry_history": {"bank": 20, "value": 1010},
        "picks": [
            {
                "element": el,
                "position": i + 1,
                "multiplier": 2 if el == captain else 1,
                "is_captain": el == captain,
                "is_vice_captain": el == vice,
            }
            for i, el in enumerate(els)
        ],
    }


PICKS_NOW = _picks(GW5_SQUAD, captain=13, vice=9)
PICKS_FIRST = _picks(GW1_SQUAD, captain=13, vice=9)
CHIPS_BY_EVENT = {3: "wildcard", 4: "freehit", 5: "triple_captain"}


# -- pure reconstructions ----------------------------------------------------


def test_sell_price_rule():
    assert sell_price(50, 50) == 50
    assert sell_price(50, 45) == 45  # losses come off in full
    assert sell_price(50, 56) == 53  # half the profit, rounded down
    assert sell_price(50, 57) == 53


def test_free_transfers_walk():
    # e2 spends the 1 FT, e3/e4 are chip weeks (consume nothing), e5 holds
    assert reconstruct_free_transfers(HISTORY["current"], CHIPS_BY_EVENT) == 4

    only_gw1 = [{"event": 1, "event_transfers": 0}]
    assert reconstruct_free_transfers(only_gw1, {}) == 1

    hoarder = [{"event": e, "event_transfers": 0} for e in range(1, 9)]
    assert reconstruct_free_transfers(hoarder, {}) == 5  # capped

    hit_taker = [
        {"event": 1, "event_transfers": 0},
        {"event": 2, "event_transfers": 3},  # 1 FT + two hits
    ]
    assert reconstruct_free_transfers(hit_taker, {}) == 1  # max(1-3,0)+1


def test_purchase_prices_reconstruction():
    start = {int(e["id"]): int(e["now_cost"]) - int(e["cost_change_start"]) for e in
             BOOTSTRAP["elements"]}  # fmt: skip
    price = reconstruct_purchase_prices(
        PICKS_FIRST["picks"], TRANSFERS, CHIPS_BY_EVENT, start, joined_at_gw1=True
    )
    assert price[3] == 50  # season-start price, not the risen 53
    assert price[16] == 62  # wildcard buy at recorded cost
    assert price[17] == 70  # pending buy counts; the free-hit 69 was skipped
    late = reconstruct_purchase_prices(PICKS_FIRST["picks"], [], {}, start, joined_at_gw1=False)
    assert late[3] is None  # unknowable — caller must approximate, flagged


def test_chip_halves():
    played = [{"name": "wildcard", "event": 3}, {"name": "freehit", "event": 4}]
    assert chips_available_now(played, next_gw=6, first_half_deadline_gw=19) == [
        "bboost",
        "triple_captain",
    ]
    # the second half starts with a fresh set of all four
    assert len(chips_available_now(played, next_gw=25, first_half_deadline_gw=19)) == 4


# -- full state assembly -----------------------------------------------------


def test_build_team_state():
    state = build_team_state(
        ENTRY, HISTORY, PICKS_NOW, PICKS_FIRST, TRANSFERS, BOOTSTRAP,
        first_half_deadline_gw=19,
    )  # fmt: skip
    assert state["status"] == "ok" and state["gw"] == 5
    assert "warnings" not in state  # legal shape, exact purchase prices

    els = {p["element"] for p in state["squad"]}
    assert 17 in els and 14 not in els  # pending GW6 transfer applied
    assert len(els) == 15
    assert state["pending_transfers"] == 1 and "GW6" in state["note"]
    assert state["bank"] == 20 + 60 - 70  # picks bank adjusted by the pending move
    assert state["free_transfers"] == 4
    assert state["chips_available"] == ["bboost"]
    assert {c["name"] for c in state["chips_played"]} == {
        "wildcard", "freehit", "triple_captain",
    }  # fmt: skip

    by_el = {p["element"]: p for p in state["squad"]}
    assert by_el[13]["is_captain"] and by_el[9]["is_vice_captain"]
    assert by_el[3]["purchase_price"] == 50 and by_el[3]["current_price"] == 53
    assert by_el[3]["selling_price"] == 51  # 50 + 3 // 2
    assert by_el[16]["purchase_price"] == 62
    assert by_el[3]["code"] == 9003
    assert not state["approx_purchase_prices"]


def test_late_joiner_is_flagged_approximate():
    entry = {**ENTRY, "started_event": 3, "current_event": 5}
    state = build_team_state(
        entry, HISTORY, PICKS_NOW, PICKS_NOW, TRANSFERS, BOOTSTRAP,
        first_half_deadline_gw=19,
    )  # fmt: skip
    assert state["approx_purchase_prices"]
    assert any("approximated" in w for w in state["warnings"])


# -- fetch orchestration (network faked) -------------------------------------


class FakeApi:
    def __init__(self, entry, picks_404=False):
        self._entry = entry
        self._picks_404 = picks_404

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def entry(self, team_id):
        if self._entry is None:
            req = httpx.Request("GET", "http://x")
            raise httpx.HTTPStatusError(
                "404", request=req, response=httpx.Response(404, request=req)
            )
        return self._entry

    def entry_history(self, team_id):
        return HISTORY

    def entry_picks(self, team_id, gw):
        if self._picks_404:
            req = httpx.Request("GET", "http://x")
            raise httpx.HTTPStatusError(
                "404", request=req, response=httpx.Response(404, request=req)
            )
        return PICKS_NOW if gw == 5 else PICKS_FIRST

    def entry_transfers(self, team_id):
        return TRANSFERS


def _wire(monkeypatch, entry, picks_404=False):
    monkeypatch.setattr(ts, "_cache", {})
    monkeypatch.setattr(ts, "FplApi", lambda: FakeApi(entry, picks_404))
    monkeypatch.setattr(ts, "latest_snapshot", lambda name: (None, BOOTSTRAP))


def test_fetch_pending_before_first_deadline(monkeypatch):
    _wire(monkeypatch, {**ENTRY, "current_event": None})
    state = ts.fetch_team_state(4242)
    assert state["status"] == "pending"
    assert "deadline" in state["note"]


def test_fetch_pending_when_picks_not_public_yet(monkeypatch):
    _wire(monkeypatch, ENTRY, picks_404=True)
    assert ts.fetch_team_state(4242)["status"] == "pending"


def test_fetch_unknown_id(monkeypatch):
    _wire(monkeypatch, None)
    assert "no FPL team with ID" in ts.fetch_team_state(999999999)["error"]


def test_fetch_full_state_and_cache(monkeypatch):
    calls = {"n": 0}

    class CountingApi(FakeApi):
        def entry(self, team_id):
            calls["n"] += 1
            return super().entry(team_id)

    monkeypatch.setattr(ts, "_cache", {})
    monkeypatch.setattr(ts, "FplApi", lambda: CountingApi(ENTRY))
    monkeypatch.setattr(ts, "latest_snapshot", lambda name: (None, BOOTSTRAP))
    first = ts.fetch_team_state(4242)
    second = ts.fetch_team_state(4242)
    assert first["status"] == "ok" and second is first
    assert calls["n"] == 1  # served from the TTL cache


# -- REST endpoint (store + fetch faked; CI-safe) ----------------------------


def test_team_endpoint(monkeypatch):
    import api.app as app_mod

    monkeypatch.setattr(
        app_mod, "get_store", lambda: SimpleNamespace(provenance={"season": "2026-27"})
    )
    monkeypatch.setattr(
        ts, "fetch_team_state",
        lambda tid, gw=19: {"status": "pending", "team_id": tid, "note": ts.PENDING_NOTE},
    )  # fmt: skip
    r = TestClient(app_mod.app).get("/team/4242")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"

    monkeypatch.setattr(
        ts, "fetch_team_state", lambda tid, gw=19: {"error": "no FPL team with ID 1"}
    )
    assert TestClient(app_mod.app).get("/team/1").status_code == 404


@pytest.mark.parametrize("payload", [{}, {"bank": 0.5}])
def test_plan_requires_squad_or_team_id(monkeypatch, payload):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    import api.app as app_mod
    import api.tools as tools_mod

    monkeypatch.setattr(
        tools_mod, "get_store", lambda: SimpleNamespace(provenance={"season": "2026-27"})
    )
    r = TestClient(app_mod.app).post("/transfers/plan", json=payload)
    assert r.status_code == 404
    assert "team_id" in str(r.json()["detail"])
