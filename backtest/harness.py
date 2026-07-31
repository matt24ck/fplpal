"""Multi-season backtest harness (PLAN §8; TODO §2's accepted quality debt).

Replays whole seasons point-in-time through the full stack — minutes and
event-rate models fitted strictly on earlier seasons, team strength refit
before every GW, per-season scoring rules (2023-24/2024-25 had no
defensive-contribution points) — and scores each replay with the PLAN §8
metric suite: RMSE vs the last-4-form and season-PPG baselines, within-
(GW, position) Spearman, top-10 overlap, captain-pick quality, clean-sheet
and start Briers, and the total-points ratio. (FPL's ``ep_next`` baseline
only exists in live bootstrap snapshots, not the historical archive, so the
two naive baselines carry the comparison, as in the pre-launch gate.)

Because the expensive per-season work — the minutes model and 38 per-GW
team-strength fits — does not depend on the event-rate half-life, it is
computed once per season and cached, and the ``--half-lives`` sweep re-runs
only the rates fit + assembly per candidate. That turns the rate-decay
tuning (the documented Salah-decline miss) from days of compute into one run.

``--refit-weights`` refits the rating blend across seasons: NNLS on pooled
2023-24 + 2024-25 windows, validated on 2025-26 against the currently cached
weights, and (with ``--write-weights``) a final all-season fit written to
``data/models/ratings_weights.json``.

Run (long — an hour-plus for the full sweep):

    python -m backtest.harness                          # 3-season metric suite
    python -m backtest.harness --half-lives 120 180 270 365
    python -m backtest.harness --refit-weights [--write-weights]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from engine.config.season import load_season
from engine.features.matches import load_matches
from engine.models.event_rates import RATE_HALF_LIFE_DAYS, EventRatesModel
from engine.models.minutes import MinutesModel, build_minutes_dataset
from engine.models.points import (
    ASSEMBLY_COLS,
    PLAYER_GW_PATH,
    PointsAssembler,
    _rank_corr,
    _topk_overlap,
    fixture_context,
)
from engine.models.ratings import (
    DEFAULT_HORIZON,
    POOL_MIN_E_MINUTES,
    RatingsModel,
    add_subscores,
    build_windows,
)
from engine.models.team_strength import TeamStrengthModel
from engine.pipeline import WEIGHTS_PATH

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "data" / "backtest" / "harness_results.json"

SEASONS_DEFAULT = ("2023-24", "2024-25", "2025-26")
DEFAULT_HALF_LIFE = RATE_HALF_LIFE_DAYS  # the engine's live setting


# -- per-season replay with cached invariants --------------------------------


@dataclass
class SeasonInvariants:
    """The half-life-independent pieces of one season's replay."""

    season: str
    minutes_df: pd.DataFrame  # (season, fixture, element) + minutes predictions
    ctx: pd.DataFrame  # per-GW as-of team-strength fixture context


def season_invariants(
    pg: pd.DataFrame, mdata: pd.DataFrame, season: str, verbose: bool = True
) -> SeasonInvariants:
    def log(msg: str) -> None:
        if verbose:
            print(msg)

    log(f"[{season}] fitting minutes model on earlier seasons...")
    labeled = mdata.dropna(subset=["y_class"])
    mm = MinutesModel().fit(labeled[labeled["season"] < season])
    m_test = mdata[mdata["season"] == season]
    minutes_df = m_test[["season", "fixture", "element"]].join(mm.predict(m_test))

    log(f"[{season}] fitting team strength before each GW...")
    matches = load_matches()
    hold = matches[matches["season"] == season]
    ctx_parts = []
    for _, md in hold.groupby("gw"):
        tm = TeamStrengthModel().fit(matches, as_of=md["kickoff_time"].min())
        ctx_parts.append(fixture_context(tm, md))
    return SeasonInvariants(season, minutes_df, pd.concat(ctx_parts, ignore_index=True))


def project_season(
    pg: pd.DataFrame, inv: SeasonInvariants, half_life: float = DEFAULT_HALF_LIFE
) -> pd.DataFrame:
    """One replay projection frame for (season, half-life) — rates + assembly
    only; minutes and team strength come cached from the invariants."""
    season = inv.season
    hist = pg[pg["season"] <= season]  # later seasons can't inform this replay
    rm = EventRatesModel(half_life_days=half_life, season=season).fit(hist[hist["season"] < season])
    rates = rm.transform(hist)
    base = rates.loc[rates["season"] == season, ASSEMBLY_COLS]
    df = base.merge(inv.minutes_df, on=["season", "fixture", "element"], how="inner").merge(
        inv.ctx, on=["season", "fixture", "team"], how="inner"
    )
    return PointsAssembler(load_season(season), rm).project(df)


