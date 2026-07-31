"""Player event rates: shrunken per-90 rates for every scoring-relevant event.

PLAN.md §4 Layer 3. For each player-fixture row, strictly pre-match per-90
rates computed from exponentially time-decayed career sums (grouped by FPL's
stable player ``code``, so rates carry across seasons) and shrunk toward
position × price-tier priors, empirical-Bayes style with strength ``k`` in
effective 90s: ``rate = (decayed_count + k·prior) / (decayed_90s + k)``.

Rates produced per row:

- ``xg90``, ``xa90`` — attacking rates from official FPL xG/xA (2022-23+).
  ``fin_mult`` — the player's goals/xG ratio, heavily shrunk toward 1
  (finishing skill is mostly noise, and xG is goal-calibrated by
  construction); ``exp_goals90 = xg90 × fin_mult``. ``assist_mult`` — the
  player's FPL-assists/xA ratio, shrunk toward the position's league ratio,
  which sits far above 1 (FWD ~2.5x: FPL's assist definition credits
  rebounds, deflections, and won penalties that xA does not);
  ``exp_assists90 = xa90 × assist_mult``.
- ``cbit90`` / ``cbirt90`` — defensive-count rates; ``dc90`` selects the
  position's counting stat. ``EventRatesModel.p_dc`` converts rate + minutes
  into P(hit the DC threshold) via a negative binomial with per-position
  overdispersion fitted on full-match rows.
- ``saves90`` — GK save volume; Layer 4 scales it by opponent shot volume.
- ``yc90``, ``rc90`` — card rates (a genuine per-player trait).
- ``bps_res90`` — "bonus magnetism": per-90 residual of actual BPS vs a
  per-position linear model on countable events, capturing players who
  systematically over/under-earn BPS given their output.
- Position base rates (constants from fit): ``og90`` own goals, ``pm90``
  penalty misses, ``ps90`` penalty saves (GKP).

Notes:

- Availability differs by stat (xG 2022-23+; DC counts 2016-19 and 2025-26),
  so each family keeps its own decayed exposure — missing-era rows contribute
  to neither numerator nor exposure, and rates fall back toward priors.
- The archive's ``defensive_contribution`` column is the raw CBIT/CBIRT count
  (verified equal), not the awarded points; thresholds come from season config.
- Penalty-taker status isn't in the archive, but a taker's penalty xG is baked
  into FPL xG, so xg90 partially encodes it. Explicit penalty share from
  ``set-piece-notes`` is a live-data, Layer-4 concern.
- Rates for an upcoming fixture: append it as a row with NaN stats — every
  feature uses only prior rows (same pattern as the minutes model).

Run a 2025-26 holdout evaluation: ``python -m engine.models.event_rates``
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import nbinom, poisson

from engine.config.season import load_season

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYER_GW_PATH = REPO_ROOT / "data" / "features" / "player_gw.parquet"

# Tuned by the multi-season harness (backtest/harness.py, BUILDLOG §28): the
# 120/180/270/365 sweep left distribution metrics unchanged but 180 tracked
# player decline better where it costs real points — captain quality 6.84 vs
# 6.42 pts/GW across 2023-26, and 6.11 vs 5.42 in 2025-26, the documented
# Salah-decay season.
RATE_HALF_LIFE_DAYS = 180.0
_EPOCH = pd.Timestamp("2016-01-01", tz="UTC")

# Shrinkage strength per stat, in effective 90s (fin in xG units). Starting
# points for the backtest harness to tune, not settled choices.
DEFAULT_K = {
    "xg": 10.0,
    "xa": 10.0,
    "cbit": 6.0,
    "cbirt": 6.0,
    "saves": 8.0,
    "yc": 15.0,
    "rc": 80.0,
    "bps_res": 15.0,
    "fin": 25.0,  # xG units of prior weight on the goals/xG ratio
    "assist_ratio": 12.0,  # xA units of prior weight on the assists/xA ratio
}

# Stats whose priors use position × price-tier cells; the rest use position.
CELL_STATS = ("xg", "xa", "cbit", "cbirt", "saves")


def data_basis(exposure_90: float | None) -> dict:
    """Prior-vs-observed provenance for one player (TODO §3 badge).

    ``prior_weight`` is the exact empirical-Bayes blend ``k / (exposure + k)``
    at the attacking strength ``k = DEFAULT_K["xg"]`` — representative because
    attacking rates carry most of an outfielder's xPts, and the per-stat k's
    all sit in the same 6-15 band. ``effective_90s`` is the time-decayed
    exposure of the always-available stat family, so a new signing (or a
    promoted-club player — the archive has no Championship data) reads as
    pure prior even mid-career.
    """
    e = 0.0 if exposure_90 is None or np.isnan(exposure_90) else max(float(exposure_90), 0.0)
    k = DEFAULT_K["xg"]
    w = k / (e + k)
    if e == 0.0:
        level = "pure_prior"
        note = "no PL data in the archive — projection is entirely the position × price-tier prior"
    elif w >= 0.5:
        level = "mostly_prior"
        note = "thin PL sample — projection leans mostly on the position × price-tier prior"
    elif w >= 0.25:
        level = "mixed"
        note = "moderate PL sample — the prior still carries meaningful weight"
    else:
        level = "observed"
        note = "rates predominantly from observed PL performance"
    return {
        "level": level,
        "effective_90s": round(e, 1),
        "prior_weight": round(w, 2),
        "note": note,
    }


BPS_REG_FEATURES = [
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "penalties_saved",
    "penalties_missed",
    "yellow_cards",
    "red_cards",
    "own_goals",
]


class EventRatesModel:
    def __init__(
        self,
        half_life_days: float = RATE_HALF_LIFE_DAYS,
        n_price_bins: int = 5,
        ks: dict[str, float] | None = None,
        season: str = "2026-27",
    ) -> None:
        self.decay = np.log(2.0) / half_life_days
        self.n_price_bins = n_price_bins
        self.ks = {**DEFAULT_K, **(ks or {})}
        self.dc_threshold = dict(load_season(season).scoring.defensive_contribution.threshold)

        self.cell_priors_: pd.DataFrame | None = None  # (position, price_bin) x stat
        self.pos_priors_: pd.DataFrame | None = None  # position x stat
        self.base_rates_: pd.DataFrame | None = None  # position x {og90, pm90, ps90}
        self.dc_phi_: dict[str, float] = {}  # position -> var/mean overdispersion
        self.dc_base_: dict[str, float] = {}  # position -> P(hit | played), train
        self.bps_coefs_: dict[str, np.ndarray] = {}
        self.assist_ratio_: dict[str, float] = {}  # position -> league FPL-assists/xA

    # -- fitting -----------------------------------------------------------

    def fit(self, pg_train: pd.DataFrame) -> "EventRatesModel":
        """Learn priors, BPS model, and dispersion from raw training rows."""
        pg = self._prep(pg_train)
        played = pg[pg["minutes"] > 0].copy()
        ex = played["minutes"] / 90.0

        stats = _stat_values(played)
        rows = []
        for (pos, pbin), idx in played.groupby(
            ["position", "_price_bin"], observed=True
        ).groups.items():
            row = {"position": pos, "price_bin": pbin}
            for name, (val, mask) in stats.items():
                m = mask.loc[idx]
                row[name] = val.loc[idx][m].sum() / max(ex.loc[idx][m].sum(), 1e-9)
                row[f"_ex_{name}"] = ex.loc[idx][m].sum()
            rows.append(row)
        cells = pd.DataFrame(rows).set_index(["position", "price_bin"])

        pos_rows = []
        for pos, idx in played.groupby("position", observed=True).groups.items():
            row = {"position": pos}
            for name, (val, mask) in stats.items():
                m = mask.loc[idx]
                row[name] = val.loc[idx][m].sum() / max(ex.loc[idx][m].sum(), 1e-9)
            pos_rows.append(row)
        self.pos_priors_ = pd.DataFrame(pos_rows).set_index("position")

        # Thin cells (< 30 effective 90s) fall back to the position prior.
        for name in stats:
            thin = cells[f"_ex_{name}"] < 30.0
            pos_of = cells.index.get_level_values("position")
            cells.loc[thin, name] = self.pos_priors_[name].reindex(pos_of[thin]).to_numpy()
        self.cell_priors_ = cells[list(stats)]

        # Position base rates for rare events.
        base = played.groupby("position", observed=True).apply(
            lambda d: pd.Series(
                {
                    "og90": d["own_goals"].sum() / (d["minutes"].sum() / 90.0),
                    "pm90": d["penalties_missed"].sum() / (d["minutes"].sum() / 90.0),
                    "ps90": d["penalties_saved"].sum() / (d["minutes"].sum() / 90.0),
                }
            ),
            include_groups=False,
        )
        self.base_rates_ = base

        # League FPL-assists/xA per position: FPL's assist definition is far
        # more generous than Opta xA (FWD ~2.5x — rebounds, deflections, won
        # penalties all credit), so player assist ratios shrink toward these.
        # Goals get no such target: xG is goal-calibrated by construction, and
        # the 2022-25 position goals/xG ratios did not generalize on holdout.
        xg_rows = played[played["xg"].notna()]
        for pos, d in xg_rows.groupby("position", observed=True):
            xa_sum = float(d["xa"].sum())
            if xa_sum > 20:
                self.assist_ratio_[pos] = float(np.clip(d["assists"].sum() / xa_sum, 1.0, 2.5))
        for pos in ("GKP", "DEF", "MID", "FWD"):
            self.assist_ratio_.setdefault(pos, 1.4)

        self._fit_dc_dispersion(played)
        self._fit_bps(played)
        return self

    def _fit_dc_dispersion(self, played: pd.DataFrame) -> None:
        """Per-position var/mean of DC counts across full matches (NB overdispersion)."""
        full = played[(played["minutes"] >= 85) & played["cbi"].notna()].copy()
        full["_cbit"] = (full["cbi"] + full["tackles"]).astype(float)
        full["_cbirt"] = (full["_cbit"] + full["recoveries"]).astype(float)
        for pos in ("DEF", "MID", "FWD"):
            col = "_cbit" if pos == "DEF" else "_cbirt"
            per = (
                full[full["position"] == pos]
                .groupby("code")[col]
                .agg(["mean", "var", "count"])
                .query("count >= 10 and mean > 0")
            )
            phi = float((per["var"] / per["mean"]).median()) if len(per) >= 10 else 1.3
            self.dc_phi_[pos] = max(phi, 1.0)
            hits = np.where(full["position"] == pos, full[col] >= self.dc_threshold[pos], np.nan)
            self.dc_base_[pos] = float(pd.Series(hits).mean())

    def _fit_bps(self, played: pd.DataFrame) -> None:
        """Per-position OLS: BPS ~ countable events. Residual = bonus magnetism."""
        for pos in ("GKP", "DEF", "MID", "FWD"):
            d = played[played["position"] == pos]
            X = _bps_design(d)
            coefs, *_ = np.linalg.lstsq(X, d["bps"].to_numpy(dtype=float), rcond=None)
            self.bps_coefs_[pos] = coefs

    # -- transform ---------------------------------------------------------

    def transform(self, pg: pd.DataFrame) -> pd.DataFrame:
        """Full frame + point-in-time shrunken rate columns per row."""
        pg = self._prep(pg)
        pg = pg.sort_values(["code", "kickoff_time", "fixture"]).reset_index(drop=True)
        t = (pg["kickoff_time"] - _EPOCH).dt.total_seconds() / 86400.0
        pg["_t"] = t

        # BPS residual per played row, from the fitted per-position model.
        pred_bps = np.full(len(pg), np.nan)
        for pos, coefs in self.bps_coefs_.items():
            m = (pg["position"] == pos).to_numpy()
            pred_bps[m] = _bps_design(pg[m]) @ coefs
        pg["_bps_res"] = np.where(pg["minutes"] > 0, pg["bps"] - pred_bps, 0.0)

        stats = _stat_values(pg)
        stats["bps_res"] = (pg["_bps_res"], pg["minutes"] > 0)

        # Decayed pre-match sums: e^{-d(t_i-t_0)} · Σ_{j<i} v_j e^{d(t_j-t_0)}.
        def G() -> pd.core.groupby.DataFrameGroupBy:
            return pg.groupby("code", sort=False)

        t0 = G()["_t"].transform("first")
        up = np.exp(self.decay * (t - t0))
        down = np.exp(-self.decay * (t - t0))
        ex90 = pg["minutes"].to_numpy(dtype=float) / 90.0

        masks = {name: mask for name, (_, mask) in stats.items()}
        for name, (val, mask) in stats.items():
            pg[f"_n_{name}"] = np.where(mask, val.astype(float).fillna(0.0), 0.0) * up
            pg[f"_e_{name}"] = np.where(mask, ex90, 0.0) * up
        for name in stats:
            pg[f"_cn_{name}"] = G()[f"_n_{name}"].cumsum()
            pg[f"_ce_{name}"] = G()[f"_e_{name}"].cumsum()
        for name in stats:
            pg[f"n_{name}"] = G()[f"_cn_{name}"].shift(1).fillna(0.0) * down
            pg[f"e_{name}"] = G()[f"_ce_{name}"].shift(1).fillna(0.0) * down

        # Priors per row, then shrink.
        prior = self.cell_priors_.reindex(
            pd.MultiIndex.from_arrays([pg["position"], pg["_price_bin"]])
        ).set_axis(pg.index)
        for name in stats:
            if name == "bps_res":
                p = 0.0
            elif name in CELL_STATS:
                p = prior[name].fillna(pg["position"].map(self.pos_priors_[name]).astype(float))
            else:
                p = pg["position"].map(self.pos_priors_[name]).astype(float)
            k = self.ks.get(name, 10.0)
            pg[f"{name}90"] = (pg[f"n_{name}"] + k * p) / (pg[f"e_{name}"] + k)
            pg[f"{name}90_raw"] = np.where(
                pg[f"e_{name}"] > 0, pg[f"n_{name}"] / pg[f"e_{name}"], np.nan
            )

        k_fin = self.ks["fin"]
        pg["fin_mult"] = ((pg["n_goals_xg"] + k_fin) / (pg["n_xg"] + k_fin)).clip(0.5, 1.6)
        pg["exp_goals90"] = pg["xg90"] * pg["fin_mult"]

        k_ar = self.ks["assist_ratio"]
        ratio_a = pg["position"].map(self.assist_ratio_).astype(float)
        pg["assist_mult"] = ((pg["n_assists_xg"] + k_ar * ratio_a) / (pg["n_xa"] + k_ar)).clip(
            0.6, 2.6
        )
        pg["exp_assists90"] = pg["xa90"] * pg["assist_mult"]

        pg["dc90"] = np.where(
            pg["position"] == "DEF",
            pg["cbit90"],
            np.where(pg["position"] == "GKP", np.nan, pg["cbirt90"]),
        )
        for col in ("og90", "pm90", "ps90"):
            pg[col] = pg["position"].map(self.base_rates_[col]).astype(float)

        pg["exposure_90"] = pg["e_saves"]  # always-available family
        pg["exposure_xg_90"] = pg["e_xg"]
        pg["exposure_dc_90"] = pg["e_cbit"]
        drop = [c for c in pg.columns if c.startswith("_")]
        drop += [f"n_{n}" for n in masks] + [f"e_{n}" for n in masks]
        return pg.drop(columns=drop)

    # -- derived probabilities ---------------------------------------------

    def p_dc(self, rates: pd.DataFrame, minutes: np.ndarray) -> np.ndarray:
        """P(hit the position's DC-count threshold) given expected minutes on pitch."""
        out = np.zeros(len(rates))
        lam_all = rates["dc90"].to_numpy(dtype=float) * np.asarray(minutes, dtype=float) / 90.0
        pos_arr = rates["position"].astype(str).to_numpy()
        for pos, tau in self.dc_threshold.items():
            m = (pos_arr == pos) & (lam_all > 0)
            if not m.any():
                continue
            lam = lam_all[m]
            phi = self.dc_phi_.get(pos, 1.3)
            if phi <= 1.02:
                out[m] = poisson.sf(tau - 1, lam)
            else:
                r = lam / (phi - 1.0)  # NB2 with var = phi * mean at this lam
                out[m] = nbinom.sf(tau - 1, r, r / (r + lam))
        return out

    # -- helpers -----------------------------------------------------------

    def _prep(self, pg: pd.DataFrame) -> pd.DataFrame:
        pg = pg.dropna(subset=["code"]).copy()
        pct = pg.groupby(["season", "gw", "position"], observed=True)["price"].rank(pct=True)
        pg["_price_bin"] = np.ceil(pct * self.n_price_bins).clip(1, self.n_price_bins).astype(int)
        return pg


def _stat_values(pg: pd.DataFrame) -> dict[str, tuple[pd.Series, pd.Series]]:
    """stat -> (per-row value, availability mask). Shared by fit and transform."""
    xg_ok = pg["xg"].notna()
    dc_ok = pg["cbi"].notna() & pg["tackles"].notna() & pg["recoveries"].notna()
    cbit = (pg["cbi"] + pg["tackles"]).astype("Float64")
    return {
        "xg": (pg["xg"], xg_ok),
        "xa": (pg["xa"], xg_ok),
        "goals_xg": (pg["goals_scored"], xg_ok),  # finishing vs the same xG window
        "assists_xg": (pg["assists"], xg_ok),  # FPL assists vs the same xA window
        "cbit": (cbit, dc_ok),
        "cbirt": ((cbit + pg["recoveries"]).astype("Float64"), dc_ok),
        "saves": (pg["saves"], pd.Series(True, index=pg.index)),
        "yc": (pg["yellow_cards"], pd.Series(True, index=pg.index)),
        "rc": (pg["red_cards"], pd.Series(True, index=pg.index)),
    }


def _bps_design(d: pd.DataFrame) -> np.ndarray:
    cols = [d[c].to_numpy(dtype=float) for c in BPS_REG_FEATURES]
    mins = d["minutes"].to_numpy(dtype=float)
    return np.column_stack([np.ones(len(d)), mins / 90.0, (mins >= 60).astype(float), *cols])


# -- holdout evaluation ----------------------------------------------------


def _brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def evaluate_holdout(holdout_season: str = "2025-26") -> None:
    """Fit priors before the holdout, score event probabilities on its played rows."""
    pg = pd.read_parquet(PLAYER_GW_PATH)
    model = EventRatesModel().fit(pg[pg["season"] < holdout_season])
    rates = model.transform(pg)
    test = rates[(rates["season"] == holdout_season) & (rates["minutes"] > 0)].copy()
    mins = test["minutes"].to_numpy(dtype=float)
    print(
        f"priors fitted on {(pg['season'] < holdout_season).sum():,} rows | "
        f"holdout {holdout_season}: {len(test):,} played player-fixtures"
    )

    # Goals: P(anytime) from shrunken xg90 x finishing, vs raw rate and position prior.
    lam = test["exp_goals90"].to_numpy() * mins / 90.0
    y_goal = (test["goals_scored"] > 0).to_numpy(dtype=float)
    pos_prior = test["position"].map(model.pos_priors_["xg"]).astype(float).to_numpy()
    raw = np.where(test["exposure_xg_90"] > 2, test["xg90_raw"].fillna(0.0).to_numpy(), pos_prior)
    print("\ngoals   P(anytime):")
    print(
        f"  Brier: shrunken {_brier(1 - np.exp(-lam), y_goal):.4f} | "
        f"raw-rate {_brier(1 - np.exp(-raw * mins / 90.0), y_goal):.4f} | "
        f"position-prior {_brier(1 - np.exp(-pos_prior * mins / 90.0), y_goal):.4f}"
    )
    print(f"  total E[goals] {lam.sum():.0f} vs actual {test['goals_scored'].sum():.0f}")

    lam_a = test["exp_assists90"].to_numpy() * mins / 90.0
    y_ass = (test["assists"] > 0).to_numpy(dtype=float)
    pos_prior_a = test["position"].map(model.pos_priors_["xa"]).astype(float).to_numpy()
    raw_a = np.where(
        test["exposure_xg_90"] > 2, test["xa90_raw"].fillna(0.0).to_numpy(), pos_prior_a
    )
    print("assists P(anytime):")
    print(
        f"  Brier: shrunken {_brier(1 - np.exp(-lam_a), y_ass):.4f} | "
        f"raw-rate {_brier(1 - np.exp(-raw_a * mins / 90.0), y_ass):.4f} | "
        f"position-prior {_brier(1 - np.exp(-pos_prior_a * mins / 90.0), y_ass):.4f}"
    )
    print(f"  total E[assists] {lam_a.sum():.0f} vs actual {test['assists'].sum():.0f}")

    # Defensive contribution threshold.
    dct = test[(test["position"] != "GKP") & test["cbi"].notna()].copy()
    dct["_count"] = np.where(
        dct["position"] == "DEF",
        dct["cbi"] + dct["tackles"],
        dct["cbi"] + dct["tackles"] + dct["recoveries"],
    )
    tau = dct["position"].map(model.dc_threshold).astype(int)
    y_dc = (dct["_count"] >= tau).to_numpy(dtype=float)
    p_dc = model.p_dc(dct, dct["minutes"].to_numpy(dtype=float))
    p_base = dct["position"].map(model.dc_base_).astype(float).to_numpy()
    print("\nDC threshold (phi " + str({p: round(v, 2) for p, v in model.dc_phi_.items()}) + "):")
    print(f"  Brier: model {_brier(p_dc, y_dc):.4f} | position-base {_brier(p_base, y_dc):.4f}")
    cal = (
        pd.DataFrame({"p": p_dc, "y": y_dc})
        .assign(bin=lambda d: pd.cut(d["p"], np.arange(0, 1.05, 0.1)))
        .groupby("bin", observed=True)
        .agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean"))
    )
    print(cal.to_string(float_format=lambda v: f"{v:.3f}"))

    # GK saves.
    gk = test[(test["position"] == "GKP") & (test["minutes"] >= 60)]
    pred_s = gk["saves90"].to_numpy() * gk["minutes"].to_numpy(dtype=float) / 90.0
    base_s = gk["position"].map(model.pos_priors_["saves"]).astype(float).to_numpy()
    base_s = base_s * gk["minutes"].to_numpy(dtype=float) / 90.0
    y_s = gk["saves"].to_numpy(dtype=float)
    print(
        f"\nGK saves: MAE model {np.mean(np.abs(pred_s - y_s)):.2f} vs position-prior "
        f"{np.mean(np.abs(base_s - y_s)):.2f} | total {pred_s.sum():.0f} vs actual {y_s.sum():.0f}"
    )

    # Yellow cards.
    p_yc = 1 - np.exp(-test["yc90"].to_numpy() * mins / 90.0)
    y_yc = (test["yellow_cards"] > 0).to_numpy(dtype=float)
    pos_yc = test["position"].map(model.pos_priors_["yc"]).astype(float).to_numpy()
    p_yc_base = 1 - np.exp(-pos_yc * mins / 90.0)
    print(
        f"yellows P(card): Brier model {_brier(p_yc, y_yc):.4f} vs position {_brier(p_yc_base, y_yc):.4f}"
    )

    # BPS model quality + bonus magnetism persistence.
    pred_bps = np.full(len(test), np.nan)
    for pos, coefs in model.bps_coefs_.items():
        m = (test["position"] == pos).to_numpy()
        pred_bps[m] = _bps_design(test[m]) @ coefs
    resid = test["bps"].to_numpy(dtype=float) - pred_bps
    r2 = 1 - np.var(resid) / np.var(test["bps"].to_numpy(dtype=float))
    est = test[test["exposure_90"] >= 10]
    persist = float(
        np.corrcoef(est["bps_res90"], est["bps"] - pred_bps[test["exposure_90"] >= 10])[0, 1]
    )
    print(
        f"BPS event model holdout R2 {r2:.3f}; magnetism persistence r {persist:.3f} (n={len(est):,})"
    )

    # Sanity: end-of-season rate leaders.
    last = test.groupby("code").tail(1)
    est = last[last["exposure_90"] >= 8]
    print("\ntop exp_goals90 (end of season, >=8 effective 90s):")
    cols = ["player", "team", "position", "exp_goals90", "fin_mult", "xa90"]
    print(
        est.nlargest(6, "exp_goals90")[cols].to_string(
            index=False, float_format=lambda v: f"{v:.2f}"
        )
    )
    print("\ntop xa90:")
    print(est.nlargest(6, "xa90")[cols].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    defs = est[est["position"] == "DEF"].copy()
    defs["p_dc_90min"] = model.p_dc(defs, np.full(len(defs), 90.0))
    print("\ntop DEF P(DC | 90 min):")
    print(
        defs.nlargest(6, "p_dc_90min")[["player", "team", "dc90", "p_dc_90min"]].to_string(
            index=False, float_format=lambda v: f"{v:.2f}"
        )
    )


if __name__ == "__main__":
    evaluate_holdout()
