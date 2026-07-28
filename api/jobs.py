"""Background jobs for a deployed instance (PLAN §7: APScheduler at MVP scope).

One service owns everything: on startup (``JOBS_ENABLED=1``) a daemon thread

1. seeds the data volume if it's empty — historical archive download, feature
   builds, first snapshot, played-GW catch-up, first pipeline run — all
   idempotent, then
2. starts the schedule: hourly API snapshot, nightly played-GW ingest
   (finished fixtures appended to the canonical table), nightly pipeline
   refresh (followed by a live-store reload so the API serves the new
   parquets).

Local dev leaves ``JOBS_ENABLED`` unset and runs the same steps manually
(``python -m engine.ingest.snapshot`` / ``python -m engine.pipeline``).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

log = logging.getLogger("api.jobs")

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYER_GW = REPO_ROOT / "data" / "features" / "player_gw.parquet"
MATCHES = REPO_ROOT / "data" / "features" / "matches.parquet"
LIVE_PROJ = REPO_ROOT / "data" / "live" / "projections_fixture.parquet"
RATINGS_WEIGHTS = REPO_ROOT / "data" / "models" / "ratings_weights.json"

SNAPSHOT_MINUTE = 5  # hourly at :05 UTC
INGEST_HOUR_UTC = 1  # nightly at 01:15 UTC — before the pipeline, so the
INGEST_MINUTE = 15  # night after a GW finishes retrains on its data
PIPELINE_HOUR_UTC = 2  # nightly at 02:30 UTC
PIPELINE_MINUTE = 30


def _run_module(module: str) -> None:
    """Run an engine module CLI as a subprocess (their __main__ blocks are the
    documented, idempotent entry points)."""
    log.info("jobs: running %s", module)
    subprocess.run([sys.executable, "-m", module], check=True, cwd=REPO_ROOT, timeout=3600)


def snapshot_job() -> None:
    from engine.ingest.snapshot import run_core_snapshot

    run_core_snapshot()


def played_gw_job() -> None:
    from engine.ingest.played_gw import ingest

    ingest()


def pipeline_job() -> None:
    from engine.pipeline import build_live_projections

    build_live_projections()
    from api.data import get_store

    try:
        get_store().reload()
        log.info("jobs: live store reloaded")
    except FileNotFoundError:
        log.warning("jobs: pipeline ran but live data still missing")


def seed_if_needed() -> None:
    """Make an empty volume serviceable. Every step is skipped when its output
    already exists, so this is safe to run on every boot."""
    if not PLAYER_GW.exists():
        log.info("jobs: no historical archive — downloading (one-time, ~45 MB)")
        _run_module("engine.ingest.historical")
        _run_module("engine.features.historical_gw")
    if not MATCHES.exists():
        _run_module("engine.features.matches")
    if not RATINGS_WEIGHTS.exists():
        log.warning(
            "jobs: no cached rating weights (data/models/ratings_weights.json) — "
            "the first pipeline run will refit them via a full 2025-26 replay, "
            "which takes a long time; committing the cache file avoids this"
        )
    from engine.ingest.snapshot import latest_snapshot

    if latest_snapshot("bootstrap_static") is None:
        log.info("jobs: no snapshots — taking the first one")
        snapshot_job()
    try:
        # Mid-season (re)deploys catch up on finished GWs before the first
        # pipeline; pre-season and up-to-date volumes make this a cheap no-op.
        played_gw_job()
    except Exception:
        log.exception("jobs: played-GW ingest failed — pipeline proceeds on existing history")
    if not LIVE_PROJ.exists():
        log.info("jobs: no live projections — running the first pipeline")
        pipeline_job()


def _bootstrap_then_schedule() -> None:
    try:
        seed_if_needed()
    except Exception:
        log.exception("jobs: seeding failed — scheduler starts anyway; will retry on schedule")

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(
        snapshot_job,
        CronTrigger(minute=SNAPSHOT_MINUTE, timezone="UTC"),
        id="hourly-snapshot",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    sched.add_job(
        played_gw_job,
        CronTrigger(hour=INGEST_HOUR_UTC, minute=INGEST_MINUTE, timezone="UTC"),
        id="played-gw-ingest",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    sched.add_job(
        pipeline_job,
        CronTrigger(hour=PIPELINE_HOUR_UTC, minute=PIPELINE_MINUTE, timezone="UTC"),
        id="nightly-pipeline",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    sched.start()
    log.info(
        "jobs: scheduled — snapshot hourly at :%02d, played-GW ingest daily %02d:%02d, "
        "pipeline daily %02d:%02d UTC",
        SNAPSHOT_MINUTE,
        INGEST_HOUR_UTC,
        INGEST_MINUTE,
        PIPELINE_HOUR_UTC,
        PIPELINE_MINUTE,
    )


def start_background() -> None:
    """Called from the app lifespan when JOBS_ENABLED=1. Returns immediately so
    the server binds its port; seeding continues in a daemon thread."""
    threading.Thread(target=_bootstrap_then_schedule, name="jobs", daemon=True).start()


def jobs_enabled() -> bool:
    return os.environ.get("JOBS_ENABLED", "") == "1"
