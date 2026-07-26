"""Minutes model: appearance class, expected minutes, and P(60+) per fixture.

PLAN.md §4 Layer 2 — the highest-leverage component: most projection error in
public FPL models comes from minutes, not per-90 quality. Three LightGBM
models over point-in-time features from the canonical player-GW table:

- a 3-class classifier over {unused, cameo, start} per player-fixture,
- P(plays 60+ | start),
- E[minutes | start] (regression); cameo minutes use per-position train means.

Combined output per player-fixture: ``p_start``, ``p_cameo``, ``p_unused``,
``p60_given_start``, ``p_60plus``, ``e_minutes``.

Design notes:

- Every feature is computed strictly from *prior* fixtures (shifted rolling /
  time-decayed aggregates), so the same builder serves backtests and live
  prediction without leakage.
- Cold start (GW1): in-season history is all-NaN; prediction leans on the
  prev-season aggregates (name-joined), price, and position. LightGBM handles
  NaN natively, and GW1 rows appear in training with exactly this shape.
- Labels need the ``starts`` column (2022-23+), and the archive's 2022-23
  GW1-15 have ``starts`` erroneously all-zero — ``_repair_starts`` masks any
  (season, GW) whose recorded starts fall far short of 22 per fixture. Masked
  and pre-2022 rows still contribute history, with started inferred as
  minutes >= 60 (a starter subbed before the hour is miscounted; rare).
- Injury/suspension flags (``chance_of_playing``) are not in the historical
  archive, so the model cannot learn them; live use overlays them via
  ``MinutesModel.apply_availability``.
- Cross-season identity is FPL's stable ``code`` (element ids are
  season-scoped and names drift between seasons in the archive).
- For fixtures beyond the next one, features are computed from history as of
  now rather than simulated forward — acceptable over a 1-8 GW horizon.

Run a 2025-26 holdout evaluation: ``python -m engine.models.minutes``
"""

from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYER_GW_PATH = REPO_ROOT / "data" / "features" / "player_gw.parquet"

HALF_LIFE_DAYS = 28.0  # decay for recency-weighted start share / minutes
_DECAY = np.log(2.0) / HALF_LIFE_DAYS
_EPOCH = pd.Timestamp("2016-01-01", tz="UTC")

POSITION_DTYPE = pd.CategoricalDtype(["GKP", "DEF", "MID", "FWD"])

UNUSED, CAMEO, START = 0, 1, 2

ID_COLS = [
    "season",
    "gw",
    "fixture",
    "kickoff_time",
    "element",
    "code",
    "player",
    "team",
    "opponent",
    "was_home",
]

FEATURES = [
    "position",
    "price",
    "price_change_3",
    "gw",
    "season_matches_prior",
    "season_apps",
    "season_starts",
    "unused_streak",
    "start_share_5",
    "start_share_decay",
    "started_last",
    "min_avg_3",
    "min_avg_5",
    "min_decay",
    "mins_last",
    "days_since_played",
    "days_since_team_last",
    "prev_minutes_share",
    "prev_start_share",
    "prev_apps",
]

# Modest fixed capacity for all three models; tuning belongs to the backtest
# harness, not this module.
LGB_PARAMS = dict(
    n_estimators=400,
    learning_rate=0.05,
    num_leaves=63,
    min_child_samples=40,
    colsample_bytree=0.9,
    subsample=0.9,
    subsample_freq=1,
    reg_lambda=1.0,
    random_state=7,
    n_jobs=-1,
    verbose=-1,
)


# -- dataset ---------------------------------------------------------------


def _repair_starts(pg: pd.DataFrame) -> pd.Series:
    """``starts`` with implausible (season, GW) groups masked to NA.

    A clean GW records 22 starters per fixture; the 2022-23 GW1-15 archive
    records ~0. Mask any group below half the expected count.
    """
    starts = pg["starts"].astype("float64")
    grp = pg.groupby(["season", "gw"])
    recorded = grp["starts"].transform(lambda s: s.astype("float64").sum())
    expected = grp["fixture"].transform("nunique") * 22.0
    return starts.mask(recorded < 0.5 * expected)


