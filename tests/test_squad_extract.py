"""/squad/extract and the codes-based /squad/rate path.

Fully synthetic — no live parquets, no network, no credentials: the store and
the vision call are both replaced, so these run in the same dataless CI lane
as the other API tests.
"""

from __future__ import annotations

import base64

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.resolve import Resolver

IMG = base64.b64encode(b"not really an image, but valid base64").decode()

# codes 1-3 GKP, 4-9 DEF, 10-15 MID, 16-19 FWD, plus a same-name MID pair (20, 21)
_SPEC = [("GKP", 3), ("DEF", 6), ("MID", 6), ("FWD", 4)]
SQUAD_CODES = [1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 16, 17, 18]  # legal 2/5/5/3


def synth_players() -> pd.DataFrame:
    rows, code = [], 0
    for pos, n in _SPEC:
        for _ in range(n):
            code += 1
            rows.append(
                (
                    code,
                    f"{pos.title()} Player{code}",
                    f"P{code}",
                    f"Club{code}",
                    pos,
                    40 + code,
                    20.0 + code,
                    2.0 + code / 10,
                )
            )
    rows.append((20, "Twin One", "Twin", "ClubT1", "MID", 50, 9.0, 0.9))
    rows.append((21, "Twin Two", "Twin", "ClubT2", "MID", 50, 8.0, 0.8))
    return pd.DataFrame(
        rows,
        columns=["code", "player", "web_name", "team", "position", "price", "xpts", "xpts_next"],
    )


class FakeStore:
    def __init__(self) -> None:
        self.players = synth_players()
        self.resolver = Resolver(self.players)
        self.provenance = {
            "season": "2026-27",
            "gw_window": [1, 6],
            "data_snapshot": "test",
            "computed_at": "2026-08-20T00:00:00+00:00",
        }


def _row_of(code: int) -> str:
    return "GKP" if code <= 3 else "DEF" if code <= 9 else "MID" if code <= 15 else "FWD"


def canned_extraction(codes=SQUAD_CODES) -> dict:
    return {
        "view": "pick_team",
        "players": [
            {"name": f"P{c}", "row": _row_of(c), "is_captain": c == 10, "is_vice": c == 16}
            for c in codes
        ],
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.delenv("CHAT_DAILY_TOKEN_CAP", raising=False)
    from api import app as app_module
    from api import tools, vision

    store = FakeStore()
    monkeypatch.setattr(app_module, "get_store", lambda: store)
    monkeypatch.setattr(tools, "get_store", lambda: store)
    monkeypatch.setattr(vision, "extract_squad", lambda image, media: canned_extraction())
    monkeypatch.setattr(app_module, "_extract_hits", {})
    return TestClient(app_module.app)


# --- /squad/extract -----------------------------------------------------------


def test_extract_full_squad_is_complete(client):
    r = client.post("/squad/extract", json={"image": IMG, "media_type": "image/png"})
    assert r.status_code == 200
    body = r.json()
    assert body["complete"] is True
    assert body["warnings"] == []
    assert body["counts"] == {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    assert [p["match"]["code"] for p in body["players"]] == SQUAD_CODES
    assert all(p["status"] == "ok" for p in body["players"])
    captain = [p["match"]["code"] for p in body["players"] if p["is_captain"]]
    vice = [p["match"]["code"] for p in body["players"] if p["is_vice"]]
    assert captain == [10] and vice == [16]


def test_extract_tolerates_data_url_prefix(client):
    r = client.post("/squad/extract", json={"image": f"data:image/jpeg;base64,{IMG}"})
    assert r.status_code == 200


def test_extract_rejects_bad_media_type(client):
    r = client.post("/squad/extract", json={"image": IMG, "media_type": "image/gif"})
    assert r.status_code == 422
    assert "media type" in r.json()["detail"]


def test_extract_rejects_invalid_base64(client):
    r = client.post("/squad/extract", json={"image": "!!not-base64!!"})
    assert r.status_code == 422


def test_extract_partial_read_is_200_but_incomplete(client, monkeypatch):
    from api import vision

    monkeypatch.setattr(
        vision, "extract_squad", lambda image, media: canned_extraction(SQUAD_CODES[:11])
    )
    body = client.post("/squad/extract", json={"image": IMG}).json()
    assert body["complete"] is False
    assert any("expected 15" in w for w in body["warnings"])
    assert len(body["players"]) == 11


def test_extract_ambiguous_name_needs_confirmation(client, monkeypatch):
    from api import vision

    ext = canned_extraction()
    ext["players"][7] = {"name": "Twin", "row": "MID", "is_captain": False, "is_vice": False}
    monkeypatch.setattr(vision, "extract_squad", lambda image, media: ext)
    body = client.post("/squad/extract", json={"image": IMG}).json()
    assert body["complete"] is False
    twin = body["players"][7]
    assert twin["status"] == "ambiguous"
    assert {c["code"] for c in twin["candidates"]} == {20, 21}
    assert any("Twin" in w for w in body["warnings"])


def test_extract_per_user_rate_limit(client, monkeypatch):
    from api import app as app_module

    monkeypatch.setattr(app_module, "EXTRACT_LIMIT_PER_HOUR", 1)
    assert client.post("/squad/extract", json={"image": IMG}).status_code == 200
    r = client.post("/squad/extract", json={"image": IMG})
    assert r.status_code == 429
    assert "rate limit" in r.json()["detail"]


def test_extract_respects_daily_token_budget(client, monkeypatch):
    monkeypatch.setenv("CHAT_DAILY_TOKEN_CAP", "0")
    r = client.post("/squad/extract", json={"image": IMG})
    assert r.status_code == 429
    assert "midnight UTC" in r.json()["detail"]


# --- /squad/rate with codes ---------------------------------------------------


def test_rate_with_codes_solves_lineup(client):
    r = client.post("/squad/rate", json={"codes": SQUAD_CODES})
    assert r.status_code == 200
    body = r.json()
    assert len(body["starting_xi"]) == 11
    assert len(body["bench_in_order"]) == 4
    assert body["formation"]
    assert body["gap_to_optimal"] >= 0
    assert sum(1 for p in body["starting_xi"] if p.get("captain")) == 1


def test_rate_requires_exactly_one_of_players_or_codes(client):
    assert client.post("/squad/rate", json={}).status_code == 422
    both = {"codes": SQUAD_CODES, "players": [f"P{c}" for c in SQUAD_CODES]}
    assert client.post("/squad/rate", json=both).status_code == 422


def test_rate_with_codes_validates_membership_and_shape(client):
    dup = [*SQUAD_CODES[:14], SQUAD_CODES[0]]
    r = client.post("/squad/rate", json={"codes": dup})
    assert r.status_code == 404 and "duplicate" in str(r.json()["detail"])

    unknown = [*SQUAD_CODES[:14], 999]
    r = client.post("/squad/rate", json={"codes": unknown})
    assert r.status_code == 404 and "unknown player codes" in str(r.json()["detail"])

    six_def = [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 16, 17, 18]  # 6 DEF / 4 MID
    r = client.post("/squad/rate", json={"codes": six_def})
    assert r.status_code == 404 and "squad shape" in str(r.json()["detail"])
