"""Synthetic FPL API payloads for data-free tests (no volume, no network).

Shapes mirror the real endpoints: bootstrap-static (events/teams/elements),
fixtures, element-summary ``history`` entries (floats as strings, exactly as
the API serves them), and event/{gw}/live. GW1 here is finished and
data-checked with three fixtures — teams 2 and 3 double (a DGW) — GW2 is the
next event. Element 14 is an assistant manager (element_type 5) that every
canonical-table code path must drop, and "Ipswich Town" exercises the
live-name -> archive-name alias.
"""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

BOOTSTRAP = {
    "events": [
        {
            "id": 1,
            "finished": True,
            "data_checked": True,
            "deadline_time": "2026-08-21T17:30:00Z",
        },
        {
            "id": 2,
            "finished": False,
            "data_checked": False,
            "is_next": True,
            "deadline_time": "2026-08-28T17:30:00Z",
        },
    ],
    "teams": [
        {"id": 1, "name": "Alpha"},
        {"id": 2, "name": "Beta"},
        {"id": 3, "name": "Ipswich Town"},
        {"id": 4, "name": "Delta"},
    ],
    "elements": [
        {"id": 10, "code": 5010, "element_type": 1, "team": 1,
         "first_name": "Gio", "second_name": "Keeper"},
        {"id": 11, "code": 5011, "element_type": 2, "team": 1,
         "first_name": "Dan", "second_name": "Back"},
        {"id": 12, "code": 5012, "element_type": 3, "team": 2,
         "first_name": "Mo", "second_name": "Middle"},
        {"id": 13, "code": 5013, "element_type": 4, "team": 3,
         "first_name": "Fred", "second_name": "Front"},
        {"id": 14, "code": 5014, "element_type": 5, "team": 4,
         "first_name": "Boss", "second_name": "Gaffer"},
        {"id": 15, "code": 5015, "element_type": 3, "team": 4,
         "first_name": "Ben", "second_name": "Bench"},
    ],
}  # fmt: skip
for _e in BOOTSTRAP["elements"]:
    _e.update({"now_cost": 55, "status": "a", "chance_of_playing_next_round": None})

FIXTURES = [
    {"id": 101, "event": 1, "team_h": 1, "team_a": 2, "finished": True,
     "kickoff_time": "2026-08-22T14:00:00Z"},
    {"id": 102, "event": 1, "team_h": 3, "team_a": 4, "finished": True,
     "kickoff_time": "2026-08-22T16:30:00Z"},
    {"id": 103, "event": 1, "team_h": 2, "team_a": 3, "finished": True,
     "kickoff_time": "2026-08-23T15:00:00Z"},
    {"id": 201, "event": 2, "team_h": 1, "team_a": 4, "finished": False,
     "kickoff_time": "2026-08-29T14:00:00Z"},
]  # fmt: skip


def history(fixture: int, opponent: int, was_home: bool, **over) -> dict:
    """One element-summary ``history`` entry with realistic field types."""
    kickoffs = {f["id"]: f["kickoff_time"] for f in FIXTURES}
    entry = {
        "fixture": fixture,
        "opponent_team": opponent,
        "was_home": was_home,
        "kickoff_time": kickoffs[fixture],
        "round": next(f["event"] for f in FIXTURES if f["id"] == fixture),
        "team_h_score": 2,
        "team_a_score": 1,
        "minutes": 90,
        "total_points": 2,
        "goals_scored": 0,
        "assists": 0,
        "clean_sheets": 0,
        "goals_conceded": 1,
        "own_goals": 0,
        "penalties_saved": 0,
        "penalties_missed": 0,
        "saves": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "bonus": 0,
        "bps": 12,
        "influence": "25.4",
        "creativity": "3.1",
        "threat": "8.0",
        "ict_index": "3.6",
        "starts": 1,
        "expected_goals": "0.12",
        "expected_assists": "0.05",
        "expected_goal_involvements": "0.17",
        "expected_goals_conceded": "1.32",
        "clearances_blocks_interceptions": 4,
        "recoveries": 5,
        "tackles": 2,
        # raw count, not points: CBIT (cbi+tackles) for GKP/DEF entries below,
        # CBIRT (+recoveries) for MID/FWD — override per element as needed
        "defensive_contribution": 6,
        "value": 55,
        "transfers_balance": 0,
        "selected": 100_000,
        "transfers_in": 0,
        "transfers_out": 0,
    }
    entry.update(over)
    return entry


