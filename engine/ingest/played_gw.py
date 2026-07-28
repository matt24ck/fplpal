"""Post-match ingest: finished gameweeks appended to the canonical player-GW table.

The models retrain on current-season data only if played fixtures land in
``data/features/player_gw.parquet`` in the exact shape the historical build
produces (``engine/features/historical_gw.py``). This job closes that loop:

1. Snapshot bootstrap + fixtures (the usual archive-first posture), find
   events that are ``finished`` *and* ``data_checked`` (points final — no
   provisional bonus), and within them the finished fixtures not yet in the
   table. Zero such fixtures — pre-season, or nothing new — is a clean no-op.
2. Archive ``event/{gw}/live`` for each affected gameweek and one combined
   ``element-summary`` snapshot for the full player pool, then transform the
   per-fixture ``history`` entries into canonical rows (one row per player
   per fixture, so double gameweeks produce two rows, exactly like the
   archive).
3. Validate before appending: ``defensive_contribution`` must equal the raw
   CBIT/CBIRT count (cbi+tackles for DEF, +recoveries for MID/FWD — the
   archive identity BUILDLOG §11 verified; a mismatch means FPL changed the
   semantics and the job must fail loudly, not append quietly), and per-player
   GW totals must reproduce the live endpoint's ``total_points``.
4. Append idempotently — new rows are cast to the existing table's dtypes
   (schema identity by construction), re-runs never duplicate a fixture, and
   partial gameweeks (postponements) are picked up by later runs because
   ingestion is keyed on fixtures, not events. Then rebuild the match results
   table so team strength sees the new scores.

Run: ``python -m engine.ingest.played_gw``
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import pandas as pd

from engine.features.historical_gw import (
    CANONICAL,
    ELEMENT_TYPE_TO_POSITION,
    FLOAT_COLS,
    INT_COLS,
    NULLABLE_INT_COLS,
)
from engine.ingest.fpl_api import FplApi
from engine.ingest.snapshot import latest_snapshot, run_core_snapshot, save_snapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEATURES_DIR = REPO_ROOT / "data" / "features"

LIVE_SEASON = "2026-27"
# Live API team name -> the name the historical archive uses. Applied at
# ingest time so the canonical table (and the matches/team-strength tables
# built from it) keep one identity per club across seasons.
TEAM_ALIASES = {"Ipswich Town": "Ipswich", "Hull City": "Hull"}

# Canonical column -> element-summary ``history`` key (identical unless noted).
HISTORY_FIELDS = {
    "starts": "starts",
    "cbi": "clearances_blocks_interceptions",
    "tackles": "tackles",
    "recoveries": "recoveries",
    "defensive_contribution": "defensive_contribution",
    "team_h_score": "team_h_score",
    "team_a_score": "team_a_score",
    "minutes": "minutes",
    "total_points": "total_points",
    "goals_scored": "goals_scored",
    "assists": "assists",
    "clean_sheets": "clean_sheets",
    "goals_conceded": "goals_conceded",
    "own_goals": "own_goals",
    "penalties_saved": "penalties_saved",
    "penalties_missed": "penalties_missed",
    "saves": "saves",
    "yellow_cards": "yellow_cards",
    "red_cards": "red_cards",
    "bonus": "bonus",
    "bps": "bps",
    "price": "value",
    "selected": "selected",
    "transfers_in": "transfers_in",
    "transfers_out": "transfers_out",
    "xg": "expected_goals",
    "xa": "expected_assists",
    "xgi": "expected_goal_involvements",
    "xgc": "expected_goals_conceded",
    "influence": "influence",
    "creativity": "creativity",
    "threat": "threat",
    "ict_index": "ict_index",
}


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=CANONICAL)


def finished_fixture_ids(bootstrap: dict, fixtures: list[dict]) -> set[int]:
    """Fixtures whose stats are final: the fixture is finished and its event is
    both finished and data-checked (bonus and points confirmed)."""
    done_events = {
        e["id"] for e in bootstrap.get("events", []) if e.get("finished") and e.get("data_checked")
    }
    return {int(f["id"]) for f in fixtures if f.get("event") in done_events and f.get("finished")}


def build_played_rows(
    bootstrap: dict,
    fixtures: list[dict],
    summaries: dict[int, dict],
    fixture_ids: set[int],
    season: str = LIVE_SEASON,
) -> pd.DataFrame:
    """Canonical player-GW rows for ``fixture_ids`` from element-summary
    ``history`` entries. One row per player per fixture; assistant-manager
    elements are dropped, exactly like the historical build."""
    teams = {int(t["id"]): TEAM_ALIASES.get(t["name"], t["name"]) for t in bootstrap["teams"]}
    fx = {int(f["id"]): f for f in fixtures}
    els = {int(e["id"]): e for e in bootstrap["elements"]}

    records: list[dict[str, Any]] = []
    for el_id, summary in summaries.items():
        el = els.get(int(el_id))
        if el is None or el["element_type"] not in ELEMENT_TYPE_TO_POSITION:
            continue
        for h in summary.get("history", []):
            fid = int(h["fixture"])
            if fid not in fixture_ids:
                continue
            f = fx[fid]
            opponent_id = int(h["opponent_team"])
            # Own team from the fixture sides, not bootstrap's current team —
            # robust to mid-season transfers when backfilling old fixtures.
            team_id = int(f["team_a"]) if opponent_id == int(f["team_h"]) else int(f["team_h"])
            rec: dict[str, Any] = {
                "season": season,
                "gw": int(f["event"]),
                "fixture": fid,
                "kickoff_time": f.get("kickoff_time"),
                "element": int(el["id"]),
                "code": int(el["code"]),
                "player": f"{el['first_name']} {el['second_name']}".strip(),
                "position": ELEMENT_TYPE_TO_POSITION[el["element_type"]],
                "team": teams[team_id],
                "opponent": teams[opponent_id],
                "team_id": team_id,
                "opponent_id": opponent_id,
                "was_home": bool(h["was_home"]),
            }
            for col, key in HISTORY_FIELDS.items():
                rec[col] = h.get(key)
            records.append(rec)

    if not records:
        return _empty()

    out = pd.DataFrame(records)
    out["kickoff_time"] = pd.to_datetime(out["kickoff_time"], utc=True, errors="coerce")
    for col in NULLABLE_INT_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
    for col in INT_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    for col in FLOAT_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.sort_values(["gw", "kickoff_time", "element"]).reset_index(drop=True)[CANONICAL]
    _validate_rows(out)
    return out


def _validate_rows(rows: pd.DataFrame) -> None:
    problems = []
    dupes = int(rows.duplicated(["element", "fixture"]).sum())
    if dupes:
        problems.append(f"{dupes} duplicate (element, fixture) rows")
    for col in ("team", "opponent"):
        if rows[col].isna().any():
            problems.append(f"{col} unmapped on {int(rows[col].isna().sum())} rows")
    if rows["kickoff_time"].isna().any():
        problems.append("kickoff_time missing")

    # DC semantics guard: the canonical column is the raw CBIT/CBIRT count
    # (exact archive identity for DEF/MID/FWD; GKP has no exact formula). If
    # the API starts serving awarded points here instead, fail loudly.
    d = rows[
        rows["position"].isin(["DEF", "MID", "FWD"])
        & rows["defensive_contribution"].notna()
        & rows["cbi"].notna()
        & rows["tackles"].notna()
        & rows["recoveries"].notna()
    ]
    if len(d):
        cbit = d["cbi"] + d["tackles"]
        expected = cbit.where(d["position"] == "DEF", cbit + d["recoveries"])
        bad = int((d["defensive_contribution"] != expected).sum())
        if bad:
            problems.append(
                f"defensive_contribution != raw CBIT/CBIRT count on {bad} rows — "
                "the API semantics may have changed (points instead of counts?); "
                "review before appending"
            )
    if problems:
        raise ValueError("played-GW rows failed validation: " + "; ".join(problems))


def validate_vs_live(rows: pd.DataFrame, live: dict[int, dict]) -> None:
    """Cross-check: per-player GW totals in ``rows`` must reproduce the live
    endpoint's ``total_points``. ``rows`` must hold ALL of each gameweek's
    ingested fixtures (existing + new), since live stats aggregate the GW."""
    for gw, payload in live.items():
        ours = rows[rows["gw"] == int(gw)].groupby("element")["total_points"].sum()
        mismatches = []
        for el in payload.get("elements", []):
            el_id = int(el["id"])
            if el_id not in ours.index:
                continue  # AM rows and pool exits have no canonical rows
            theirs = int(el.get("stats", {}).get("total_points", 0))
            if int(ours.loc[el_id]) != theirs:
                mismatches.append((el_id, int(ours.loc[el_id]), theirs))
        if mismatches:
            sample = ", ".join(f"element {e}: ours {o} vs live {t}" for e, o, t in mismatches[:5])
            raise ValueError(
                f"GW{gw} total_points disagree with event/{gw}/live on "
                f"{len(mismatches)} players ({sample}) — not appending"
            )


def append_rows(table_path: Path, new_rows: pd.DataFrame, season: str = LIVE_SEASON) -> None:
    """Idempotent append: replace any existing rows for the same fixtures,
    cast to the table's exact dtypes, keep one row per (season, element,
    fixture), write atomically."""
    existing = pd.read_parquet(table_path)
    if list(existing.columns) != list(new_rows.columns):
        raise ValueError(
            f"column mismatch vs canonical table: {list(new_rows.columns)} "
            f"!= {list(existing.columns)}"
        )
    new_fixtures = set(new_rows["fixture"].tolist())
    keep = ~((existing["season"] == season) & existing["fixture"].isin(new_fixtures))
    cast = new_rows.astype(existing.dtypes.to_dict())
    combined = pd.concat([existing[keep], cast], ignore_index=True)
    dupes = int(combined.duplicated(["season", "element", "fixture"]).sum())
    if dupes:
        raise ValueError(f"append would create {dupes} duplicate (season, element, fixture) rows")
    combined = combined.sort_values(["season", "gw", "kickoff_time", "element"]).reset_index(
        drop=True
    )
    tmp = table_path.with_suffix(".parquet.tmp")
    combined.to_parquet(tmp, index=False)
    tmp.replace(table_path)


def _rebuild_matches(features_dir: Path) -> None:
    from engine.features.matches import build_matches

    build_matches(features_dir / "player_gw.parquet", features_dir / "matches.parquet")


def ingest(features_dir: Path | None = None, season: str = LIVE_SEASON) -> pd.DataFrame:
    """One scheduled run. Returns the appended rows (empty frame = no-op)."""
    features_dir = features_dir or Path(
        os.environ.get("FPL_FEATURES_DIR", str(DEFAULT_FEATURES_DIR))
    )
    table_path = features_dir / "player_gw.parquet"
    matches_path = features_dir / "matches.parquet"
    if not table_path.exists():
        print("played-gw: no canonical table yet — seed the data volume first; skipping")
        return _empty()

    bootstrap = run_core_snapshot()
    if bootstrap is None:
        return _empty()  # API in maintenance; run_core_snapshot already logged
    snap = latest_snapshot("fixtures")
    assert snap is not None  # run_core_snapshot just archived one
    _, fixtures = snap

    done = finished_fixture_ids(bootstrap, fixtures)
    if not done:
        print("played-gw: no finished gameweeks — nothing to ingest")
        return _empty()

    existing = pd.read_parquet(table_path)
    have = set(existing.loc[existing["season"] == season, "fixture"].tolist())
    todo = done - have
    if not todo:
        print(f"played-gw: up to date ({len(have)} fixtures already ingested)")
        if matches_path.exists() and matches_path.stat().st_mtime < table_path.stat().st_mtime:
            _rebuild_matches(features_dir)  # heal a crash between append and rebuild
        return _empty()

    fx_by_id = {int(f["id"]): f for f in fixtures}
    events_todo = sorted({int(fx_by_id[fid]["event"]) for fid in todo})
    print(f"played-gw: {len(todo)} finished fixtures to ingest (GWs {events_todo})")

    with FplApi() as api:
        live: dict[int, dict] = {}
        for gw in events_todo:
            live[gw] = api.event_live(gw)
            save_snapshot(f"event_live_gw{gw}", live[gw])
        el_ids = [
            int(e["id"])
            for e in bootstrap["elements"]
            if e["element_type"] in ELEMENT_TYPE_TO_POSITION
        ]
        summaries: dict[int, dict] = {}
        for i, el_id in enumerate(el_ids, 1):
            summaries[el_id] = api.element_summary(el_id)
            if i % 100 == 0:
                print(f"  element summaries {i}/{len(el_ids)}")
        save_snapshot("element_summaries", {str(k): v for k, v in summaries.items()})

    rows = build_played_rows(bootstrap, fixtures, summaries, todo, season)
    got = set(rows["fixture"].tolist()) if len(rows) else set()
    lagging = todo - got
    if lagging:
        # element-summary can lag event status briefly; keyed on fixtures, a
        # later run picks these up
        print(f"played-gw: {len(lagging)} fixtures not yet in element summaries — deferred")
    if rows.empty:
        return _empty()

    affected = existing[
        (existing["season"] == season) & existing["gw"].isin({int(g) for g in events_todo})
    ]
    validate_vs_live(pd.concat([affected, rows], ignore_index=True), live)

    append_rows(table_path, rows, season)
    per_gw = rows.groupby("gw")["fixture"].nunique().to_dict()
    print(
        f"played-gw: appended {len(rows):,} rows "
        f"({', '.join(f'GW{g}: {n} fixtures' for g, n in sorted(per_gw.items()))})"
    )
    _rebuild_matches(features_dir)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest finished gameweeks into player_gw.")
    parser.add_argument("--features-dir", type=Path, default=None)
    args = parser.parse_args()
    ingest(args.features_dir)


if __name__ == "__main__":
    main()
