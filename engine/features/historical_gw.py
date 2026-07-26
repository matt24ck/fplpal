"""Normalize the vaastav archive into one canonical player-gameweek table.

Ten seasons of ``merged_gw.csv`` with drifting schemas become a single parquet
(one row per player per fixture — double gameweeks produce two rows):

    data/features/player_gw.parquet

Season quirks handled here (verified against the actual files):

- 2016-17/2017-18: latin-1 encoding, ``First_Last`` names, no team/position.
- 2018-19/2019-20: names carry a trailing ``_<id>`` suffix.
- pre-2020-21: no ``team``/``position`` columns — position joins from
  ``players_raw.csv`` (element_type); team id is derived from the fixture:
  each fixture has exactly two opponent_team values, a player's team is the
  other one.
- 2019-20: COVID restart gameweeks are numbered 39-47 (kept as-is; models
  should key time on kickoff_time, not GW number).
- xG columns (xg/xa/xgi/xgc) and ``starts`` exist from 2022-23 only.
- Defensive-count stats (cbi/tackles/recoveries) exist 2016-19 and 2025-26;
  the ``defensive_contribution`` points stat is 2025-26 only.
- 2024-25: assistant-manager ("AM") rows are dropped.
- ``code`` is FPL's global player id, stable across seasons (element ids are
  not) — joined from ``players_raw.csv``; it is the cross-season identity key
  (player names drift between seasons in the source).

Run: ``python -m engine.features.historical_gw``
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd

from engine.ingest.historical import SEASONS, historical_root

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "data" / "features" / "player_gw.parquet"

POSITION_MAP = {"GK": "GKP", "GKP": "GKP", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}
ELEMENT_TYPE_TO_POSITION = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}  # 5 = AM, dropped

RENAMES = {
    "expected_goals": "xg",
    "expected_assists": "xa",
    "expected_goal_involvements": "xgi",
    "expected_goals_conceded": "xgc",
    "clearances_blocks_interceptions": "cbi",
    "value": "price",
}

INT_COLS = [
    "minutes",
    "total_points",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "own_goals",
    "penalties_saved",
    "penalties_missed",
    "saves",
    "yellow_cards",
    "red_cards",
    "bonus",
    "bps",
    "price",
    "selected",
    "transfers_in",
    "transfers_out",
]
NULLABLE_INT_COLS = [
    "starts",
    "cbi",
    "tackles",
    "recoveries",
    "defensive_contribution",
    "team_h_score",
    "team_a_score",
]
FLOAT_COLS = ["xg", "xa", "xgi", "xgc", "influence", "creativity", "threat", "ict_index"]

CANONICAL = [
    "season",
    "gw",
    "fixture",
    "kickoff_time",
    "element",
    "code",
    "player",
    "position",
    "team",
    "opponent",
    "team_id",
    "opponent_id",
    "was_home",
    *NULLABLE_INT_COLS,
    *INT_COLS,
    *FLOAT_COLS,
]


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="latin-1")


def _team_name_map(root: Path, season: str) -> dict[int, str]:
    """Season-scoped team id -> FPL team name, from teams.csv or the master list."""
    teams_csv = root / season / "teams.csv"
    if teams_csv.exists():
        teams = _read_csv(teams_csv)
        return dict(zip(teams["id"].astype(int), teams["name"].astype(str)))
    master_path = root / "master_team_list.csv"
    master = _read_csv(master_path)
    expected = {"season", "team", "team_name"}
    if not expected.issubset(master.columns):
        raise ValueError(
            f"unexpected master_team_list.csv schema {list(master.columns)}; expected {expected}"
        )
    rows = master[master["season"] == season]
    if rows.empty:
        raise ValueError(f"no team names for {season} in teams.csv or master_team_list.csv")
    return dict(zip(rows["team"].astype(int), rows["team_name"].astype(str)))


def _derive_team_id(df: pd.DataFrame) -> pd.Series:
    """A fixture has two opponent_team values; a player's team is the other one.

    sum(pair) - own opponent id = the other id. Fixtures where only one side's
    players appear (shouldn't happen) come out as NA.
    """
    pair_sum = df.groupby("fixture")["opponent_team"].transform(
        lambda s: pd.NA if s.nunique() != 2 else s.unique().sum()
    )
    return (pair_sum - df["opponent_team"]).astype("Int64")


def load_season_gw(root: Path, season: str) -> pd.DataFrame:
    df = _read_csv(root / season / "gws" / "merged_gw.csv")
    df = df.rename(columns=RENAMES)

    out = pd.DataFrame()
    out["season"] = pd.Series(season, index=df.index)
    out["gw"] = df["GW"].astype(int)
    out["fixture"] = df["fixture"].astype(int)
    out["kickoff_time"] = pd.to_datetime(df["kickoff_time"], utc=True, errors="coerce")
    out["element"] = df["element"].astype(int)
    out["player"] = (
        df["name"]
        .astype(str)
        .str.replace(r"_\d+$", "", regex=True)
        .str.replace("_", " ", regex=False)
        .str.strip()
    )

    # Cross-season identity: FPL's stable global player code.
    players_raw = _read_csv(root / season / "players_raw.csv")
    code = dict(zip(players_raw["id"].astype(int), players_raw["code"].astype(int)))
    out["code"] = out["element"].map(code).astype("Int64")

    # Position: from the file where present, else via players_raw element_type.
    if "position" in df.columns:
        out["position"] = df["position"].map(POSITION_MAP)
    else:
        etype = dict(zip(players_raw["id"].astype(int), players_raw["element_type"].astype(int)))
        out["position"] = out["element"].map(etype).map(ELEMENT_TYPE_TO_POSITION)

    # Teams: derive ids from fixture pairs, then map to names.
    names = _team_name_map(root, season)
    out["opponent_id"] = df["opponent_team"].astype("Int64")
    out["team_id"] = _derive_team_id(df.assign(fixture=out["fixture"]))
    out["opponent"] = out["opponent_id"].map(names)
    if "team" in df.columns:
        out["team"] = df["team"].astype(str)
    else:
        out["team"] = out["team_id"].map(names)

    out["was_home"] = df["was_home"].astype(bool)

    for col in NULLABLE_INT_COLS:
        out[col] = (
            pd.to_numeric(df[col], errors="coerce").astype("Int64")
            if col in df.columns
            else pd.Series(pd.NA, index=df.index, dtype="Int64")
        )
    for col in INT_COLS:
        out[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    for col in FLOAT_COLS:
        out[col] = (
            pd.to_numeric(df[col], errors="coerce")
            if col in df.columns
            else pd.Series(pd.NA, index=df.index, dtype="Float64")
        )

    # Drop assistant-manager rows (2024-25 only) and anything unmappable.
    out = out[out["position"].notna()]
    return out


def build(root: Path | None = None, out_path: Path | None = None) -> pd.DataFrame:
    root = root or historical_root()
    out_path = (
        out_path
        or Path(os.environ.get("FPL_FEATURES_DIR", DEFAULT_OUT.parent)) / "player_gw.parquet"
    )

    frames = []
    for season in SEASONS:
        season_df = load_season_gw(root, season)
        frames.append(season_df)
        print(f"{season}: {len(season_df):,} rows, {season_df['element'].nunique()} players")

    table = pd.concat(frames, ignore_index=True)

    # One row per player per fixture; duplicates are upstream data errors.
    dupes = table.duplicated(subset=["season", "element", "fixture"]).sum()
    if dupes:
        print(f"warning: dropping {dupes} duplicate (season, element, fixture) rows")
        table = table.drop_duplicates(subset=["season", "element", "fixture"], keep="first")

    _validate(table)
    table = table.sort_values(["season", "gw", "kickoff_time", "element"]).reset_index(drop=True)
    table = table[CANONICAL]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out_path, index=False)
    print(f"\nwrote {len(table):,} rows -> {out_path}")
    _print_summary(table)
    return table


def _validate(table: pd.DataFrame) -> None:
    problems = []
    bad_pos = set(table["position"].unique()) - {"GKP", "DEF", "MID", "FWD"}
    if bad_pos:
        problems.append(f"unexpected positions: {bad_pos}")
    for col in ("team", "opponent"):
        missing = table[col].isna().mean()
        if missing > 0.001:
            problems.append(f"{col} unmapped for {missing:.1%} of rows")
    if table["kickoff_time"].isna().mean() > 0.01:
        problems.append("kickoff_time missing on >1% of rows")
    if table["code"].isna().mean() > 0.001:
        problems.append(f"code unmapped for {table['code'].isna().mean():.2%} of rows")
    if problems:
        raise ValueError("player_gw validation failed: " + "; ".join(problems))


def _print_summary(table: pd.DataFrame) -> None:
    print("\ncoverage by season:")
    cov = table.groupby("season").agg(
        rows=("element", "size"),
        xg=("xg", lambda s: f"{s.notna().mean():.0%}"),
        starts=("starts", lambda s: f"{s.notna().mean():.0%}"),
        def_counts=("cbi", lambda s: f"{s.notna().mean():.0%}"),
        dc_points=("defensive_contribution", lambda s: f"{s.notna().mean():.0%}"),
    )
    print(cov.to_string())

    print("\ntop scorer per season (sanity check):")
    totals = table.groupby(["season", "player"])["total_points"].sum().reset_index()
    top = totals.loc[totals.groupby("season")["total_points"].idxmax()]
    for _, r in top.iterrows():
        print(f"  {r['season']}: {r['player']} ({r['total_points']} pts)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the canonical player-GW table.")
    parser.add_argument("--root", type=Path, default=None, help="vaastav archive root")
    parser.add_argument("--out", type=Path, default=None, help="output parquet path")
    args = parser.parse_args()
    build(args.root, args.out)


if __name__ == "__main__":
    main()