def build_minutes_dataset(player_gw: pd.DataFrame | None = None) -> pd.DataFrame:
    """Point-in-time features + labels, one row per player per fixture."""
    pg = player_gw.copy() if player_gw is not None else pd.read_parquet(PLAYER_GW_PATH)
    pg = pg.sort_values(["season", "element", "kickoff_time", "fixture"]).reset_index(drop=True)

    keys = ["season", "element"]

    def G() -> pd.core.groupby.DataFrameGroupBy:
        return pg.groupby(keys, sort=False)

    starts = _repair_starts(pg)
    pg["_starts"] = starts
    pg["_started"] = starts.fillna((pg["minutes"] >= 60).astype(float))
    pg["_played"] = (pg["minutes"] > 0).astype(float)
    pg["_t"] = (pg["kickoff_time"] - _EPOCH).dt.total_seconds() / 86400.0

    pg["started_last"] = G()["_started"].shift(1)
    pg["mins_last"] = G()["minutes"].shift(1)
    pg["_sh_started"] = G()["_started"].shift(1)
    pg["_sh_minutes"] = G()["minutes"].shift(1)
    pg["start_share_5"] = G()["_sh_started"].transform(lambda s: s.rolling(5, min_periods=1).mean())
    pg["min_avg_5"] = G()["_sh_minutes"].transform(lambda s: s.rolling(5, min_periods=1).mean())
    pg["min_avg_3"] = G()["_sh_minutes"].transform(lambda s: s.rolling(3, min_periods=1).mean())

    # Exponentially decayed start share and minutes. With weights
    # e^{-decay (t_i - t_j)}, the e^{-decay t_i} factor cancels in the ratio,
    # so cumulative sums of e^{decay (t_j - t_0)}-scaled values suffice.
    u = np.exp(_DECAY * (pg["_t"] - G()["_t"].transform("first")))
    pg["_u"], pg["_us"], pg["_um"] = u, u * pg["_started"], u * pg["minutes"]
    pg["_cu"] = G()["_u"].cumsum()
    pg["_cus"] = G()["_us"].cumsum()
    pg["_cum"] = G()["_um"].cumsum()
    cu_prev = G()["_cu"].shift(1)
    pg["start_share_decay"] = G()["_cus"].shift(1) / cu_prev
    pg["min_decay"] = G()["_cum"].shift(1) / cu_prev

    pg["season_matches_prior"] = G().cumcount().astype(float)
    pg["season_apps"] = G()["_played"].cumsum() - pg["_played"]
    pg["season_starts"] = G()["_started"].cumsum() - pg["_started"]

    # Consecutive unused fixtures immediately before this one.
    pg["_lastplay_pos"] = pg["season_matches_prior"].where(pg["_played"] > 0)
    pg["_lastplay_pos"] = G()["_lastplay_pos"].shift(1)
    pg["_lastplay_pos"] = G()["_lastplay_pos"].ffill()
    pg["unused_streak"] = pg["season_matches_prior"] - 1.0 - pg["_lastplay_pos"].fillna(-1.0)

    pg["_playtime"] = pg["_t"].where(pg["_played"] > 0)
    pg["_playtime"] = G()["_playtime"].shift(1)
    pg["_playtime"] = G()["_playtime"].ffill()
    pg["days_since_played"] = pg["_t"] - pg["_playtime"]

    pg["price_change_3"] = pg["price"] - G()["price"].shift(3)

    # Days since the team's previous fixture (rotation risk).
    tk = (
        pg[["season", "team", "kickoff_time"]]
        .drop_duplicates()
        .sort_values(["season", "team", "kickoff_time"])
    )
    tk["days_since_team_last"] = (
        tk.groupby(["season", "team"])["kickoff_time"].diff().dt.total_seconds() / 86400.0
    )
    pg = pg.merge(tk, on=["season", "team", "kickoff_time"], how="left")

    # Prev-season aggregates by stable player code — the GW1 prior.
    per_season = (
        pg.groupby(["season", "code"])
        .agg(
            _pmin=("minutes", "sum"),
            _papps=("_played", "sum"),
            _pstarts=("_starts", lambda s: s.sum(min_count=1)),
        )
        .reset_index()
    )
    season_list = sorted(pg["season"].unique())
    per_season["season"] = per_season["season"].map(dict(zip(season_list[:-1], season_list[1:])))
    per_season = per_season.dropna(subset=["season"])
    per_season["prev_minutes_share"] = per_season["_pmin"] / (38 * 90)
    per_season["prev_start_share"] = per_season["_pstarts"] / 38.0
    per_season["prev_apps"] = per_season["_papps"]
    pg = pg.merge(
        per_season[["season", "code", "prev_minutes_share", "prev_start_share", "prev_apps"]],
        on=["season", "code"],
        how="left",
    )

    # Labels — only where starts is genuinely recorded.
    y = np.where(pg["_starts"] == 1, START, np.where(pg["minutes"] > 0, CAMEO, UNUSED)).astype(
        float
    )
    y[pg["_starts"].isna()] = np.nan
    pg["y_class"] = y
    pg["y_60"] = (pg["minutes"] >= 60).astype(int)

    cols = list(dict.fromkeys(ID_COLS + ["position"] + FEATURES + ["minutes", "y_class", "y_60"]))
    data = pg[cols].copy()
    data["position"] = data["position"].astype(POSITION_DTYPE)
    return data


