"""Squad and lineup optimization: MILP over projected points.

PLAN.md §5. Deterministic operations-research layer on top of Layer-4
projections — all advice is solved, not heuristic. This module covers the
GW1-critical scope:

- ``optimize_squad``: best 15 for a budget (2/5/5/3 shape, ≤3 per club,
  budget from season config), with the starting XI, formation, captain and
  vice chosen jointly.
- ``optimize_lineup``: best XI / formation / captain / vice / bench order
  from a fixed 15 (the "rate my draft" primitive).

Objective: XI points + captain doubling + a small vice term (vice value only
materializes when the captain misses) + bench players weighted by autosub
likelihood (position-level weights — the backup GK almost never autosubs in,
outfield bench does occasionally). Locked/excluded player lists support
"build around X" / "never Y" requests from the chat layer.

The multi-period transfer planner and chip advisor (PLAN §5) are in-season
deliverables and intentionally not here yet.

Solver: HiGHS via PuLP (CBC fallback). FPL scale (~700 binaries × 4 roles)
solves in well under a second.

Run a 2025-26 GW1 draft evaluation: ``python -m engine.optimize.squad``
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd
import pulp

from engine.config.season import SeasonRules, load_season

# P(a bench player's points reach the XI via autosub), by position.
BENCH_WEIGHTS = {"GKP": 0.04, "DEF": 0.16, "MID": 0.16, "FWD": 0.16}
# Weight on the vice-captain's points: ~P(captain misses the match).
VICE_WEIGHT = 0.07

REQUIRED_COLS = ["player", "team", "position", "price", "xpts"]


@dataclass
class SquadSolution:
    squad: pd.DataFrame = field(repr=False)  # 15 rows + in_xi/is_captain/is_vice/bench_order
    formation: str
    cost: float  # tenths of £m
    xpts_xi: float  # XI + captain doubling, no bench/vice terms
    objective: float  # full objective incl. bench + vice weights
    solve_seconds: float

    def summary(self) -> str:
        lines = [
            f"formation {self.formation} | cost £{self.cost / 10:.1f}m | "
            f"XI+captain xPts {self.xpts_xi:.1f} | solved in {self.solve_seconds * 1000:.0f}ms"
        ]
        xi = self.squad[self.squad["in_xi"]].sort_values(
            ["position", "xpts"],
            key=lambda s: (
                s.map({"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}) if s.name == "position" else -s
            ),
        )
        for r in xi.itertuples():
            tag = " (C)" if r.is_captain else " (V)" if r.is_vice else ""
            lines.append(f"  {r.position} {r.player}{tag} £{r.price / 10:.1f}m {r.xpts:.1f}xp")
        bench = self.squad[~self.squad["in_xi"]].sort_values("bench_order")
        lines.append(
            "  bench: " + ", ".join(f"{r.player} {r.xpts:.1f}xp" for r in bench.itertuples())
        )
        return "\n".join(lines)


def optimize_squad(
    players: pd.DataFrame,
    rules: SeasonRules | None = None,
    budget: int | None = None,
    locked: tuple = (),
    excluded: tuple = (),
    fix_squad: bool = False,
) -> SquadSolution:
    """Solve the squad MILP over a per-player projection table.

    ``players`` needs one row per candidate with REQUIRED_COLS (price in
    tenths of £m, ``xpts`` over the target horizon); ``p_play`` optional for
    bench ordering. ``locked``/``excluded`` match against ``player`` or
    ``code``. ``fix_squad=True`` turns this into lineup-only optimization
    (the 15 must be exactly the rows passed).
    """
    rules = rules or load_season()
    sq_rules = rules.squad
    budget = budget if budget is not None else sq_rules.budget

    p = players.reset_index(drop=True).copy()
    missing = [c for c in REQUIRED_COLS if c not in p.columns]
    if missing:
        raise ValueError(f"players table missing columns: {missing}")
    if fix_squad and len(p) != sq_rules.size:
        raise ValueError(f"fix_squad needs exactly {sq_rules.size} rows, got {len(p)}")

    n = len(p)
    xp = p["xpts"].to_numpy(dtype=float)
    price = p["price"].to_numpy(dtype=float)
    pos = p["position"].astype(str).to_numpy()
    bench_w = p["position"].map(BENCH_WEIGHTS).to_numpy(dtype=float)

    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    sq = pulp.LpVariable.dicts("sq", range(n), cat="Binary")
    xi = pulp.LpVariable.dicts("xi", range(n), cat="Binary")
    cap = pulp.LpVariable.dicts("cap", range(n), cat="Binary")
    vice = pulp.LpVariable.dicts("vice", range(n), cat="Binary")

    prob += pulp.lpSum(
        xi[i] * xp[i]
        + cap[i] * xp[i]
        + VICE_WEIGHT * vice[i] * xp[i]
        + bench_w[i] * (sq[i] - xi[i]) * xp[i]
        for i in range(n)
    )

    for position, count in sq_rules.positions.items():
        prob += pulp.lpSum(sq[i] for i in range(n) if pos[i] == position) == count
    prob += pulp.lpSum(sq[i] * price[i] for i in range(n)) <= budget
    for club in pd.unique(p["team"]):
        prob += (
            pulp.lpSum(sq[i] for i in range(n) if p.at[i, "team"] == club) <= sq_rules.max_per_club
        )

    prob += pulp.lpSum(xi[i] for i in range(n)) == 11
    for position, (lo, hi) in sq_rules.formation.items():
        in_pos = pulp.lpSum(xi[i] for i in range(n) if pos[i] == position)
        prob += in_pos >= lo
        prob += in_pos <= hi
    prob += pulp.lpSum(cap[i] for i in range(n)) == 1
    prob += pulp.lpSum(vice[i] for i in range(n)) == 1
    for i in range(n):
        prob += xi[i] <= sq[i]
        prob += cap[i] <= xi[i]
        prob += vice[i] <= xi[i]
        prob += cap[i] + vice[i] <= 1

    keys = set(locked)
    for i in range(n):
        ident = {p.at[i, "player"]} | ({p.at[i, "code"]} if "code" in p.columns else set())
        if fix_squad or ident & keys:
            prob += sq[i] == 1
        if ident & set(excluded):
            prob += sq[i] == 0

    t0 = time.perf_counter()
    prob.solve(_solver())
    elapsed = time.perf_counter() - t0
    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError(f"squad MILP not optimal: {pulp.LpStatus[prob.status]}")

    chosen = [i for i in range(n) if sq[i].value() > 0.5]
    out = p.loc[chosen].copy()
    out["in_xi"] = [xi[i].value() > 0.5 for i in chosen]
    out["is_captain"] = [cap[i].value() > 0.5 for i in chosen]
    out["is_vice"] = [vice[i].value() > 0.5 for i in chosen]
    out = _assign_bench_order(out)

    xi_rows = out[out["in_xi"]]
    counts = xi_rows["position"].value_counts()
    formation = f"{counts.get('DEF', 0)}-{counts.get('MID', 0)}-{counts.get('FWD', 0)}"
    xpts_xi = float(xi_rows["xpts"].sum() + xi_rows.loc[xi_rows["is_captain"], "xpts"].sum())
    return SquadSolution(
        squad=out.reset_index(drop=True),
        formation=formation,
        cost=float(out["price"].sum()),
        xpts_xi=xpts_xi,
        objective=float(pulp.value(prob.objective)),
        solve_seconds=elapsed,
    )


def optimize_lineup(squad15: pd.DataFrame, rules: SeasonRules | None = None) -> SquadSolution:
    """Best XI, formation, captain/vice, and bench order from a fixed 15."""
    return optimize_squad(squad15, rules=rules, budget=None, fix_squad=True)


def _assign_bench_order(out: pd.DataFrame) -> pd.DataFrame:
    """FPL bench: GK in slot 1, outfield in autosub priority (best first)."""
    out = out.copy()
    out["bench_order"] = 0
    bench = out[~out["in_xi"]]
    key = bench["xpts"] * bench["p_play"] if "p_play" in bench.columns else bench["xpts"]
    outfield = bench[bench["position"] != "GKP"].loc[
        key[bench["position"] != "GKP"].sort_values(ascending=False).index
    ]
    out.loc[bench[bench["position"] == "GKP"].index, "bench_order"] = 1
    out.loc[outfield.index, "bench_order"] = range(2, 2 + len(outfield))
    return out


def _solver():
    try:
        return pulp.HiGHS(msg=False)
    except Exception:
        return pulp.PULP_CBC_CMD(msg=0)


# -- holdout evaluation ----------------------------------------------------


def evaluate_gw1_draft(holdout_season: str = "2025-26", horizon: int = 6) -> None:
    """Draft a GW1 squad from pre-season projections; score it on realized points.

    Benchmarks: the same MILP fed last season's total points (the naive
    drafter), and the same MILP fed realized points (hindsight upper bound).
    Realized scoring holds the drafted XI and captain fixed for the horizon —
    no transfers or autosubs for any variant, so the comparison is symmetric.
    """
    from engine.models.points import PLAYER_GW_PATH, replay_season

    proj, _ = replay_season(holdout_season)
    gws = sorted(proj["gw"].unique())[:horizon]
    window = proj[proj["gw"].isin(gws)].copy()

    gw1_codes = set(window.loc[window["gw"] == gws[0], "code"])
    pool = (
        window[window["code"].isin(gw1_codes)]
        .sort_values("gw")
        .groupby("code", as_index=False)
        .agg(
            player=("player", "first"),
            team=("team", "first"),
            position=("position", "first"),
            price=("price", "first"),
            xpts=("xpts", "sum"),
            p_play=("p_start", "mean"),
            realized=("total_points", "sum"),
        )
    )

    pg = pd.read_parquet(PLAYER_GW_PATH)
    seasons = sorted(pg["season"].unique())
    prev_season = seasons[seasons.index(holdout_season) - 1]
    prev_last = (
        pg[pg["season"] == prev_season]
        .groupby("code", as_index=False)["total_points"]
        .sum()
        .rename(columns={"total_points": "prev_pts"})
    )
    pool = pool.merge(prev_last, on="code", how="left").fillna({"prev_pts": 0.0})

    rules = load_season()

    def realized_score(sol: SquadSolution) -> float:
        xi = sol.squad[sol.squad["in_xi"]]
        return float(xi["realized"].sum() + xi.loc[xi["is_captain"], "realized"].sum())

    print(f"\n== GW1 draft, optimized on model xPts (next {horizon} GWs) ==")
    model_sol = optimize_squad(pool, rules)
    print(model_sol.summary())

    naive_pool = pool.assign(xpts=pool["prev_pts"])
    naive_sol = optimize_squad(naive_pool, rules)
    print("\n== naive draft, optimized on last-season total points ==")
    print(naive_sol.summary())

    hind_pool = pool.assign(xpts=pool["realized"])
    hind_sol = optimize_squad(hind_pool, rules)

    print(f"\nrealized GW1-{gws[-1]} points (fixed XI + captain, no transfers/autosubs):")
    print(f"  model draft:     {realized_score(model_sol):.0f}")
    print(f"  naive draft:     {realized_score(naive_sol):.0f}")
    print(f"  hindsight bound: {realized_score(hind_sol):.0f}")

    sq = model_sol.squad
    checks = {
        "cost <= budget": sq["price"].sum() <= rules.squad.budget,
        "shape 2/5/5/3": sq["position"].value_counts().to_dict()
        == {k: v for k, v in rules.squad.positions.items()},
        "max 3 per club": int(sq["team"].value_counts().max()) <= rules.squad.max_per_club,
        "XI formation valid": all(
            lo <= (sq[sq["in_xi"]]["position"] == pos).sum() <= hi
            for pos, (lo, hi) in rules.squad.formation.items()
        ),
    }
    print(
        "\nconstraint checks: "
        + ", ".join(f"{k}: {'ok' if v else 'FAIL'}" for k, v in checks.items())
    )

    # Lineup-only path: shuffle the model squad and re-derive the XI.
    relineup = optimize_lineup(
        sq[["player", "team", "position", "price", "xpts", "p_play", "realized"]], rules
    )
    same = abs(relineup.xpts_xi - model_sol.xpts_xi) < 1e-6
    print(f"optimize_lineup on the drafted 15 reproduces the XI: {'ok' if same else 'FAIL'}")


if __name__ == "__main__":
    import sys

    if (sys.stdout.encoding or "").lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    evaluate_gw1_draft()
