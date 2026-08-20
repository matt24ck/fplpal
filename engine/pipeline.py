"""Live pipeline: 2026-27 API snapshots -> projections, ratings, and a draft.

The bridge from archived bootstrap/fixtures snapshots to model-ready output —
the core of the nightly refresh job. Everything downstream of the snapshots
is the exact machinery the backtests validated; the live season enters as
future player-fixture rows in the canonical player-GW shape with NaN stats,
which is precisely the cold-start shape the models were trained to handle
(priors + price + position).

Flow per refresh:

1. Latest ``bootstrap_static`` + ``fixtures`` snapshots -> future rows for the
   next ``horizon`` gameweeks (one row per player per fixture).
2. Minutes and event-rate models fit on the full historical archive — which,
   in season, includes the live season's finished fixtures appended by
   ``engine.ingest.played_gw`` — so the models retrain on current form.
   Features for future rows are computed one GW at a time (concat history +
   that GW only), so phantom future rows never contaminate each other's
   history, and each GW's frame keeps only that GW's future fixtures so
   played live-season rows never leak into the projection output.
3. Live status flags overlay minutes multiplicatively (``chance_of_playing``;
   injured/suspended -> 0, doubtful default 75%).
4. Team strength fits on all history; live team names that drifted from the
   archive's ("Ipswich Town" vs "Ipswich") are aliased, and teams with no
   meaningful recent data (Coventry, Hull) fall to the promoted prior.
5. Points assembly + per-GW aggregation + position ratings (blend weights
   fitted on the 2025-26 replay, cached in ``data/models/``) + the optimal
   GW1 draft squad.

Outputs land in ``data/live/`` as parquet with provenance columns
(``data_snapshot``, ``computed_at``) — the chat layer cites these.

Run: ``python -m engine.pipeline``  (add ``--refit-ratings`` to rebuild the
cached rating weights from a fresh 2025-26 replay)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from engine.config.season import ELEMENT_TYPE_TO_POSITION, load_season
from engine.features.historical_gw import FLOAT_COLS, INT_COLS, NULLABLE_INT_COLS
from engine.features.matches import load_matches
from engine.ingest.played_gw import LIVE_SEASON, TEAM_ALIASES
from engine.ingest.snapshot import latest_snapshot
from engine.models.event_rates import EventRatesModel
from engine.models.minutes import MinutesModel, build_minutes_dataset
from engine.models.points import (
    ASSEMBLY_COLS,
    PLAYER_GW_PATH,
    PointsAssembler,
    aggregate_gw,
    fixture_context,
)
from engine.models.ratings import DEFAULT_HORIZON, RatingsModel, add_subscores, build_windows
from engine.models.team_strength import TeamStrengthModel
from engine.optimize.squad import optimize_squad

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = REPO_ROOT / "data" / "live"
WEIGHTS_PATH = REPO_ROOT / "data" / "models" / "ratings_weights.json"

# LIVE_SEASON and TEAM_ALIASES live in engine.ingest.played_gw (the season-
# lifecycle owner) — re-exported here for existing importers.
__all__ = ["LIVE_SEASON", "TEAM_ALIASES", "build_future_rows", "build_live_projections"]


def build_future_rows(
    bootstrap: dict, fixtures: list[dict], horizon: int, season: str = LIVE_SEASON
) -> tuple[pd.DataFrame, dict[int, float]]:
    """Future player-fixture rows in canonical player-GW shape + availability map."""
    events = {e["id"]: e for e in bootstrap["events"]}
    next_ev = next(
        (e["id"] for e in bootstrap["events"] if e.get("is_next")),
        min(e["id"] for e in bootstrap["events"] if not e["finished"]),
    )
    gws = [g for g in range(next_ev, next_ev + horizon) if g in events]
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}

    els = pd.DataFrame(bootstrap["elements"])
    els = els[els["element_type"].isin(ELEMENT_TYPE_TO_POSITION)].copy()

    fx = pd.DataFrame(fixtures)
    fx = fx[fx["event"].isin(gws)].copy()
    fx["kickoff_time"] = pd.to_datetime(fx["kickoff_time"], utc=True, errors="coerce")
    for ev, d in fx.groupby("event"):
        fx.loc[d.index, "kickoff_time"] = d["kickoff_time"].fillna(
            pd.Timestamp(events[ev]["deadline_time"], tz="UTC")
        )

    sides = pd.concat(
        [
            fx.rename(columns={"team_h": "team_id", "team_a": "opponent_id"}).assign(was_home=True)[
                ["id", "event", "kickoff_time", "team_id", "opponent_id", "was_home"]
            ],
            fx.rename(columns={"team_a": "team_id", "team_h": "opponent_id"}).assign(
                was_home=False
            )[["id", "event", "kickoff_time", "team_id", "opponent_id", "was_home"]],
        ],
        ignore_index=True,
    )
    rows = sides.merge(els, left_on="team_id", right_on="team", suffixes=("", "_el"))

    out = pd.DataFrame(
        {
            "season": season,
            "gw": rows["event"].astype(int),
            "fixture": rows["id"].astype(int),
            "kickoff_time": rows["kickoff_time"],
            "element": rows["id_el"].astype(int),
            "code": rows["code"].astype("Int64"),
            "player": (rows["first_name"] + " " + rows["second_name"]).str.strip(),
            "position": rows["element_type"].map(ELEMENT_TYPE_TO_POSITION),
            "team": rows["team_id"].map(teams),
            "opponent": rows["opponent_id"].map(teams),
            "team_id": rows["team_id"].astype("Int64"),
            "opponent_id": rows["opponent_id"].astype("Int64"),
            "was_home": rows["was_home"].astype(bool),
        }
    )
    for col in NULLABLE_INT_COLS:
        out[col] = pd.Series(pd.NA, index=out.index, dtype="Int64")
    for col in INT_COLS:
        out[col] = 0
    out["price"] = rows["now_cost"].astype(int).to_numpy()
    for col in FLOAT_COLS:
        out[col] = pd.Series(pd.NA, index=out.index, dtype="Float64")

    chance = pd.to_numeric(els["chance_of_playing_next_round"], errors="coerce")
    avail = {}
    for el_id, status, ch in zip(els["id"], els["status"], chance):
        if status == "a":
            avail[int(el_id)] = 1.0
        elif not np.isnan(ch):
            avail[int(el_id)] = float(ch) / 100.0
        else:
            avail[int(el_id)] = 0.75 if status == "d" else 0.0
    return out, avail


def load_ratings_model(refit: bool = False) -> RatingsModel:
    """Rating blend weights, cached from a 2025-26 replay fit."""
    model = RatingsModel()
    if WEIGHTS_PATH.exists() and not refit:
        data = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
        model.weights_ = {pos: pd.Series(w) for pos, w in data.items()}
        return model
    from engine.models.points import replay_season

    print("fitting rating weights from a 2025-26 replay (cached afterwards)...")
    proj, _ = replay_season("2025-26")
    model.fit(add_subscores(build_windows(proj, DEFAULT_HORIZON)))
    WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEIGHTS_PATH.write_text(
        json.dumps({pos: w.round(4).to_dict() for pos, w in model.weights_.items()}, indent=2),
        encoding="utf-8",
    )
    return model


def build_live_projections(
    horizon: int = DEFAULT_HORIZON, season: str = LIVE_SEASON, refit_ratings: bool = False
) -> dict[str, pd.DataFrame]:
    bs_snap = latest_snapshot("bootstrap_static")
    fx_snap = latest_snapshot("fixtures")
    if bs_snap is None or fx_snap is None:
        raise SystemExit("no snapshots archived — run: python -m engine.ingest.snapshot")
    bs_path, bootstrap = bs_snap
    _, fixtures = fx_snap
    as_of = bs_path.stem.replace(".json", "")

    hist = pd.read_parquet(PLAYER_GW_PATH)
    future, avail = build_future_rows(bootstrap, fixtures, horizon, season)
    gws = sorted(future["gw"].unique())
    print(
        f"snapshot {as_of}: {future['element'].nunique()} players, "
        f"GW{gws[0]}-{gws[-1]}, {future['fixture'].nunique()} fixtures"
    )

    print("fitting minutes + event-rate models on the full archive...")
    mm = MinutesModel().fit(build_minutes_dataset(hist).dropna(subset=["y_class"]))
    rm = EventRatesModel(season=season).fit(hist)

    tm = TeamStrengthModel().fit(load_matches())
    for live_name, hist_name in TEAM_ALIASES.items():
        if hist_name in tm.attack_ and live_name not in tm.attack_:
            tm.attack_[live_name] = tm.attack_[hist_name]
            tm.defence_[live_name] = tm.defence_[hist_name]
            tm.weighted_n_[live_name] = tm.weighted_n_.get(hist_name, 0.0)
    fixtures_df = (
        future[["season", "fixture", "team", "opponent", "was_home"]]
        .query("was_home")
        .drop_duplicates("fixture")
        .rename(columns={"team": "home", "opponent": "away"})
    )
    ctx = fixture_context(tm, fixtures_df)

    parts = []
    for g in gws:
        fut_g = future[future["gw"] == g]
        fut_fixtures = set(fut_g["fixture"])
        pg_g = pd.concat([hist, fut_g], ignore_index=True)
        md = build_minutes_dataset(pg_g)
        # Once played-GW ingest appends live-season rows to the archive,
        # season == live no longer means "future" — select this GW's future
        # fixtures explicitly so played rows never enter the projection frame.
        rows_m = md[(md["season"] == season) & md["fixture"].isin(fut_fixtures)]
        mp = MinutesModel.apply_availability(
            mm.predict(rows_m), rows_m["element"].map(avail).to_numpy(dtype=float)
        )
        minutes_df = rows_m[["season", "fixture", "element"]].join(mp)
        rates_g = rm.transform(pg_g)
        base = rates_g.loc[
            (rates_g["season"] == season) & rates_g["fixture"].isin(fut_fixtures), ASSEMBLY_COLS
        ]
        parts.append(base.merge(minutes_df, on=["season", "fixture", "element"], how="inner"))
        print(f"  GW{g}: {len(parts[-1]):,} player-fixture rows")

    df = pd.concat(parts, ignore_index=True).merge(
        ctx, on=["season", "fixture", "team"], how="inner"
    )
    proj = PointsAssembler(load_season(season), rm).project(df)
    per_gw = aggregate_gw(proj)
    windows = add_subscores(build_windows(proj, horizon))
    windows["rating"] = load_ratings_model(refit_ratings).rate(windows)

    # "Known as" display name from bootstrap (e.g. "Evanilson", not "Barbosa")
    # — carried per-code so the UI never has to guess a surname from ``player``.
    web_names = {int(e["code"]): e.get("web_name") for e in bootstrap["elements"]}
    now = pd.Timestamp.now(tz="UTC").isoformat()
    for frame in (proj, per_gw, windows):
        frame["web_name"] = frame["code"].map(web_names)
        frame["data_snapshot"] = as_of
        frame["computed_at"] = now
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    proj.to_parquet(LIVE_DIR / "projections_fixture.parquet", index=False)
    per_gw.to_parquet(LIVE_DIR / "projections_gw.parquet", index=False)
    windows.to_parquet(LIVE_DIR / "ratings.parquet", index=False)
    print(f"wrote projections + ratings -> {LIVE_DIR}")

    return {"projections": proj, "per_gw": per_gw, "ratings": windows}


def _print_summary(out: dict[str, pd.DataFrame], horizon: int) -> None:
    proj = out["projections"]
    ratings = out["ratings"]

    new_players = proj.groupby("code")["exposure_90"].max()
    zeroed = {e for e, a in proj.groupby("element")["p_start"].max().items() if a == 0}
    print(
        f"\npool: {proj['code'].nunique()} players | no PL history (pure priors): "
        f"{int((new_players == 0).sum())} | zeroed by status flags: {len(zeroed)}"
    )

    totals = (
        proj.groupby(["code", "player", "team", "position"], observed=True)
        .agg(xpts=("xpts", "sum"), price=("price", "first"))
        .reset_index()
    )
    print(f"\ntop 10 projected, next {horizon} GWs:")
    for r in totals.nlargest(10, "xpts").itertuples():
        print(f"  {r.position} {r.player} ({r.team}) £{r.price / 10:.1f}m — {r.xpts:.1f} xPts")

    print("\ntop-rated per position:")
    for pos in ("GKP", "DEF", "MID", "FWD"):
        top = ratings[ratings["position"] == pos].nlargest(3, "rating")
        line = ", ".join(f"{r.player} {r.rating:.0f}" for r in top.itertuples())
        print(f"  {pos}: {line}")

    pool = (
        proj.sort_values("gw")
        .groupby("code", as_index=False)
        .agg(
            player=("player", "first"),
            team=("team", "first"),
            position=("position", "first"),
            price=("price", "first"),
            xpts=("xpts", "sum"),
            p_play=("p_start", "mean"),
        )
    )
    sol = optimize_squad(pool)
    print(f"\n== optimal GW1 draft, £{sol.cost / 10:.1f}m ==")
    print(sol.summary())


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh live projections from snapshots.")
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    parser.add_argument("--refit-ratings", action="store_true")
    args = parser.parse_args()
    out = build_live_projections(horizon=args.horizon, refit_ratings=args.refit_ratings)
    _print_summary(out, args.horizon)


if __name__ == "__main__":
    import sys

    if (sys.stdout.encoding or "").lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
