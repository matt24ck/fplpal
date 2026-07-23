"""Match-level results table, derived from the canonical player-GW table.

One row per played match: home/away teams, final score, kickoff, and team xG
(sum of player xG per side, 2022-23 onward). This is the training input for
the team-strength model.

Run: ``python -m engine.features.matches``
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYER_GW_PATH = REPO_ROOT / "data" / "features" / "player_gw.parquet"
DEFAULT_OUT = REPO_ROOT / "data" / "features" / "matches.parquet"


def build_matches(player_gw_path: Path | None = None, out_path: Path | None = None) -> pd.DataFrame:
    pg = pd.read_parquet(player_gw_path or PLAYER_GW_PATH)

    side = pg.groupby(["season", "fixture", "team", "was_home"], as_index=False).agg(
        kickoff_time=("kickoff_time", "first"),
        gw=("gw", "first"),
        team_h_score=("team_h_score", "first"),
        team_a_score=("team_a_score", "first"),
        xg=("xg", lambda s: s.sum(min_count=1)),  # all-NA side -> NA, not 0
    )

    home = side[side["was_home"]]
    away = side[~side["was_home"]]
    m = home.merge(away, on=["season", "fixture"], suffixes=("_h", "_a"))

    matches = pd.DataFrame(
        {
            "season": m["season"],
            "fixture": m["fixture"],
            "gw": m["gw_h"],
            "kickoff_time": m["kickoff_time_h"],
            "home": m["team_h"],
            "away": m["team_a"],
            "home_goals": m["team_h_score_h"],
            "away_goals": m["team_a_score_h"],
            "home_xg": m["xg_h"].astype("Float64"),
            "away_xg": m["xg_a"].astype("Float64"),
        }
    )

    n_before = len(matches)
    matches = matches.dropna(subset=["home_goals", "away_goals"])
    matches["home_goals"] = matches["home_goals"].astype(int)
    matches["away_goals"] = matches["away_goals"].astype(int)
    dropped = n_before - len(matches)
    if dropped:
        print(f"dropped {dropped} rows without a final score")

    matches = matches.sort_values(["kickoff_time", "fixture"]).reset_index(drop=True)

    out_path = out_path or DEFAULT_OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    matches.to_parquet(out_path, index=False)

    counts = matches.groupby("season").size()
    print(f"wrote {len(matches):,} matches -> {out_path}")
    print(counts.to_string())
    short = counts[counts != 380]
    if not short.empty:
        print(f"note: seasons without exactly 380 matches: {dict(short)}")
    return matches


def load_matches(path: Path | None = None) -> pd.DataFrame:
    path = path or DEFAULT_OUT
    if not path.exists():
        return build_matches(out_path=path)
    return pd.read_parquet(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the match results table.")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    build_matches(out_path=args.out)


if __name__ == "__main__":
    main()