# -- model -----------------------------------------------------------------


class MinutesModel:
    def __init__(self, **lgb_overrides) -> None:
        self.params = {**LGB_PARAMS, **lgb_overrides}
        self.clf_: lgb.LGBMClassifier | None = None
        self.p60_: lgb.LGBMClassifier | None = None
        self.reg_start_min_: lgb.LGBMRegressor | None = None
        self.cameo_minutes_: pd.Series | None = None
        self.cameo_default_: float = 20.0

    def fit(self, data: pd.DataFrame) -> "MinutesModel":
        train = data.dropna(subset=["y_class"])
        if train.empty:
            raise ValueError("no labeled rows (starts never recorded)")
        X = train[FEATURES]
        self.clf_ = lgb.LGBMClassifier(objective="multiclass", num_class=3, **self.params)
        self.clf_.fit(X, train["y_class"].astype(int))

        started = train[train["y_class"] == START]
        Xs = started[FEATURES]
        self.p60_ = lgb.LGBMClassifier(objective="binary", **self.params)
        self.p60_.fit(Xs, started["y_60"])
        self.reg_start_min_ = lgb.LGBMRegressor(**self.params)
        self.reg_start_min_.fit(Xs, started["minutes"])

        cameo = train[train["y_class"] == CAMEO]
        self.cameo_minutes_ = cameo.groupby("position", observed=False)["minutes"].mean()
        self.cameo_default_ = float(cameo["minutes"].mean())
        return self

    def predict(self, data: pd.DataFrame) -> pd.DataFrame:
        """p_unused/p_cameo/p_start, p60_given_start, p_60plus, e_minutes per row."""
        X = data[FEATURES]
        proba = self.clf_.predict_proba(X)[:, np.argsort(self.clf_.classes_)]
        p_unused, p_cameo, p_start = proba[:, UNUSED], proba[:, CAMEO], proba[:, START]

        p60 = self.p60_.predict_proba(X)[:, list(self.p60_.classes_).index(1)]
        e_min_start = np.clip(self.reg_start_min_.predict(X), 1.0, 90.0)
        e_min_cameo = (
            data["position"]
            .map(self.cameo_minutes_)
            .fillna(self.cameo_default_)
            .to_numpy(dtype=float)
        )

        return pd.DataFrame(
            {
                "p_unused": p_unused,
                "p_cameo": p_cameo,
                "p_start": p_start,
                "p60_given_start": p60,
                "p_60plus": p_start * p60,
                "e_min_given_start": e_min_start,
                "e_minutes": p_start * e_min_start + p_cameo * e_min_cameo,
            },
            index=data.index,
        )

    @staticmethod
    def apply_availability(pred: pd.DataFrame, availability: np.ndarray) -> pd.DataFrame:
        """Overlay live status flags: scale by P(available), e.g. chance_of_playing/100."""
        a = np.clip(np.asarray(availability, dtype=float), 0.0, 1.0)
        out = pred.copy()
        for col in ("p_start", "p_cameo", "p_60plus", "e_minutes"):
            out[col] = out[col] * a
        out["p_unused"] = 1.0 - out["p_start"] - out["p_cameo"]
        return out


