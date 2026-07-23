"""Download the vaastav/Fantasy-Premier-League historical archive.

The official API serves per-GW player data for the *current* season only
(past seasons exist only as season totals via ``history_past``), so this
community archive is the training corpus for every model (PLAN.md §3).

Files are fetched over HTTPS from raw.githubusercontent.com — no git
involved — and downloads are idempotent: existing files are skipped unless
``--force``. Missing files (early seasons lack some) are reported, not fatal.

    python -m engine.ingest.historical
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO_ROOT / "data" / "historical" / "vaastav"
BASE = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"

# 2016-17 .. 2025-26
SEASONS = [f"{y}-{str(y + 1)[2:]}" for y in range(2016, 2026)]

FILES = [
    "gws/merged_gw.csv",  # per-player per-GW rows — the core training data
    "players_raw.csv",  # season-end player attributes (position, team, cost)
    "teams.csv",  # team id -> name mapping for the season
    "fixtures.csv",  # season fixture list with scores
]


def historical_root() -> Path:
    override = os.environ.get("FPL_HISTORICAL_DIR")
    return Path(override) if override else DEFAULT_ROOT


def download_season(
    client: httpx.Client, season: str, root: Path, force: bool = False
) -> tuple[list[str], list[str]]:
    """Fetch one season's files. Returns (downloaded/cached, missing)."""
    got: list[str] = []
    missing: list[str] = []
    for rel in FILES:
        dest = root / season / rel.replace("/", os.sep)
        if dest.exists() and not force:
            got.append(f"{rel} (cached)")
            continue
        resp = client.get(f"{BASE}/{season}/{rel}")
        if resp.status_code == 404:
            missing.append(rel)
            continue
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        got.append(f"{rel} ({len(resp.content) / 1e6:.1f} MB)")
    return got, missing


# Season-independent files at the archive root. master_team_list.csv maps
# (season, season-scoped team id) -> team name — the only team-name source for
# early seasons that have no teams.csv upstream.
ROOT_FILES = ["master_team_list.csv"]


def run_download(root: Path | None = None, force: bool = False) -> None:
    root = root or historical_root()
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        for rel in ROOT_FILES:
            dest = root / rel
            if dest.exists() and not force:
                print(f"{rel}: cached")
            else:
                resp = client.get(f"{BASE}/{rel}")
                if resp.status_code == 404:
                    print(f"{rel}: missing upstream")
                else:
                    resp.raise_for_status()
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(resp.content)
                    print(f"{rel}: downloaded ({len(resp.content) / 1e6:.1f} MB)")
        for season in SEASONS:
            got, missing = download_season(client, season, root, force)
            line = f"{season}: {len(got)}/{len(FILES)} files"
            if missing:
                line += f"  (missing upstream: {', '.join(missing)})"
            print(line)
            for item in got:
                print(f"    {item}")
    print(f"\narchive root: {root}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the vaastav FPL historical archive.")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    args = parser.parse_args()
    run_download(args.root, args.force)


if __name__ == "__main__":
    main()