SUMMARIES = {
    10: {"history": [history(101, 2, True, saves=3, total_points=3)]},  # GKP, CBIT ok
    11: {"history": [history(101, 2, True, total_points=6)]},  # DEF: dc = 4 + 2
    12: {  # MID on team 2 — a double gameweek, one row per fixture
        "history": [
            history(101, 1, False, defensive_contribution=11, goals_scored=1, total_points=7),
            history(103, 3, True, defensive_contribution=11, total_points=2),
        ]
    },
    13: {  # FWD on team 3 — the other DGW side, aliased team name
        "history": [
            history(102, 4, True, defensive_contribution=11, total_points=2),
            history(103, 2, False, defensive_contribution=11, assists=1, total_points=5),
        ]
    },
    14: {"history": [history(102, 3, False)]},  # assistant manager: dropped
    15: {  # unused sub still gets a row, like the archive
        "history": [
            history(
                102, 3, False, minutes=0, starts=0, total_points=0, bps=0,
                clearances_blocks_interceptions=0, recoveries=0, tackles=0,
                defensive_contribution=0, influence="0.0", creativity="0.0",
                threat="0.0", ict_index="0.0", expected_goals="0.00",
                expected_assists="0.00", expected_goal_involvements="0.00",
                expected_goals_conceded="0.00",
            )
        ]
    },
}  # fmt: skip


def live_payload(summaries: dict[int, dict], gw: int = 1) -> dict[int, dict]:
    """event/{gw}/live shaped from the summaries (stats aggregate the GW)."""
    totals: dict[int, int] = defaultdict(int)
    for el_id, s in summaries.items():
        for h in s["history"]:
            if h["round"] == gw:
                totals[el_id] += h["total_points"]
    return {gw: {"elements": [{"id": k, "stats": {"total_points": v}} for k, v in totals.items()]}}


# The canonical table's exact dtypes (recorded from data/features/player_gw.parquet;
# test_real_archive_dtypes guards this against drift when the volume is present).
ARCHIVE_DTYPES = {
    "season": "str", "gw": "int64", "fixture": "int64",
    "kickoff_time": "datetime64[us, UTC]", "element": "int64", "code": "Int64",
    "player": "str", "position": "str", "team": "str", "opponent": "str",
    "team_id": "Int64", "opponent_id": "Int64", "was_home": "bool",
    "starts": "Int64", "cbi": "Int64", "tackles": "Int64", "recoveries": "Int64",
    "defensive_contribution": "Int64", "team_h_score": "Int64", "team_a_score": "Int64",
    "minutes": "int64", "total_points": "int64", "goals_scored": "int64",
    "assists": "int64", "clean_sheets": "int64", "goals_conceded": "int64",
    "own_goals": "int64", "penalties_saved": "int64", "penalties_missed": "int64",
    "saves": "int64", "yellow_cards": "int64", "red_cards": "int64",
    "bonus": "int64", "bps": "int64", "price": "int64", "selected": "int64",
    "transfers_in": "int64", "transfers_out": "int64",
    "xg": "Float64", "xa": "Float64", "xgi": "Float64", "xgc": "Float64",
    "influence": "float64", "creativity": "float64", "threat": "float64",
    "ict_index": "float64",
}  # fmt: skip


def base_table() -> pd.DataFrame:
    """A one-row 2025-26 mini-archive with the real table's dtypes."""
    row = {
        "season": "2025-26", "gw": 38, "fixture": 380,
        "kickoff_time": pd.Timestamp("2026-05-24T15:00:00Z"),
        "element": 999, "code": 4999, "player": "Old Timer", "position": "MID",
        "team": "Alpha", "opponent": "Beta", "team_id": 1, "opponent_id": 2,
        "was_home": True, "starts": 1, "cbi": 3, "tackles": 1, "recoveries": 4,
        "defensive_contribution": 8, "team_h_score": 1, "team_a_score": 1,
        "minutes": 90, "total_points": 2, "goals_scored": 0, "assists": 0,
        "clean_sheets": 0, "goals_conceded": 1, "own_goals": 0,
        "penalties_saved": 0, "penalties_missed": 0, "saves": 0,
        "yellow_cards": 0, "red_cards": 0, "bonus": 0, "bps": 14, "price": 50,
        "selected": 1000, "transfers_in": 0, "transfers_out": 0,
        "xg": 0.1, "xa": 0.2, "xgi": 0.3, "xgc": 1.4,
        "influence": 20.0, "creativity": 10.0, "threat": 5.0, "ict_index": 3.5,
    }  # fmt: skip
    return pd.DataFrame([row]).astype(ARCHIVE_DTYPES)
