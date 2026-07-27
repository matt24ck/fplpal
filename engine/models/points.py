"""Points assembly: expected FPL points per player-fixture, decomposed by source.

PLAN.md §4 Layer 4 — the layer that combines the stack:

    Layer 1 team strength  -> fixture goal expectations, P(CS), conceded dist
    Layer 2 minutes        -> p_start / p_cameo / p_60plus / expected minutes
    Layer 3 event rates    -> shrunken per-90 rates per player

into ``E[pts] = Σ P(event) × points(event, position)`` with every scoring
value taken from season config, never hardcoded. Output is one row per
player-fixture with named components (``pts_goals``, ``pts_cs``, ...), their
sum ``xpts``, and a variance estimate ``var_pts`` (captaincy and differential
advice need upside, not just means).

Assembly notes:

- Attacking rates scale with fixture difficulty: λ_fixture / baseline_lambda
  (the team's venue-averaged expectation vs an average opponent). GK save
  volume scales with opponent attack the same way.
- Saves and DC are conditioned on starting (E[minutes | start]); cameo
  contributions to those categories are negligible and ignored.
- Clean sheets use p_60plus × P(CS); goals-conceded pairs use the full-match
  conceded distribution × p_60plus (GK/DEF who play, play ~90).
- Bonus: E[BPS | plays] from the event-rate model's per-position BPS
  regression applied to *conditional-on-playing* event expectations (the
  regression was fit on played rows, so feeding it unconditional expectations
  would hand its intercept to every benchwarmer), plus the player's
  bonus-magnetism residual; converted to expected bonus by an exact
  Plackett-Luce top-3 allocation within each fixture over play-gated,
  temperature-scaled weights. Match bonus sums to 6 by construction (actual
  bonus can exceed 6 on BPS ties — a known small under-count).
- Variance sums per-component variances assuming independence (goal/assist
  and CS/conceded correlations ignored at this stage).
- Team-switch caveat: a transferred player's rates were earned at his old
  club; only fixture difficulty is adjusted, not team quality change.

The holdout evaluation replays 2025-26 point-in-time: minutes and rates
models fitted before the season, team strength refitted before every GW.

Run: ``python -m engine.models.points``
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import poisson, spearmanr

from engine.config.season import SeasonRules, load_season
from engine.models.event_rates import EventRatesModel
from engine.models.minutes import MinutesModel, build_minutes_dataset
from engine.models.team_strength import TeamStrengthModel

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYER_GW_PATH = REPO_ROOT / "data" / "features" / "player_gw.parquet"

DEFAULT_BONUS_TEMPERATURE = 5.0  # BPS units per Plackett-Luce log-odds unit

COMPONENTS = [
    "pts_appearance",
    "pts_goals",
    "pts_assists",
    "pts_cs",
    "pts_gc",
    "pts_saves",
    "pts_dc",
    "pts_bonus",
    "pts_cards",
    "pts_other",
]

# Columns carried from the rates-transformed player-GW frame into assembly.
ASSEMBLY_COLS = [
    "season", "gw", "fixture", "kickoff_time", "element", "code", "player", "position",
    "team", "opponent", "was_home", "price", "minutes", "total_points", "goals_scored",
    "assists", "clean_sheets", "goals_conceded", "saves", "penalties_saved",
    "penalties_missed", "yellow_cards", "red_cards", "own_goals", "bonus", "bps",
    "defensive_contribution", "exp_goals90", "exp_assists90", "dc90", "saves90", "yc90",
    "rc90", "og90", "pm90", "ps90", "bps_res90", "exposure_90",
]  # fmt: skip


def fixture_context(model: TeamStrengthModel, fixtures: pd.DataFrame) -> pd.DataFrame:
    """Per-(fixture, team) context rows from Layer 1: goal expectations,
    P(CS), conceded-pair moments, and the attack/saves fixture scalers.

    ``fixtures`` needs columns season/fixture/home/away.
    """
    league = model.league_lambda()
    rows = []
    for r in fixtures.itertuples():
        f = model.forecast(r.home, r.away)
        opp_pmf = {r.home: f.score_grid.sum(axis=0), r.away: f.score_grid.sum(axis=1)}
        lam = {r.home: f.lambda_home, r.away: f.lambda_away}
        p_cs = {r.home: f.p_cs_home, r.away: f.p_cs_away}
        for team, opp in ((r.home, r.away), (r.away, r.home)):
            pairs = np.arange(len(opp_pmf[team])) // 2
            rows.append(
                {
                    "season": r.season,
                    "fixture": r.fixture,
                    "team": team,
                    "lam_for": lam[team],
                    "lam_against": lam[opp],
                    "p_cs": p_cs[team],
                    "e_gc_pairs": float(opp_pmf[team] @ pairs),
                    "e_gc_pairs_sq": float(opp_pmf[team] @ pairs**2),
                    "scale_attack": lam[team] / model.baseline_lambda(team),
                    "scale_saves": lam[opp] / league,
                }
            )
    return pd.DataFrame(rows)


class PointsAssembler:
    """Combines minutes predictions, event rates, and fixture context into xPts.

    ``project`` expects one row per player-fixture carrying: position, season,
    fixture; the minutes-model outputs (p_start, p_cameo, p_60plus,
    e_min_given_start, e_minutes); the event-rate outputs (exp_goals90,
    exp_assists90, dc90, saves90, yc90, rc90, og90, pm90, ps90, bps_res90);
    and the fixture-context columns from ``fixture_context``.
    """

    def __init__(
        self,
        rules: SeasonRules,
        rates_model: EventRatesModel,
        bonus_temperature: float = DEFAULT_BONUS_TEMPERATURE,
    ) -> None:
        self.rules = rules
        self.rates_model = rates_model
        self.temperature = bonus_temperature

    def project(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.reset_index(drop=True).copy()
        s = self.rules.scoring
        pos = df["position"].astype(str)

        m90 = df["e_minutes"].to_numpy(dtype=float) / 90.0
        p_start = df["p_start"].to_numpy(dtype=float)
        p60 = df["p_60plus"].to_numpy(dtype=float)
        p_play = p_start + df["p_cameo"].to_numpy(dtype=float)

        # Appearance: outcomes {0, short, 60+}.
        df["pts_appearance"] = p_play * s.appearance_short + p60 * (
            s.appearance_60 - s.appearance_short
        )
        var_app = ((p_play - p60) * s.appearance_short**2 + p60 * s.appearance_60**2) - df[
            "pts_appearance"
        ] ** 2

        # Attacking, scaled by fixture difficulty.
        scale_att = df["scale_attack"].to_numpy(dtype=float)
        lam_g = df["exp_goals90"].to_numpy(dtype=float) * m90 * scale_att
        lam_a = df["exp_assists90"].to_numpy(dtype=float) * m90 * scale_att
        goal_val = pos.map(s.goal).to_numpy(dtype=float)
        df["pts_goals"] = lam_g * goal_val
        df["pts_assists"] = lam_a * s.assist

        # Clean sheets and goals conceded.
        cs_val = pos.map(s.clean_sheet).to_numpy(dtype=float)
        p_cs_player = p60 * df["p_cs"].to_numpy(dtype=float)
        df["pts_cs"] = cs_val * p_cs_player
        gc_val = pos.map(s.goals_conceded_per_2).to_numpy(dtype=float)
        e_pairs = p60 * df["e_gc_pairs"].to_numpy(dtype=float)
        df["pts_gc"] = gc_val * e_pairs
        var_gc = gc_val**2 * (p60 * df["e_gc_pairs_sq"].to_numpy(dtype=float) - e_pairs**2)

        # GK saves (per-3) and penalty saves, conditioned on starting.
        e_start_m90 = df["e_min_given_start"].to_numpy(dtype=float) / 90.0
        lam_s = (
            df["saves90"].to_numpy(dtype=float)
            * e_start_m90
            * df["scale_saves"].to_numpy(dtype=float)
        )
        e_sv, e_sv_sq = _floor_div_moments(lam_s, 3)
        is_gk = (pos == "GKP").to_numpy()
        lam_ps = df["ps90"].to_numpy(dtype=float) * m90
        df["pts_saves"] = np.where(
            is_gk, p_start * e_sv * s.saves_per_3 + s.penalty_save * lam_ps, 0.0
        )
        var_saves = np.where(
            is_gk,
            s.saves_per_3**2 * (p_start * e_sv_sq - (p_start * e_sv) ** 2)
            + s.penalty_save**2 * lam_ps,
            0.0,
        )

        # Defensive contribution (threshold hit), conditioned on starting.
        p_dc = self.rates_model.p_dc(df, df["e_min_given_start"].to_numpy(dtype=float)) * p_start
        dc_val = float(s.defensive_contribution.points)
        df["pts_dc"] = p_dc * dc_val

        # Cards, own goals, penalty misses.
        lam_yc = df["yc90"].to_numpy(dtype=float) * m90
        lam_rc = df["rc90"].to_numpy(dtype=float) * m90
        lam_og = df["og90"].to_numpy(dtype=float) * m90
        lam_pm = df["pm90"].to_numpy(dtype=float) * m90
        df["pts_cards"] = s.yellow_card * lam_yc + s.red_card * lam_rc
        df["pts_other"] = s.own_goal * lam_og + s.penalty_miss * lam_pm

        # Bonus via conditional expected BPS + within-fixture Plackett-Luce.
        e_bps_cond = self._expected_bps_given_play(df, p_start, p_play)
        df["e_bps"] = p_play * e_bps_cond
        e_bonus, var_bonus = self._expected_bonus(df, e_bps_cond, p_play)
        df["pts_bonus"] = e_bonus

        df["xpts"] = sum(df[c] for c in COMPONENTS)
        df["var_pts"] = (
            var_app
            + goal_val**2 * lam_g
            + s.assist**2 * lam_a
            + cs_val**2 * p_cs_player * (1 - p_cs_player)
            + var_gc
            + var_saves
            + dc_val**2 * p_dc * (1 - p_dc)
            + var_bonus
            + s.yellow_card**2 * lam_yc
            + s.red_card**2 * lam_rc
            + s.own_goal**2 * lam_og
            + s.penalty_miss**2 * lam_pm
        )
        return df

    def _expected_bps_given_play(
        self, df: pd.DataFrame, p_start: np.ndarray, p_play: np.ndarray
    ) -> np.ndarray:
        """E[BPS | plays]: the per-position BPS regression (fit on played rows)
        applied to conditional-on-playing event expectations."""
        p_playc = np.clip(p_play, 0.02, 1.0)
        m90c = np.clip(df["e_minutes"].to_numpy(dtype=float) / p_playc / 90.0, 0.0, 1.0)
        p60c = np.clip(df["p_60plus"].to_numpy(dtype=float) / p_playc, 0.0, 1.0)
        scale_att = df["scale_attack"].to_numpy(dtype=float)

        def per90(col: str) -> np.ndarray:
            return df[col].to_numpy(dtype=float) * m90c

        design = np.column_stack(
            [
                np.ones(len(df)),
                m90c,
                p60c,
                df["exp_goals90"].to_numpy(dtype=float) * m90c * scale_att,
                df["exp_assists90"].to_numpy(dtype=float) * m90c * scale_att,
                p60c * df["p_cs"].to_numpy(dtype=float),
                df["lam_against"].to_numpy(dtype=float) * m90c,
                df["saves90"].to_numpy(dtype=float)
                * (df["e_min_given_start"].to_numpy(dtype=float) / 90.0)
                * df["scale_saves"].to_numpy(dtype=float)
                * (p_start / p_playc),
                per90("ps90"),
                per90("pm90"),
                per90("yc90"),
                per90("rc90"),
                per90("og90"),
            ]
        )
        e_cond = np.zeros(len(df))
        pos_arr = df["position"].astype(str).to_numpy()
        for pos, coefs in self.rates_model.bps_coefs_.items():
            m = pos_arr == pos
            e_cond[m] = design[m] @ coefs
        e_cond += df["bps_res90"].to_numpy(dtype=float) * m90c
        return np.maximum(e_cond, 0.0)

    def _expected_bonus(
        self, df: pd.DataFrame, e_bps_cond: np.ndarray, p_play: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Exact Plackett-Luce top-3 within each fixture over play-gated weights.

        P(j 3rd) = w_j Σ_{i≠j} Σ_{k≠i,j} P(i 1st) P(k 2nd|i) / (S - w_i - w_k)
        reduces to an O(n²) matrix identity per fixture.
        """
        b1, b2, b3 = self.rules.scoring.bonus
        w = np.clip(p_play, 0.02, 1.0) * np.exp(np.clip(e_bps_cond, 0.0, 60.0) / self.temperature)

        p1 = np.zeros(len(df))
        p2 = np.zeros(len(df))
        p3 = np.zeros(len(df))
        for idx in df.groupby(["season", "fixture"]).indices.values():
            wi = w[idx]
            total = wi.sum()
            d = total - wi
            p1i = wi / total
            a = p1i / d
            p2i = wi * (a.sum() - a)
            C = (p1i / d)[:, None] * (wi[None, :] / np.maximum(d[:, None] - wi[None, :], 1e-12))
            np.fill_diagonal(C, 0.0)
            p3i = np.maximum(wi * (C.sum() - C.sum(axis=1) - C.sum(axis=0)), 0.0)
            p3i /= p3i.sum()
            p1[idx], p2[idx], p3[idx] = p1i, p2i, p3i

        e_bonus = b1 * p1 + b2 * p2 + b3 * p3
        var = b1**2 * p1 + b2**2 * p2 + b3**2 * p3 - e_bonus**2
        return e_bonus, var