# -- the PLAN §8 metric suite ------------------------------------------------


def add_baselines(proj: pd.DataFrame, pg: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time naive baselines merged onto the projection frame:
    last-4-fixture form and season points-per-game (cold start -> 0). Also
    carries the realized ``starts`` label (not in ASSEMBLY_COLS) for the
    start-probability Brier."""
    season = proj["season"].iloc[0]
    h = pg[pg["season"] == season].sort_values(["element", "kickoff_time"])
    grp = h.groupby("element")["total_points"]
    h = h.assign(
        form4=grp.transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean()),
        ppg=grp.transform(lambda s: s.shift(1).expanding().mean()),
    )
    cols = ["season", "fixture", "element", "form4", "ppg"]
    if "starts" in h.columns and "starts" not in proj.columns:
        cols.append("starts")
    return proj.merge(h[cols], on=["season", "fixture", "element"], how="left").fillna(
        {"form4": 0.0, "ppg": 0.0}
    )


def _rmse(pred: pd.Series, actual: pd.Series) -> float:
    return float(np.sqrt(np.mean((pred.to_numpy(float) - actual.to_numpy(float)) ** 2)))


def captain_quality(proj: pd.DataFrame) -> dict:
    """Per GW: realized points of the model's captain pick (top aggregated
    xPts) vs the form baseline's pick and the hindsight-best armband."""
    agg = proj.groupby(["gw", "code"], as_index=False).agg(
        xpts=("xpts", "sum"), pts=("total_points", "sum"), form=("form4", "max")
    )
    model, naive, best = [], [], []
    for _, d in agg.groupby("gw"):
        model.append(d.loc[d["xpts"].idxmax(), "pts"])
        naive.append(d.loc[d["form"].idxmax(), "pts"])
        best.append(d["pts"].max())
    return {
        "captain_pts_per_gw": float(np.mean(model)),
        "captain_pts_form_baseline": float(np.mean(naive)),
        "captain_pts_hindsight_best": float(np.mean(best)),
    }


def cs_brier(proj: pd.DataFrame) -> float | None:
    """Team-level clean-sheet calibration: one row per (fixture, team),
    realized from a 60+ minute GKP/DEF row's clean_sheets flag."""
    d = proj[(proj["minutes"] >= 60) & proj["position"].isin(["GKP", "DEF"])]
    if d.empty:
        return None
    team_cs = d.groupby(["fixture", "team"], as_index=False).agg(
        p_cs=("p_cs", "first"), cs=("clean_sheets", "max")
    )
    return _rmse(team_cs["p_cs"], team_cs["cs"]) ** 2


def start_brier(proj: pd.DataFrame) -> float | None:
    d = proj[proj["starts"].notna()]
    if d.empty:
        return None
    return _rmse(d["p_start"], d["starts"].astype(float)) ** 2


def metric_suite(proj: pd.DataFrame) -> dict:
    played = proj[proj["minutes"] > 0]
    out = {
        "rows": len(proj),
        "played_rows": len(played),
        "xpts_total_ratio": float(proj["xpts"].sum() / max(proj["total_points"].sum(), 1)),
        "rmse": {
            "model": _rmse(proj["xpts"], proj["total_points"]),
            "form4": _rmse(proj["form4"], proj["total_points"]),
            "ppg": _rmse(proj["ppg"], proj["total_points"]),
        },
        "rank_corr_played": {
            "model": _rank_corr(played, "xpts"),
            "form4": _rank_corr(played, "form4"),
            "ppg": _rank_corr(played, "ppg"),
        },
        "top10_overlap": {
            "model": _topk_overlap(proj, "xpts"),
            "form4": _topk_overlap(proj, "form4"),
            "ppg": _topk_overlap(proj, "ppg"),
        },
        "cs_brier": cs_brier(proj),
        "start_brier": start_brier(proj),
    }
    out.update(captain_quality(proj))
    return out


# -- ratings-weight refit across seasons -------------------------------------


def rating_validation(windows: pd.DataFrame, model: RatingsModel) -> float:
    """Mean Spearman(rating, realized) within (start_gw, position) on the
    relevant pool — the decision the rating actually drives."""
    w = windows[windows["e_min_mean"] >= POOL_MIN_E_MINUTES].copy()
    w["rating"] = model.rate(w)
    corrs, ns = [], []
    for _, d in w.groupby(["start_gw", "position"], observed=True):
        d = d.dropna(subset=["rating"])
        if len(d) < 8 or d["rating"].nunique() < 2:
            continue
        rho = spearmanr(d["rating"], d["realized"]).statistic
        if not np.isnan(rho):
            corrs.append(rho)
            ns.append(len(d))
    return float(np.average(corrs, weights=ns))


