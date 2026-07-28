"""Live accuracy monitoring: deadline-frozen projections vs realized points.

The nightly pipeline overwrites ``data/live/`` in place, so the site's
credibility surface needs a point-in-time record of what was claimed before
each deadline. This module owns that record and its scoring:

1. **Freeze** (after every pipeline run): copy the per-fixture projection
   rows of every visible gameweek whose deadline is still in the future to
   ``data/accuracy/frozen/gw{N}.parquet``, adding FPL's own ``ep_next`` from
   the latest bootstrap snapshot (the baseline the engine claims to beat).
   Pre-deadline runs overwrite; post-deadline runs never touch the file — so
   what remains after a deadline is exactly what the site was serving when
   the deadline hit.

2. **Score** (after every played-GW ingest): join each frozen gameweek to
   realized rows in the canonical player-GW table on (gw, element, fixture)
   — postponed-out fixtures never match and are disclosed, not silently
   dropped — collapse to player level (DGWs sum), and compute the PLAN §8
   suite per GW: RMSE/MAE, within-position Spearman, top-10 overlap, captain
   pick vs hindsight, clean-sheet and start Briers, and the xPts/actual
   ratio, against the frozen ``ep_next`` and a live last-4-form baseline.
   Every run rescores everything from the frozen files (cheap, idempotent,
   self-healing after postponement top-ups) and writes
   ``data/accuracy/accuracy.json`` + ``player_detail.parquet``, which the
   public ``/accuracy`` endpoints serve.

Run: ``python -m engine.accuracy``  (``--freeze-only`` / ``--score-only``)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from engine.ingest.played_gw import LIVE_SEASON
from engine.ingest.snapshot import latest_snapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = REPO_ROOT / "data" / "live"
DEFAULT_ACCURACY_DIR = REPO_ROOT / "data" / "accuracy"
DEFAULT_FEATURES_DIR = REPO_ROOT / "data" / "features"

# Frozen columns the scorer consumes (the frozen files carry the full
# projection frame; realized total_points/minutes/... come from the join, so
# the projection frame's phantom NaN stat columns are simply not selected).
SCORE_COLS = [
    "season", "gw", "fixture", "element", "code", "player", "team", "position",
    "price", "xpts", "p_cs", "p_start", "ep_next", "ep_next_event",
]  # fmt: skip


def accuracy_dir() -> Path:
    override = os.environ.get("FPL_ACCURACY_DIR")
    return Path(override) if override else DEFAULT_ACCURACY_DIR


def report_path(root: Path | None = None) -> Path:
    return (root or accuracy_dir()) / "accuracy.json"


def detail_path(root: Path | None = None) -> Path:
    return (root or accuracy_dir()) / "player_detail.parquet"


# -- freeze -------------------------------------------------------------------


def freeze_projections(
    live_dir: Path | None = None,
    acc_dir: Path | None = None,
    snapshot_root: Path | None = None,
    now: pd.Timestamp | None = None,
) -> list[int]:
    """Freeze current per-fixture projections for every gameweek whose
    deadline is still ahead. Returns the frozen GW numbers."""
    live_dir = live_dir or LIVE_DIR
    frozen_dir = (acc_dir or accuracy_dir()) / "frozen"
    now = now if now is not None else pd.Timestamp.now(tz="UTC")

    proj_file = live_dir / "projections_fixture.parquet"
    if not proj_file.exists():
        print("accuracy: no live projections yet — nothing to freeze")
        return []
    snap = latest_snapshot("bootstrap_static", snapshot_root)
    if snap is None:
        print("accuracy: no bootstrap snapshot — cannot resolve deadlines; skipping freeze")
        return []
    _, bootstrap = snap

    proj = pd.read_parquet(proj_file)
    events = {int(e["id"]): e for e in bootstrap.get("events", [])}
    next_event = next((int(e["id"]) for e in bootstrap["events"] if e.get("is_next")), 0)
    ep_next = {
        int(e["id"]): pd.to_numeric(e.get("ep_next"), errors="coerce")
        for e in bootstrap.get("elements", [])
    }

    frozen: list[int] = []
    for gw in sorted(int(g) for g in proj["gw"].unique()):
        event = events.get(gw)
        if event is None or not event.get("deadline_time"):
            continue
        if pd.Timestamp(event["deadline_time"]) <= now:
            continue  # deadline passed — the last pre-deadline freeze stands
        d = proj[proj["gw"] == gw].copy()
        d["ep_next"] = d["element"].map(ep_next).astype(float)
        d["ep_next_event"] = next_event
        d["deadline_time"] = event["deadline_time"]
        d["frozen_at"] = now.isoformat()
        frozen_dir.mkdir(parents=True, exist_ok=True)
        target = frozen_dir / f"gw{gw}.parquet"
        tmp = target.with_suffix(".parquet.tmp")
        d.to_parquet(tmp, index=False)
        tmp.replace(target)
        frozen.append(gw)

    if frozen:
        print(f"accuracy: froze projections for GW {', '.join(map(str, frozen))}")
    else:
        print("accuracy: no gameweek with a future deadline — nothing frozen")
    return frozen


# -- scoring ------------------------------------------------------------------


def _round(x: float | None, nd: int = 3) -> float | None:
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def _rmse(pred: pd.Series, actual: pd.Series) -> float:
    return float(np.sqrt(np.mean((pred.to_numpy(float) - actual.to_numpy(float)) ** 2)))


def _mae(pred: pd.Series, actual: pd.Series) -> float:
    return float(np.mean(np.abs(pred.to_numpy(float) - actual.to_numpy(float))))


def _rank_corr(players: pd.DataFrame, col: str, by: list[str]) -> float | None:
    """Mean Spearman(col, total_points) within ``by`` cells on played rows,
    weighted by cell size — the harness metric on player-GW level."""
    corrs, ns = [], []
    for _, d in players[players["minutes"] > 0].groupby(by, observed=True):
        d = d.dropna(subset=[col])
        if len(d) < 8 or d[col].nunique() < 2 or d["total_points"].nunique() < 2:
            continue
        rho = spearmanr(d[col], d["total_points"]).statistic
        if not np.isnan(rho):
            corrs.append(rho)
            ns.append(len(d))
    return float(np.average(corrs, weights=ns)) if corrs else None


def _topk_overlap(players: pd.DataFrame, col: str, by: list[str], k: int = 10) -> float | None:
    hits, total = 0, 0
    for _, d in players.groupby(by, observed=True):
        d = d.dropna(subset=[col])
        if len(d) < 15:
            continue
        hits += len(set(d.nlargest(k, col)["code"]) & set(d.nlargest(k, "total_points")["code"]))
        total += k
    return hits / total if total else None


def _baseline_metrics(players: pd.DataFrame, col: str) -> dict:
    d = players.dropna(subset=[col])
    if d.empty:
        return {"rmse": None, "mae": None, "rank_corr": None, "top10_overlap": None}
    return {
        "rmse": _round(_rmse(d[col], d["total_points"])),
        "mae": _round(_mae(d[col], d["total_points"])),
        "rank_corr": _round(_rank_corr(d, col, ["position"])),
        "top10_overlap": _round(_topk_overlap(d, col, ["position"])),
    }


def _captain(players: pd.DataFrame, col: str) -> dict | None:
    d = players.dropna(subset=[col])
    if d.empty or d[col].nunique() < 2:
        return None
    pick = d.loc[d[col].idxmax()]
    return {"player": str(pick["player"]), "points": int(pick["total_points"])}


def _score_one(frozen: pd.DataFrame, realized: pd.DataFrame, pg_before: pd.DataFrame) -> dict:
    """Score one frozen gameweek against its realized rows. Returns the
    report entry plus the player-level detail frame under ``"players"``."""
    gw = int(frozen["gw"].iloc[0])
    matched = frozen[SCORE_COLS].merge(
        realized[["fixture", "element", "total_points", "minutes", "clean_sheets", "starts"]],
        on=["fixture", "element"],
        how="inner",
    )

    # Last-4-fixture form entering this GW (live season only; GW1 -> 0),
    # the naive baseline the backtests use.
    last4 = (
        pg_before.sort_values("kickoff_time")
        .groupby("element")["total_points"]
        .agg(lambda s: float(s.tail(4).mean()))
    )
    matched["form4"] = matched["element"].map(last4).fillna(0.0)

    players = matched.groupby("code", as_index=False).agg(
        player=("player", "first"),
        team=("team", "first"),
        position=("position", "first"),
        price=("price", "first"),
        n_fixtures=("fixture", "size"),
        xpts=("xpts", "sum"),
        total_points=("total_points", "sum"),
        minutes=("minutes", "sum"),
        ep_next=("ep_next", "first"),
        form4=("form4", "first"),
    )
    players.insert(0, "gw", gw)

    # ep_next is FPL's projection for the *next* event as of the freeze — a
    # fair baseline only when this GW was next at freeze time.
    ep_valid = int(frozen["ep_next_event"].iloc[0]) == gw
    if not ep_valid:
        players["ep_next"] = np.nan
    played = players[players["minutes"] > 0]
    hindsight = players.loc[players["total_points"].idxmax()] if len(players) else None

    entry = {
        "gw": gw,
        "deadline_time": str(frozen["deadline_time"].iloc[0]),
        "frozen_at": str(frozen["frozen_at"].iloc[0]),
        "data_snapshot": str(frozen["data_snapshot"].iloc[0]),
        "fixtures_frozen": int(frozen["fixture"].nunique()),
        "fixtures_scored": int(matched["fixture"].nunique()),
        "players": int(len(players)),
        "played": int(len(played)),
        "model": {
            "rmse": _round(_rmse(players["xpts"], players["total_points"])),
            "mae": _round(_mae(players["xpts"], players["total_points"])),
            "rank_corr": _round(_rank_corr(players, "xpts", ["position"])),
            "top10_overlap": _round(_topk_overlap(players, "xpts", ["position"])),
        },
        "ep_next": _baseline_metrics(players, "ep_next")
        if ep_valid
        else {"rmse": None, "mae": None, "rank_corr": None, "top10_overlap": None},
        "form4": _baseline_metrics(players, "form4"),
        "captain": {
            "model": _captain(players, "xpts"),
            "ep_next": _captain(players, "ep_next") if ep_valid else None,
            "hindsight": None
            if hindsight is None
            else {"player": str(hindsight["player"]), "points": int(hindsight["total_points"])},
        },
        "xpts_total_ratio": _round(
            float(players["xpts"].sum() / max(players["total_points"].sum(), 1))
        ),
        "cs_brier": _cs_brier(matched),
        "start_brier": _start_brier(matched),
    }
    return {"entry": entry, "players": players}


def _cs_brier(matched: pd.DataFrame) -> float | None:
    """Team-level clean-sheet calibration from a 60+ minute GKP/DEF row."""
    d = matched[(matched["minutes"] >= 60) & matched["position"].isin(["GKP", "DEF"])]
    if d.empty:
        return None
    team_cs = d.groupby(["fixture", "team"], as_index=False).agg(
        p_cs=("p_cs", "first"), cs=("clean_sheets", "max")
    )
    return _round(float(np.mean((team_cs["p_cs"] - team_cs["cs"]) ** 2)), 4)


def _start_brier(matched: pd.DataFrame) -> float | None:
    d = matched[matched["starts"].notna()]
    if d.empty:
        return None
    return _round(float(np.mean((d["p_start"] - d["starts"].astype(float)) ** 2)), 4)


def _aggregate(entries: list[dict], detail: pd.DataFrame) -> dict | None:
    """Season-to-date roll-up over all scored GWs (pooled where possible)."""
    if not entries:
        return None
    pooled_model = {
        "rmse": _round(_rmse(detail["xpts"], detail["total_points"])),
        "mae": _round(_mae(detail["xpts"], detail["total_points"])),
        "rank_corr": _round(_rank_corr(detail, "xpts", ["gw", "position"])),
        "top10_overlap": _round(_topk_overlap(detail, "xpts", ["gw", "position"])),
    }
    ep_rows = detail.dropna(subset=["ep_next"])
    ep_gws = [e for e in entries if e["ep_next"]["rank_corr"] is not None]
    pooled_ep = {
        "rmse": _round(_rmse(ep_rows["ep_next"], ep_rows["total_points"]))
        if len(ep_rows)
        else None,
        "mae": _round(_mae(ep_rows["ep_next"], ep_rows["total_points"])) if len(ep_rows) else None,
        "rank_corr": _round(_rank_corr(ep_rows, "ep_next", ["gw", "position"])),
        "top10_overlap": _round(_topk_overlap(ep_rows, "ep_next", ["gw", "position"])),
    }

    def _avg_captain(key: str) -> float | None:
        pts = [e["captain"][key]["points"] for e in entries if e["captain"][key]]
        return _round(float(np.mean(pts)), 2) if pts else None

    beat = [
        e
        for e in ep_gws
        if e["model"]["rank_corr"] is not None
        and e["model"]["rank_corr"] > e["ep_next"]["rank_corr"]
    ]
    briers = [e["cs_brier"] for e in entries if e["cs_brier"] is not None]
    return {
        "gws_scored": len(entries),
        "model": pooled_model,
        "ep_next": pooled_ep,
        "beat_ep_next_rank_corr": {"gws": len(beat), "of": len(ep_gws)},
        "captain_pts_per_gw": {
            "model": _avg_captain("model"),
            "ep_next": _avg_captain("ep_next"),
            "hindsight": _avg_captain("hindsight"),
        },
        "cs_brier": _round(float(np.mean(briers)), 4) if briers else None,
        "xpts_total_ratio": _round(
            float(detail["xpts"].sum() / max(detail["total_points"].sum(), 1))
        ),
    }


def score_accuracy(
    features_dir: Path | None = None,
    acc_dir: Path | None = None,
    season: str = LIVE_SEASON,
) -> dict:
    """Rescore every frozen gameweek that has realized rows; write the report
    JSON + player-level detail parquet. Idempotent, cheap, self-healing."""
    features_dir = features_dir or Path(
        os.environ.get("FPL_FEATURES_DIR", str(DEFAULT_FEATURES_DIR))
    )
    acc_dir = acc_dir or accuracy_dir()
    frozen_dir = acc_dir / "frozen"
    table_path = features_dir / "player_gw.parquet"

    frozen_files = sorted(frozen_dir.glob("gw*.parquet")) if frozen_dir.is_dir() else []
    pg = (
        pd.read_parquet(table_path)
        if table_path.exists()
        else pd.DataFrame(columns=["season", "gw", "element", "kickoff_time", "total_points"])
    )
    live = pg[pg["season"] == season]

    entries: list[dict] = []
    pending: list[dict] = []
    detail_parts: list[pd.DataFrame] = []
    for file in frozen_files:
        frozen = pd.read_parquet(file)
        gw = int(frozen["gw"].iloc[0])
        realized = live[live["gw"] == gw]
        if realized.empty:
            pending.append(
                {
                    "gw": gw,
                    "deadline_time": str(frozen["deadline_time"].iloc[0]),
                    "frozen_at": str(frozen["frozen_at"].iloc[0]),
                    "players": int(frozen["element"].nunique()),
                    "fixtures": int(frozen["fixture"].nunique()),
                }
            )
            continue
        scored = _score_one(frozen, realized, live[live["gw"] < gw])
        entries.append(scored["entry"])
        detail_parts.append(scored["players"])

    entries.sort(key=lambda e: e["gw"])
    pending.sort(key=lambda p: p["gw"])
    detail = (
        pd.concat(detail_parts, ignore_index=True).sort_values(["gw", "code"])
        if detail_parts
        else pd.DataFrame()
    )

    report = {
        "season": season,
        "scored_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "gws": entries,
        "pending": pending,
        "aggregate": _aggregate(entries, detail),
    }

    acc_dir.mkdir(parents=True, exist_ok=True)
    rp, dp = report_path(acc_dir), detail_path(acc_dir)
    rp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if len(detail):
        tmp = dp.with_suffix(".parquet.tmp")
        detail.to_parquet(tmp, index=False)
        tmp.replace(dp)
    print(
        f"accuracy: scored {len(entries)} GW(s), {len(pending)} pending -> {rp}"
        + (f" + {dp}" if len(detail) else "")
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze and score live projection accuracy.")
    parser.add_argument("--freeze-only", action="store_true")
    parser.add_argument("--score-only", action="store_true")
    args = parser.parse_args()
    if not args.score_only:
        freeze_projections()
    if not args.freeze_only:
        score_accuracy()


if __name__ == "__main__":
    main()