def aggregate_gw(proj: pd.DataFrame) -> pd.DataFrame:
    """Sum fixture projections to player-gameweek level (double GWs collapse)."""
    sums = {c: (c, "sum") for c in [*COMPONENTS, "xpts", "var_pts"] if c in proj.columns}
    return proj.groupby(["season", "gw", "code"], as_index=False).agg(
        player=("player", "first"),
        team=("team", "first"),
        position=("position", "first"),
        n_fixtures=("fixture", "size"),
        **sums,
    )


def _floor_div_moments(lam: np.ndarray, div: int, kmax: int = 24) -> tuple[np.ndarray, np.ndarray]:
    """E[floor(X/div)] and E[floor(X/div)^2] for X ~ Poisson(lam), elementwise."""
    k = np.arange(kmax + 1)
    pmf = poisson.pmf(k[:, None], np.asarray(lam, dtype=float)[None, :])
    f = (k // div).astype(float)
    return f @ pmf, (f**2) @ pmf


# -- holdout evaluation ----------------------------------------------------


def _rank_corr(proj: pd.DataFrame, col: str) -> float:
    """Mean Spearman(pred, actual) within (GW, position), weighted by cell size."""
    corrs, ns = [], []
    for _, d in proj.groupby(["gw", "position"], observed=True):
        d = d.dropna(subset=[col])
        if len(d) < 8 or d[col].nunique() < 2:
            continue
        rho = spearmanr(d[col], d["total_points"]).statistic
        if not np.isnan(rho):
            corrs.append(rho)
            ns.append(len(d))
    return float(np.average(corrs, weights=ns))


def _topk_overlap(proj: pd.DataFrame, col: str, k: int = 10) -> float:
    """Mean overlap of predicted vs actual top-k within (GW, position)."""
    hits, total = 0, 0
    for _, d in proj.groupby(["gw", "position"], observed=True):
        if len(d) < 15:
            continue
        hits += len(
            set(d.nlargest(k, col)["element"]) & set(d.nlargest(k, "total_points")["element"])
        )
        total += k
    return hits / total


def replay_season(
    holdout_season: str = "2025-26", verbose: bool = True
) -> tuple[pd.DataFrame, EventRatesModel]:
    """Point-in-time replay of a season through the full stack.

    Minutes and event-rate models are fitted strictly before the season; team
    strength is refitted before every GW. Returns the projected frame (one row
    per player-fixture with components, xpts, var_pts, and realized stats)
    plus the fitted rates model. Note: each GW's projection uses information
    as of that GW — a multi-GW window read from this frame is fractionally
    fresher than a projection frozen at the window start would be.
    """
    from engine.features.matches import load_matches

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    pg = pd.read_parquet(PLAYER_GW_PATH)

    log("fitting minutes model on pre-holdout seasons...")
    mdata = build_minutes_dataset(pg)
    labeled = mdata.dropna(subset=["y_class"])
    mm = MinutesModel().fit(labeled[labeled["season"] < holdout_season])
    m_test = mdata[mdata["season"] == holdout_season]
    minutes_df = m_test[["season", "fixture", "element"]].join(mm.predict(m_test))

    log("fitting event-rate priors and transforming...")
    rm = EventRatesModel().fit(pg[pg["season"] < holdout_season])
    rates = rm.transform(pg)
    base = rates.loc[rates["season"] == holdout_season, ASSEMBLY_COLS]
    df = base.merge(minutes_df, on=["season", "fixture", "element"], how="inner")

    log("fitting team strength before each GW...")
    matches = load_matches()
    hold = matches[matches["season"] == holdout_season]
    ctx_parts = []
    for i, (_, md) in enumerate(hold.groupby("gw")):
        tm = TeamStrengthModel().fit(matches, as_of=md["kickoff_time"].min())
        ctx_parts.append(fixture_context(tm, md))
        if verbose and (i + 1) % 10 == 0:
            print(f"  ...{i + 1} GWs")
    df = df.merge(pd.concat(ctx_parts), on=["season", "fixture", "team"], how="inner")
    log(f"assembled {len(df):,} player-fixture rows ({len(base):,} in holdout)")

    proj = PointsAssembler(load_season(), rm).project(df)
    return proj, rm


def replay_season_frozen(
    holdout_season: str = "2025-26",
    horizon: int = 6,
    verbose: bool = True,
    decision_gws: list[int] | None = None,
) -> pd.DataFrame:
    """Multi-GW replay with projections *frozen at each decision date*.

    For every decision GW g, projects the window g..g+horizon-1 using only
    information available before GW g — the exact regime the live pipeline
    runs in (future rows blanked to the cold-start shape, features built one
    target GW at a time so phantom rows never see each other, team strength
    as of the decision date). This is what a transfer planner deciding before
    GW g would actually have seen; ``replay_season``'s frame is fractionally
    fresher for later window weeks and would flatter a multi-GW backtest.

    Returns per-(decision_gw, gw, code) rows: xpts, price known at the
    decision date, p_play, n_fixtures. News-blind like the rest of the
    replay (no historical injury flags).
    """
    from engine.features.historical_gw import FLOAT_COLS, INT_COLS, NULLABLE_INT_COLS
    from engine.features.matches import load_matches

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    pg = pd.read_parquet(PLAYER_GW_PATH)
    seasons = sorted(pg["season"].unique())
    prev_season = seasons[seasons.index(holdout_season) - 1]
    hist_pre = pg[pg["season"] < holdout_season]
    prev = pg[pg["season"] == prev_season]
    hold = pg[pg["season"] == holdout_season]
    gws = sorted(hold["gw"].unique())

    log("fitting minutes + event-rate models on pre-holdout seasons...")
    mdata = build_minutes_dataset(pg)
    labeled = mdata.dropna(subset=["y_class"])
    mm = MinutesModel().fit(labeled[labeled["season"] < holdout_season])
    rm = EventRatesModel().fit(hist_pre)

    # Price known at each decision date: last observed price per (code, gw).
    prices = (
        hold.groupby(["gw", "code"], as_index=False)
        .agg(price=("price", "first"))
        .pivot(index="code", columns="gw", values="price")
        .reindex(columns=gws)
        .ffill(axis=1)
        .bfill(axis=1)
    )

    matches = load_matches()
    hold_matches = matches[matches["season"] == holdout_season]

    def blank(rows: pd.DataFrame, decision_gw: int) -> pd.DataFrame:
        """Holdout rows reduced to the cold-start shape the models train on."""
        out = rows.copy()
        for col in NULLABLE_INT_COLS:
            out[col] = pd.Series(pd.NA, index=out.index, dtype="Int64")
        for col in INT_COLS:
            out[col] = 0
        for col in FLOAT_COLS:
            out[col] = pd.Series(pd.NA, index=out.index, dtype="Float64")
        out["price"] = out["code"].map(prices[decision_gw]).fillna(out["price"]).astype(int)
        return out

    frames = []
    for g in decision_gws or gws:
        window = [w for w in gws if g <= w < g + horizon]
        blanked = {w: blank(hold[hold["gw"] == w], g) for w in window}
        real_before = hold[hold["gw"] < g]

        # Event rates: one transform per decision — blanked rows contribute
        # nothing to the decayed sums, so the whole window batches safely.
        rates_frame = pd.concat([hist_pre, real_before, *blanked.values()], ignore_index=True)
        rates = rm.transform(rates_frame)
        base = rates.loc[(rates["season"] == holdout_season) & (rates["gw"] >= g), ASSEMBLY_COLS]

        # Minutes: shift-based features would read phantom rows as real
        # matches, so build one target GW (and one fixture-rank, for DGWs)
        # at a time against only pre-decision history.
        minutes_parts = []
        for w in window:
            bw = blanked[w].sort_values("kickoff_time")
            rank = bw.groupby("element").cumcount()
            for r in sorted(rank.unique()):
                md = build_minutes_dataset(
                    pd.concat([prev, real_before, bw[rank == r]], ignore_index=True)
                )
                rows_m = md[(md["season"] == holdout_season) & (md["gw"] == w)]
                minutes_parts.append(
                    rows_m[["season", "fixture", "element"]].join(mm.predict(rows_m))
                )
        minutes_df = pd.concat(minutes_parts, ignore_index=True)

        tm = TeamStrengthModel().fit(
            matches, as_of=hold_matches.loc[hold_matches["gw"] == g, "kickoff_time"].min()
        )
        fixtures_df = (
            hold[hold["gw"].isin(window)][["season", "fixture", "team", "opponent", "was_home"]]
            .query("was_home")
            .drop_duplicates("fixture")
            .rename(columns={"team": "home", "opponent": "away"})
        )
        ctx = fixture_context(tm, fixtures_df)

        df = base.merge(minutes_df, on=["season", "fixture", "element"], how="inner").merge(
            ctx, on=["season", "fixture", "team"], how="inner"
        )
        proj = PointsAssembler(load_season(), rm).project(df)
        per_gw = (
            proj.groupby(["gw", "code"], as_index=False)
            .agg(
                player=("player", "first"),
                team=("team", "first"),
                position=("position", "first"),
                price=("price", "first"),
                n_fixtures=("fixture", "size"),
                xpts=("xpts", "sum"),
                p_play=("p_start", "mean"),
            )
            .assign(decision_gw=g)
        )
        frames.append(per_gw)
        log(f"  decision GW{g}: window GW{window[0]}-{window[-1]}, {len(per_gw):,} player-GWs")

    return pd.concat(frames, ignore_index=True)


def evaluate_holdout(holdout_season: str = "2025-26") -> None:
    """Replay the holdout point-in-time and score assembled xPts per player-fixture."""
    proj, rm = replay_season(holdout_season)
    rules = load_season()
    pg = pd.read_parquet(PLAYER_GW_PATH)

    actual = proj["total_points"].to_numpy(dtype=float)
    xp = proj["xpts"].to_numpy(dtype=float)
    print(
        f"\ntotal xPts {xp.sum():,.0f} vs actual {actual.sum():,.0f} "
        f"({xp.sum() / actual.sum() - 1:+.1%}) | RMSE {np.sqrt(np.mean((xp - actual) ** 2)):.3f}"
    )

    # Baselines: last-4 form and season points-per-game, point-in-time.
    h = pg[pg["season"] == holdout_season].sort_values(["element", "kickoff_time"])
    grp = h.groupby("element")["total_points"]
    h = h.assign(
        form4=grp.transform(lambda s: s.shift(1).rolling(4, min_periods=1).mean()),
        ppg=grp.transform(lambda s: s.shift(1).expanding().mean()),
    )
    proj = proj.merge(h[["fixture", "element", "form4", "ppg"]], on=["fixture", "element"])
    comp = proj.dropna(subset=["form4"])
    a = comp["total_points"].to_numpy(dtype=float)
    played = comp[comp["minutes"] > 0]
    print(f"\nvs baselines (GW2+, {len(comp):,} rows):")
    for name, col in [("model xpts", "xpts"), ("last-4 form", "form4"), ("season ppg", "ppg")]:
        rmse = float(np.sqrt(np.mean((comp[col].to_numpy(dtype=float) - a) ** 2)))
        print(
            f"  {name:12s} rank-corr {_rank_corr(comp, col):.3f} | "
            f"played-only {_rank_corr(played, col):.3f} | "
            f"top-10 overlap {_topk_overlap(comp, col):.3f} | RMSE {rmse:.3f}"
        )
    print(
        "  (all-rows rank-corr flatters exact-zero baselines: never-playing players form\n"
        "   actual-points tie groups a 0-prediction matches perfectly; played-only and\n"
        "   top-10 overlap are the decision-relevant metrics)"
    )

    # Component decomposition: predicted vs actual totals.
    s = rules.scoring
    pos = proj["position"].astype(str)
    mins = proj["minutes"].to_numpy(dtype=float)
    tau = pos.map(rm.dc_threshold).fillna(99).to_numpy(dtype=float)
    actual_comp = {
        "pts_appearance": np.where(mins >= 60, s.appearance_60, np.where(mins > 0, 1, 0)),
        "pts_goals": proj["goals_scored"] * pos.map(s.goal),
        "pts_assists": proj["assists"] * s.assist,
        "pts_cs": proj["clean_sheets"] * pos.map(s.clean_sheet),
        "pts_gc": (proj["goals_conceded"] // 2) * pos.map(s.goals_conceded_per_2),
        "pts_saves": (proj["saves"] // 3) * s.saves_per_3
        + proj["penalties_saved"] * s.penalty_save,
        "pts_dc": (proj["defensive_contribution"].astype(float) >= tau)
        * s.defensive_contribution.points,
        "pts_bonus": proj["bonus"],
        "pts_cards": proj["yellow_cards"] * s.yellow_card + proj["red_cards"] * s.red_card,
        "pts_other": proj["own_goals"] * s.own_goal + proj["penalties_missed"] * s.penalty_miss,
    }
    recon = sum(np.asarray(v, dtype=float) for v in actual_comp.values())
    exact = float(np.mean(np.isclose(recon, proj["total_points"]))) if len(proj) else 0.0
    print(f"\ncomponent totals (config reconstructs actual total on {exact:.1%} of rows):")
    for c in COMPONENTS:
        print(
            f"  {c:16s} predicted {proj[c].sum():8.0f} vs actual "
            f"{float(np.sum(actual_comp[c])):8.0f}"
        )

    eb = proj["pts_bonus"].to_numpy()
    ab = proj["bonus"].to_numpy(dtype=float)
    print(
        f"\nbonus allocation: MAE {np.mean(np.abs(eb - ab)):.3f} | corr {np.corrcoef(eb, ab)[0, 1]:.3f}"
    )

    # Season leaders: model's top 10 by summed xPts vs realized points.
    season_tot = (
        proj.groupby(["code", "player", "position"], observed=True)
        .agg(xpts=("xpts", "sum"), actual=("total_points", "sum"))
        .reset_index()
        .nlargest(10, "xpts")
    )
    print("\nmodel's season top 10 (summed per-GW xPts vs realized):")
    print(
        season_tot[["player", "position", "xpts", "actual"]].to_string(
            index=False, float_format=lambda v: f"{v:.0f}"
        )
    )

    ceil = proj.assign(ceiling=proj["xpts"] + 1.65 * np.sqrt(proj["var_pts"]))
    top_c = ceil.nlargest(5, "ceiling")
    print("\nhighest single-fixture ceilings (xpts + 1.65 sigma):")
    print(
        top_c[["player", "gw", "opponent", "xpts", "ceiling", "total_points"]].to_string(
            index=False, float_format=lambda v: f"{v:.1f}"
        )
    )


if __name__ == "__main__":
    import sys

    if (sys.stdout.encoding or "").lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    evaluate_holdout()