def refit_weights(
    projs: dict[str, pd.DataFrame], validate_on: str = "2025-26", write: bool = False
) -> dict:
    windows = {s: add_subscores(build_windows(p, DEFAULT_HORIZON)) for s, p in projs.items()}
    train = pd.concat([w for s, w in windows.items() if s != validate_on], ignore_index=True)
    val = windows[validate_on]

    multi = RatingsModel().fit(train)
    current = RatingsModel()
    cached = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
    current.weights_ = {pos: pd.Series(w) for pos, w in cached.items()}

    result = {
        "validation_season": validate_on,
        "rank_corr_cached_weights": rating_validation(val, current),
        "rank_corr_multiseason_weights": rating_validation(val, multi),
        "trained_on": sorted(s for s in windows if s != validate_on),
        "weights_multiseason": {pos: w.round(4).to_dict() for pos, w in multi.weights_.items()},
    }
    if write:
        final = RatingsModel().fit(pd.concat(windows.values(), ignore_index=True))
        WEIGHTS_PATH.write_text(
            json.dumps({pos: w.round(4).to_dict() for pos, w in final.weights_.items()}, indent=2),
            encoding="utf-8",
        )
        result["written"] = str(WEIGHTS_PATH)
        result["weights_final_all_seasons"] = {
            pos: w.round(4).to_dict() for pos, w in final.weights_.items()
        }
    return result


# -- driver ------------------------------------------------------------------


def _print_suite(tag: str, m: dict) -> None:
    r, rc, tk = m["rmse"], m["rank_corr_played"], m["top10_overlap"]
    print(
        f"{tag}: rmse {r['model']:.3f} (form {r['form4']:.3f}, ppg {r['ppg']:.3f}) | "
        f"rank-corr {rc['model']:.3f} ({rc['form4']:.3f}/{rc['ppg']:.3f}) | "
        f"top10 {tk['model']:.3f} ({tk['form4']:.3f}/{tk['ppg']:.3f}) | "
        f"captain {m['captain_pts_per_gw']:.2f} (form {m['captain_pts_form_baseline']:.2f}, "
        f"best {m['captain_pts_hindsight_best']:.2f}) | "
        f"xp/actual {m['xpts_total_ratio'] - 1:+.1%} | cs-brier {m['cs_brier']:.4f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-season backtest harness.")
    parser.add_argument("--seasons", nargs="+", default=list(SEASONS_DEFAULT))
    parser.add_argument(
        "--half-lives", nargs="+", type=float, default=[DEFAULT_HALF_LIFE],
        help="rate-decay half-lives (days) to sweep; default = current 270",
    )  # fmt: skip
    parser.add_argument("--refit-weights", action="store_true")
    parser.add_argument("--write-weights", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    pg = pd.read_parquet(PLAYER_GW_PATH)
    print("building the shared minutes feature set (once)...")
    mdata = build_minutes_dataset(pg)

    results: dict = {"seasons": {}, "half_lives": [float(h) for h in args.half_lives]}
    baseline_projs: dict[str, pd.DataFrame] = {}
    for season in args.seasons:
        inv = season_invariants(pg, mdata, season)
        results["seasons"][season] = {}
        for hl in args.half_lives:
            proj = add_baselines(project_season(pg, inv, hl), pg)
            m = metric_suite(proj)
            results["seasons"][season][str(int(hl))] = m
            _print_suite(f"{season} hl={int(hl)}", m)
            if hl == DEFAULT_HALF_LIFE or len(args.half_lives) == 1:
                baseline_projs[season] = proj

    if args.refit_weights:
        if len(baseline_projs) < len(args.seasons):
            for season in args.seasons:  # ensure a default-hl frame per season
                if season not in baseline_projs:
                    inv = season_invariants(pg, mdata, season, verbose=False)
                    baseline_projs[season] = add_baselines(
                        project_season(pg, inv, DEFAULT_HALF_LIFE), pg
                    )
        print("\nrefitting rating weights across seasons...")
        results["weights"] = refit_weights(baseline_projs, write=args.write_weights)
        print(json.dumps(results["weights"], indent=2))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    import sys

    if (sys.stdout.encoding or "").lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
