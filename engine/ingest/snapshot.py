"""Raw snapshot archive: every FPL API pull is preserved as gzipped JSON.

Downstream tables can always be rebuilt from these files, and schema drift in
the unofficial API never loses data — validation failures happen at parse
time, after the bytes are safely on disk.

Layout: ``data/snapshots/<name>/<UTC timestamp>.json.gz``

Run the core snapshot job (bootstrap-static + fixtures + set-piece notes):

    python -m engine.ingest.snapshot
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.ingest.fpl_api import FplApi, MaintenanceError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO_ROOT / "data" / "snapshots"


def snapshot_root() -> Path:
    override = os.environ.get("FPL_SNAPSHOT_DIR")
    return Path(override) if override else DEFAULT_ROOT


def save_snapshot(name: str, payload: Any, root: Path | None = None) -> Path:
    root = root or snapshot_root()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = root / name / f"{stamp}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    return path


def latest_snapshot(name: str, root: Path | None = None) -> tuple[Path, Any] | None:
    root = root or snapshot_root()
    files = sorted((root / name).glob("*.json.gz")) if (root / name).is_dir() else []
    if not files:
        return None
    return files[-1], load_snapshot(files[-1])


def load_snapshot(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def run_core_snapshot(root: Path | None = None) -> dict[str, Any] | None:
    """The scheduled-job body: pull and archive the always-wanted endpoints.

    Returns the bootstrap payload, or None if the API is in maintenance.
    """
    try:
        return _pull_all(root)
    except MaintenanceError as exc:
        print(f"[{datetime.now(UTC):%Y-%m-%d %H:%M}Z] {exc}")
        return None


def _pull_all(root: Path | None) -> dict[str, Any]:
    with FplApi() as api:
        bootstrap = api.bootstrap_static()
        path = save_snapshot("bootstrap_static", bootstrap, root)
        print(f"archived {path}")

        fixtures = api.fixtures()
        path = save_snapshot("fixtures", fixtures, root)
        print(f"archived {path}")

        try:
            notes = api.set_piece_notes()
            path = save_snapshot("set_piece_notes", notes, root)
            print(f"archived {path}")
        except Exception as exc:  # noqa: BLE001 — non-critical endpoint; don't fail the job
            print(f"set-piece notes unavailable: {exc}")

    _print_summary(bootstrap, fixtures)
    return bootstrap


def _print_summary(bootstrap: dict[str, Any], fixtures: list[dict[str, Any]]) -> None:
    events = bootstrap.get("events", [])
    elements = bootstrap.get("elements", [])
    teams = bootstrap.get("teams", [])

    print("\n--- FPL API summary ---")
    print(f"teams: {len(teams)}  players: {len(elements)}  gameweeks: {len(events)}")

    if events:
        gw1 = events[0]
        print(f"GW1 deadline: {gw1.get('deadline_time')}")
        current = next((e for e in events if e.get("is_current")), None)
        nxt = next((e for e in events if e.get("is_next")), None)
        finished = [e for e in events if e.get("finished")]
        print(
            f"current GW: {current['id'] if current else 'none'}"
            f"  next GW: {nxt['id'] if nxt else 'none'}"
            f"  finished GWs: {len(finished)}"
        )

    if elements:
        fresh = all(p.get("total_points", 0) == 0 for p in elements)
        print(f"season state: {'pre-season (all players on 0 pts)' if fresh else 'in progress'}")
        priciest = max(elements, key=lambda p: p.get("now_cost", 0))
        print(
            f"priciest player: {priciest.get('web_name')} £{priciest.get('now_cost', 0) / 10:.1f}m"
        )

    scheduled = [f for f in fixtures if f.get("kickoff_time")]
    if scheduled:
        first = min(scheduled, key=lambda f: f["kickoff_time"])
        print(f"first kickoff: {first['kickoff_time']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive a snapshot of the FPL API.")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="snapshot root directory (default: data/snapshots, or FPL_SNAPSHOT_DIR)",
    )
    parser.add_argument(
        "--watch-minutes",
        type=float,
        default=None,
        metavar="N",
        help="poll every N minutes until the API is up and one snapshot succeeds, "
        "then exit — for catching the season launch",
    )
    args = parser.parse_args()

    if args.watch_minutes is None:
        run_core_snapshot(args.root)
        return

    while True:
        if run_core_snapshot(args.root) is not None:
            print("snapshot captured — watch complete")
            return
        time.sleep(args.watch_minutes * 60)


if __name__ == "__main__":
    main()
