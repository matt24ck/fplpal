"""Chip advisor: per-chip expected value across the projection window.

PLAN.md §5's fourth optimizer. For each chip still in hand, computes the
expected points it would add in every gameweek of the visible projection
window, on top of the transfer planner's trajectory (chips interact with
transfers — a bench boost is worth more the week after a wildcard builds a
deep bench, so the baseline must be the *planned* squad each week, not a
frozen one):

- **Triple captain**: the planned captain's xPts that week — the extra
  armband multiple. Peaks on double gameweeks (``n_fixtures`` is already
  baked into per-GW xPts).
- **Bench boost**: the planned bench's xPts, discounted by the small
  autosub credit those players would earn anyway.
- **Free hit**: the best single-week squad money can buy (one MILP solve at
  current squad value + bank) minus the planned XI that week. Pays on
  blanks and doubles.
- **Wildcard**: a from-scratch squad optimized for the remaining window,
  held (with weekly re-lineup) to the window's end, minus what the transfer
  plan would earn anyway over those weeks — PLAN §5's "(optimal − current)
  minus what the plan achieves" formula. Slightly conservative: the
  post-wildcard squad is assumed to stop transferring inside the window.

Honesty note carried in every payload: the advisor sees only the projection
window (6-8 GWs). "No strong week visible" is a real and common answer —
especially for second-half chips whose best windows (blanks/doubles) are
beyond the horizon.

Run a smoke test on live data: ``python -m engine.optimize.chips``
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from engine.config.season import SeasonRules, load_season
from engine.optimize.squad import BENCH_WEIGHTS, optimize_lineup, optimize_squad
from engine.optimize.transfers import GW_DISCOUNT, TransferPlan, optimize_transfers

CHIPS = ("wildcard", "freehit", "bboost", "triple_captain")


@dataclass
class ChipWeek:
    gw: int
    ev: float  # expected extra points from playing the chip this GW
    detail: str  # e.g. captain name, bench names, squad turnover


@dataclass
class ChipAdvice:
    chip: str
    weeks: list[ChipWeek]
    best: ChipWeek | None = field(default=None)

    def __post_init__(self) -> None:
        if self.weeks and self.best is None:
            self.best = max(self.weeks, key=lambda w: w.ev)


def advise_chips(
    projections: pd.DataFrame,
    squad: dict[int, int],
    bank: int,
    free_transfers: int,
    rules: SeasonRules | None = None,
    discount: float = GW_DISCOUNT,
    chips: tuple[str, ...] = CHIPS,
    plan: TransferPlan | None = None,
    time_limit: float | None = 15.0,
) -> dict[str, ChipAdvice]:
    """Per-chip EV per window GW. Same inputs as ``optimize_transfers``
    (``squad`` maps owned code -> sell value in tenths); pass ``plan`` to
    reuse an already-solved trajectory."""
    rules = rules or load_season()
    if plan is None:
        plan = optimize_transfers(
            projections, squad, bank=bank, free_transfers=free_transfers,
            rules=rules, discount=discount, time_limit=time_limit,
        )  # fmt: skip
    budget_now = bank + sum(int(v) for v in squad.values())
    gws = [s.gw for s in plan.steps]

    out: dict[str, ChipAdvice] = {}
    if "triple_captain" in chips:
        out["triple_captain"] = ChipAdvice("triple_captain", [_tc_week(s) for s in plan.steps])
    if "bboost" in chips:
        out["bboost"] = ChipAdvice("bboost", [_bb_week(s) for s in plan.steps])
    if "freehit" in chips:
        out["freehit"] = ChipAdvice(
            "freehit", [_fh_week(projections, s, budget_now, rules) for s in plan.steps]
        )
    if "wildcard" in chips:
        # Continuation value of the plan from each week to the window end.
        plan_rest = {
            s.gw: sum(t.xpts_xi - rules.transfers.hit_cost * t.hits for t in plan.steps[i:])
            for i, s in enumerate(plan.steps)
        }
        out["wildcard"] = ChipAdvice(
            "wildcard",
            [
                _wc_week(projections, g, gws, budget_now, plan_rest[g], squad, discount, rules)
                for g in gws
            ],
        )
    return out


def _tc_week(step) -> ChipWeek:
    cap = step.squad[step.squad["is_captain"]]
    name = cap.iloc[0]["player"] if len(cap) else "—"
    ev = float(cap.iloc[0]["xpts"]) if len(cap) else 0.0
    return ChipWeek(gw=step.gw, ev=round(ev, 2), detail=name)


def _bb_week(step) -> ChipWeek:
    bench = step.squad[~step.squad["in_xi"]]
    w = bench["position"].map(BENCH_WEIGHTS)
    ev = float((bench["xpts"] * (1.0 - w)).sum())
    names = ", ".join(bench.sort_values("xpts", ascending=False)["player"].head(4))
    return ChipWeek(gw=step.gw, ev=round(ev, 2), detail=names)


def _fh_week(projections: pd.DataFrame, step, budget_now: int, rules: SeasonRules) -> ChipWeek:
    pool = _week_pool(projections, step.gw)
    sol = optimize_squad(pool, rules, budget=budget_now)
    ev = max(0.0, sol.xpts_xi - step.xpts_xi)
    cap = sol.squad[sol.squad["is_captain"]]
    detail = f"best XI {sol.xpts_xi:.1f} vs planned {step.xpts_xi:.1f}"
    if len(cap):
        detail += f", C {cap.iloc[0]['player']}"
    return ChipWeek(gw=step.gw, ev=round(ev, 2), detail=detail)


def _wc_week(
    projections: pd.DataFrame,
    g: int,
    gws: list[int],
    budget_now: int,
    plan_rest: float,
    squad: dict[int, int],
    discount: float,
    rules: SeasonRules,
) -> ChipWeek:
    rest = [w for w in gws if w >= g]
    pool = _suffix_pool(projections, rest, discount)
    scratch = optimize_squad(pool, rules, budget=budget_now)
    codes = list(scratch.squad["code"].astype(int))
    hold = _hold_over(projections, codes, rest, rules)
    ev = max(0.0, hold - plan_rest)
    turnover = len(set(codes) - set(int(c) for c in squad))
    return ChipWeek(
        gw=g,
        ev=round(ev, 2),
        detail=f"{turnover} new players, {hold:.1f} vs plan's {plan_rest:.1f} to window end",
    )


def _week_pool(projections: pd.DataFrame, gw: int) -> pd.DataFrame:
    p = projections[projections["gw"] == gw]
    cols = ["code", "player", "team", "position", "price", "xpts"]
    if "p_play" in p.columns:
        cols.append("p_play")
    return p[cols].drop_duplicates("code")


def _suffix_pool(projections: pd.DataFrame, rest: list[int], discount: float) -> pd.DataFrame:
    disc = {g: discount**i for i, g in enumerate(rest)}
    p = projections[projections["gw"].isin(rest)].copy()
    p["_dx"] = p["xpts"] * p["gw"].map(disc)
    agg = {
        "player": ("player", "first"), "team": ("team", "first"),
        "position": ("position", "first"), "price": ("price", "first"),
        "xpts": ("_dx", "sum"),
    }  # fmt: skip
    if "p_play" in p.columns:
        agg["p_play"] = ("p_play", "mean")
    return p.sort_values("gw").groupby("code", as_index=False).agg(**agg)


def _hold_over(
    projections: pd.DataFrame, codes: list[int], rest: list[int], rules: SeasonRules
) -> float:
    """Undiscounted XI+captain total from holding ``codes`` over ``rest``."""
    ident = (
        projections[projections["code"].isin(codes)]
        .sort_values("gw")
        .groupby("code")
        .agg(
            player=("player", "first"),
            team=("team", "first"),
            position=("position", "first"),
            price=("price", "first"),
        )  # fmt: skip
        .reindex(codes)
    )
    total = 0.0
    for g in rest:
        xp_g = projections[projections["gw"] == g].set_index("code")["xpts"]
        rows = ident.reset_index()
        rows["xpts"] = rows["code"].map(xp_g).fillna(0.0)
        total += optimize_lineup(
            rows[["code", "player", "team", "position", "price", "xpts"]], rules
        ).xpts_xi
    return float(total)


# -- smoke test on live data ------------------------------------------------


def _demo() -> None:
    from pathlib import Path

    live = Path(__file__).resolve().parents[2] / "data" / "live"
    per_gw = pd.read_parquet(live / "projections_gw.parquet")
    fixture = pd.read_parquet(live / "projections_fixture.parquet")
    prices = fixture.groupby("code").agg(price=("price", "first"), p_play=("p_start", "mean"))
    proj = per_gw.merge(prices, on="code", how="left")
    proj = proj[["code", "player", "team", "position", "price", "gw", "xpts", "p_play"]]

    pool = proj.groupby("code", as_index=False).agg(
        player=("player", "first"), team=("team", "first"), position=("position", "first"),
        price=("price", "first"), xpts=("xpts", "sum"), p_play=("p_play", "mean"),
    )  # fmt: skip
    draft = optimize_squad(pool)
    own = {int(r.code): int(r.price) for r in draft.squad.itertuples()}
    bank = load_season().squad.budget - int(draft.squad["price"].sum())

    for chip, adv in advise_chips(proj, own, bank=bank, free_transfers=1).items():
        best = adv.best
        print(f"{chip}: best GW{best.gw} +{best.ev:.1f} ({best.detail})")
        print("   " + " | ".join(f"GW{w.gw} {w.ev:.1f}" for w in adv.weeks))


if __name__ == "__main__":
    import sys

    if (sys.stdout.encoding or "").lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _demo()
