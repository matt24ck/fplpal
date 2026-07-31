"""Position ratings: fixture-adjusted 0-100 ratings with named sub-scores.

PLAN.md §4 "Position rating systems". Each position gets a composite rating
built from *different* sub-scores (each 0-100), so the UI and chat layer can
always answer "why is he rated 87":

    GKP  clean_sheets · saves · bonus · value · minutes
    DEF  clean_sheets · attacking · dc_floor · bonus · value · minutes
    MID  attacking · involvement · floor · explosiveness · value · minutes
    FWD  attacking · involvement · floor · explosiveness · value · minutes

Construction:

- Inputs are Layer-4 projections summed over a horizon window (default next
  6 GWs), so ratings are fixture-adjusted by construction and double/blank
  gameweeks change them the way they should.
- A sub-score is the player's percentile (x100) of the underlying quantity
  within (window, position), with the percentile CDF anchored on the
  *relevant pool* (projected ≥ 45 expected minutes per fixture-window mean) —
  benchwarmers score against the pool rather than inflating it.
- The headline rating is a weighted blend of sub-scores; weights are fitted
  per position by non-negative least squares of realized window points on
  sub-scores over historical windows — regression, not hand-tuned vibes —
  then normalized to sum 1 so the rating stays on the 0-100 scale.
- "involvement" is the player's share of his team's projected goal+assist
  points (focal-player signal; penalty duty partially shows up here via xG
  until live set-piece notes arrive). "explosiveness" is the projection
  standard deviation over the window — ceiling, not just mean.

The holdout evaluation replays 2025-26, fits weights on first-half windows,
and scores rating quality on second-half windows. Caveat shared with the
replay: per-GW projections use information as of each GW, so a window read
from the replay is fractionally fresher than a frozen-at-window-start
projection would be; the full backtest harness will freeze properly.

Run: ``python -m engine.models.ratings``
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import nnls
from scipy.stats import spearmanr

DEFAULT_HORIZON = 6
POOL_MIN_E_MINUTES = 45.0  # mean e_minutes defining the "relevant pool"

# Sub-score name -> window-aggregate source column.
SOURCES = {
    "clean_sheets": "cs_def",
    "saves": "save_pts",
    "attacking": "att",
    "dc_floor": "dc_pts",
    "involvement": "involvement",
    "floor": "floor_pts",
    "explosiveness": "sd",
    "bonus": "bonus_pts",
    "value": "value",
    "minutes": "p60_mean",
}

SUBSCORES: dict[str, list[str]] = {
    "GKP": ["clean_sheets", "saves", "bonus", "value", "minutes"],
    "DEF": ["clean_sheets", "attacking", "dc_floor", "bonus", "value", "minutes"],
    "MID": ["attacking", "involvement", "floor", "explosiveness", "value", "minutes"],
    "FWD": ["attacking", "involvement", "floor", "explosiveness", "value", "minutes"],
}


def build_windows(proj: pd.DataFrame, horizon: int = DEFAULT_HORIZON) -> pd.DataFrame:
    """Aggregate per-fixture projections into per-player horizon windows.

    One row per (season, start_gw, code) for every start GW with a complete
    horizon. ``realized`` sums actual points over the window (evaluation and
    weight fitting only — never feeds the rating itself).
    """
    proj = proj.sort_values(["gw", "kickoff_time"]).copy()
    proj["_att"] = proj["pts_goals"] + proj["pts_assists"]
    proj["_cs_def"] = proj["pts_cs"] + proj["pts_gc"]
    proj["_floor"] = proj["pts_dc"] + proj["pts_appearance"]

    gws = sorted(proj["gw"].unique())
    frames = []
    for g in gws:
        window = [x for x in gws if g <= x < g + horizon]
        if len(window) < horizon:
            continue
        w = proj[proj["gw"].isin(window)]
        agg = w.groupby(["season", "code"], as_index=False).agg(
            player=("player", "last"),
            team=("team", "last"),
            position=("position", "first"),
            price=("price", "first"),
            n_fixtures=("fixture", "size"),
            xpts=("xpts", "sum"),
            var=("var_pts", "sum"),
            att=("_att", "sum"),
            cs_def=("_cs_def", "sum"),
            dc_pts=("pts_dc", "sum"),
            save_pts=("pts_saves", "sum"),
            bonus_pts=("pts_bonus", "sum"),
            floor_pts=("_floor", "sum"),
            p60_mean=("p_60plus", "mean"),
            e_min_mean=("e_minutes", "mean"),
            realized=("total_points", "sum"),
        )
        agg["start_gw"] = g
        agg["sd"] = np.sqrt(agg["var"])
        agg["value"] = agg["xpts"] / (agg["price"] / 10.0)
        team_att = agg.groupby("team")["att"].transform("sum")
        agg["involvement"] = agg["att"] / team_att.clip(lower=1e-9)
        frames.append(agg)
    return pd.concat(frames, ignore_index=True)


def add_subscores(windows: pd.DataFrame) -> pd.DataFrame:
    """Percentile sub-scores (0-100) within each (season, start_gw, position).

    The percentile CDF is anchored on the relevant pool; everyone is scored
    through it, so fringe players land near 0 instead of compressing the scale.
    """
    windows = windows.copy()
    for name in SOURCES:
        windows[f"score_{name}"] = np.nan
    for (_, _, pos), idx in windows.groupby(
        ["season", "start_gw", "position"], observed=True
    ).groups.items():
        d = windows.loc[idx]
        pool = d["e_min_mean"] >= POOL_MIN_E_MINUTES
        for name in SUBSCORES.get(str(pos), []):
            vals = d[SOURCES[name]].to_numpy(dtype=float)
            anchor = np.sort(vals[pool.to_numpy()])
            if len(anchor) == 0:
                anchor = np.sort(vals)
            score = 100.0 * np.searchsorted(anchor, vals, side="right") / len(anchor)
            windows.loc[idx, f"score_{name}"] = np.minimum(score, 100.0)
    return windows


class RatingsModel:
    """Per-position NNLS blend of sub-scores into the headline 0-100 rating."""

    def __init__(self) -> None:
        self.weights_: dict[str, pd.Series] = {}

    def fit(self, windows: pd.DataFrame) -> RatingsModel:
        """Regress realized window points on sub-scores (pool players only)."""
        for pos, names in SUBSCORES.items():
            d = windows[
                (windows["position"] == pos) & (windows["e_min_mean"] >= POOL_MIN_E_MINUTES)
            ].dropna(subset=[f"score_{n}" for n in names])
            cols = [f"score_{n}" for n in names]
            A = np.column_stack([d[cols].to_numpy(dtype=float) / 100.0, np.ones(len(d))])
            w, _ = nnls(A, d["realized"].to_numpy(dtype=float))
            w = w[:-1]  # drop intercept — monotone shift, irrelevant to a rating
            if w.sum() <= 0:
                w = np.ones(len(names))
            self.weights_[pos] = pd.Series(w / w.sum(), index=names)
        return self

    def rate(self, windows: pd.DataFrame) -> pd.Series:
        """Headline rating: fitted-weight blend of sub-scores, 0-100."""
        rating = pd.Series(np.nan, index=windows.index)
        for pos, w in self.weights_.items():
            mask = windows["position"] == pos
            scores = windows.loc[mask, [f"score_{n}" for n in w.index]]
            rating[mask] = scores.to_numpy(dtype=float) @ w.to_numpy()
        return rating


# -- holdout evaluation ----------------------------------------------------


def evaluate_holdout(holdout_season: str = "2025-26", horizon: int = DEFAULT_HORIZON) -> None:
    """Replay the holdout, fit blend weights on first-half windows, score second half."""
    from engine.models.points import replay_season

    proj, _ = replay_season(holdout_season)
    windows = add_subscores(build_windows(proj, horizon))
    mid_gw = int(np.median(windows["start_gw"].unique()))
    train = windows[windows["start_gw"] <= mid_gw]
    test = windows[windows["start_gw"] > mid_gw]

    model = RatingsModel().fit(train)
    windows["rating"] = model.rate(windows)
    test = windows[windows["start_gw"] > mid_gw]

    print(
        f"\n{horizon}-GW windows: {windows['start_gw'].nunique()} starts, "
        f"weights fit on start_gw <= {mid_gw}, evaluated after"
    )
    print("\nfitted sub-score weights per position:")
    for pos, w in model.weights_.items():
        parts = " ".join(f"{n} {v:.2f}" for n, v in w.items())
        print(f"  {pos}: {parts}")

    # Rating quality: Spearman vs realized window points among pool players.
    pool = test[test["e_min_mean"] >= POOL_MIN_E_MINUTES]
    print(f"\nrank corr with realized {horizon}-GW points (pool players, per window):")
    for pos in SUBSCORES:
        rows = pool[pool["position"] == pos]
        r_rating, r_xpts, ns = [], [], []
        for _, d in rows.groupby("start_gw"):
            if len(d) < 10:
                continue
            r_rating.append(spearmanr(d["rating"], d["realized"]).statistic)
            r_xpts.append(spearmanr(d["xpts"], d["realized"]).statistic)
            ns.append(len(d))
        print(
            f"  {pos}: rating {np.average(r_rating, weights=ns):.3f} | "
            f"raw xpts {np.average(r_xpts, weights=ns):.3f} (n/window ~{int(np.mean(ns))})"
        )

    # The pre-season view: GW1 top of each position.
    gw1 = windows[windows["start_gw"] == windows["start_gw"].min()]
    print(f"\ntop-rated at GW1 (next {horizon} GWs):")
    for pos in SUBSCORES:
        top = gw1[gw1["position"] == pos].nlargest(4, "rating")
        rows = ", ".join(
            f"{r.player} {r.rating:.0f} (£{r.price / 10:.1f}m)" for r in top.itertuples()
        )
        print(f"  {pos}: {rows}")

    print("\nGW1 top DEF sub-score breakdown (the 'why' surface):")
    cols = ["player", "team", "rating"] + [f"score_{n}" for n in SUBSCORES["DEF"]]
    top_def = gw1[gw1["position"] == "DEF"].nlargest(6, "rating")[cols]
    top_def.columns = [c.removeprefix("score_") for c in top_def.columns]
    print(top_def.to_string(index=False, float_format=lambda v: f"{v:.0f}"))


if __name__ == "__main__":
    import sys

    if (sys.stdout.encoding or "").lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    evaluate_holdout()