# -- holdout evaluation ----------------------------------------------------


def evaluate_holdout(holdout_season: str = "2025-26") -> None:
    """Train on earlier labeled seasons, score every player-fixture of the holdout."""
    data = build_minutes_dataset()
    labeled = data.dropna(subset=["y_class"])
    train = labeled[labeled["season"] < holdout_season]
    test = labeled[labeled["season"] == holdout_season]
    if train.empty or test.empty:
        raise SystemExit(f"no labeled train/test rows around {holdout_season}")

    model = MinutesModel().fit(train)
    pred = model.predict(test)
    print(
        f"trained on {len(train):,} labeled rows "
        f"({', '.join(sorted(train['season'].unique()))}) | holdout {holdout_season}: "
        f"{len(test):,} rows"
    )

    y = test["y_class"].to_numpy()
    y_start = (y == START).astype(float)
    p_start = pred["p_start"].to_numpy()

    # Baselines: last-5 start share / last-5 minutes, train means where no history.
    base_start_rate = float((train["y_class"] == START).mean())
    p_base = test["start_share_5"].fillna(base_start_rate).clip(0.02, 0.98).to_numpy()
    brier = float(np.mean((p_start - y_start) ** 2))
    brier_base = float(np.mean((p_base - y_start) ** 2))

    proba = np.column_stack([pred["p_unused"], pred["p_cameo"], pred["p_start"]])
    logloss = float(-np.mean(np.log(np.clip(proba[np.arange(len(y)), y.astype(int)], 1e-9, 1))))

    e_min = pred["e_minutes"].to_numpy()
    mins = test["minutes"].to_numpy(dtype=float)
    base_mins = test["min_avg_5"].fillna(float(train["minutes"].mean())).to_numpy()
    mae = float(np.mean(np.abs(e_min - mins)))
    mae_base = float(np.mean(np.abs(base_mins - mins)))
    rmse = float(np.sqrt(np.mean((e_min - mins) ** 2)))
    rmse_base = float(np.sqrt(np.mean((base_mins - mins) ** 2)))

    print(f"\nstart Brier:   model {brier:.4f} vs last-5-share baseline {brier_base:.4f}")
    print(f"3-class log loss: {logloss:.4f}")
    print(f"minutes MAE:   model {mae:.2f} vs last-5-avg baseline {mae_base:.2f}")
    print(f"minutes RMSE:  model {rmse:.2f} vs last-5-avg baseline {rmse_base:.2f}")

    started = y == START
    p60 = pred["p60_given_start"].to_numpy()[started]
    y60 = test["y_60"].to_numpy()[started]
    print(
        f"P(60+|start) on actual starters: predicted {p60.mean():.3f} "
        f"vs observed {y60.mean():.3f} (Brier {np.mean((p60 - y60) ** 2):.4f})"
    )

    early = test["gw"] <= 5
    brier_early = float(np.mean((p_start[early] - y_start[early]) ** 2))
    brier_early_base = float(np.mean((p_base[early] - y_start[early]) ** 2))
    mae_early = float(np.mean(np.abs(e_min[early] - mins[early])))
    mae_early_base = float(np.mean(np.abs(base_mins[early] - mins[early])))
    print(
        f"\ncold start (GW1-5): start Brier {brier_early:.4f} vs baseline {brier_early_base:.4f}"
        f" | minutes MAE {mae_early:.2f} vs baseline {mae_early_base:.2f}"
    )

    print("\np_start calibration (deciles):")
    cal = (
        pd.DataFrame({"p": p_start, "y": y_start})
        .assign(bin=lambda d: pd.qcut(d["p"], 10, duplicates="drop"))
        .groupby("bin", observed=True)
        .agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean"))
    )
    print(cal.to_string(float_format=lambda v: f"{v:.3f}"))

    gain = model.clf_.booster_.feature_importance(importance_type="gain")
    top = pd.Series(gain, index=FEATURES).sort_values(ascending=False).head(10)
    print("\ntop classifier features (gain):")
    print((top / top.sum()).to_string(float_format=lambda v: f"{v:.1%}"))


if __name__ == "__main__":
    evaluate_holdout()
