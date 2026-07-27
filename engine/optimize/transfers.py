"""Multi-period transfer planner: MILP over a 5-8 GW horizon.

PLAN.md §5 — the in-season deliverable that replaces myopic week-to-week
transfer picking. One MILP decides, jointly for every gameweek in the
horizon: which transfers to make and when, whether a −4 hit pays for
itself, when to bank a free transfer instead, and the full lineup
(XI/formation/captain/vice) for every planned week.

Model per period t (a gameweek in the horizon):

- Squad evolution ``sq[i,t] = sq[i,t-1] + buy[i,t] - sell[i,t]`` from the
  user's current 15, with squad shape, ≤3-per-club, and budget flow
  ``bank[t] = bank[t-1] + Σ sell_value·sell - Σ price·buy ≥ 0``. Owned
  players sell at their FPL sell price (purchase + half the profit,
  rounded down); players bought inside the plan sell at what they cost
  (prices are assumed flat over the horizon). An initially-owned player
  cannot be re-bought after selling — his elevated sell value would
  otherwise survive the round trip.
- Free-transfer state ``f[t+1] = min(max_banked, max(f[t] - n[t], 0) + 1)``
  linearized as ``f[t+1] ≤ f[t] - n[t] + h[t] + 1`` with hits
  ``h[t] ≥ n[t] - f[t]``: because every hit costs points, the solver never
  inflates ``h`` beyond the true excess, and because banked transfers are
  only ever useful, ``f`` sits at its upper bound.
- Objective: discounted XI + captain points per period (γ^t, uncertainty
  about far GWs), the vice and bench-autosub weights from the squad MILP,
  minus ``hit_cost`` per (discounted) hit.

The first period of the plan is "this week's move"; later periods are the
plan's shadow — re-plan every week (the API always solves from the user's
live state, so the plan self-corrects as projections move).

Pool restriction keeps the MILP small: owned players plus, per position,
the top-k by discounted horizon points and the cheapest few (budget
enablers). ~150 players × 6 GWs solves in a few seconds with HiGHS.

Run a smoke test on live data: ``python -m engine.optimize.transfers``
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pandas as pd
import pulp

from engine.config.season import SeasonRules, load_season
from engine.optimize.squad import BENCH_WEIGHTS, VICE_WEIGHT

# Default per-GW discount on future-week points: far weeks are less certain
# and plans get revised. Tuned on the 2025-26 planner backtest sweep (γ=0.9
# scored 2,152 vs 2,059 undiscounted; single-season fit — the multi-season
# harness should revisit).
GW_DISCOUNT = 0.9

POOL_TOP_PER_POSITION = 25
POOL_CHEAP_PER_POSITION = 5

REQUIRED_COLS = ["code", "player", "team", "position", "price", "gw", "xpts"]


@dataclass
class PlannedMove:
    out_code: int
    out_player: str
    in_code: int
    in_player: str
    price_out: int  # sell value banked, tenths of £m
    price_in: int  # buy price paid, tenths


@dataclass
class GWStep:
    gw: int
    moves: list[PlannedMove]
    hits: int
    ft_before: int
    ft_after: int
    bank_after: int  # tenths
    xpts_xi: float  # XI + captain, undiscounted, this GW
    squad: pd.DataFrame = field(repr=False)  # 15 rows: code..xpts/in_xi/is_captain/is_vice


@dataclass
class TransferPlan:
    steps: list[GWStep]
    objective: float  # discounted, incl. bench/vice/hits
    xpts_total: float  # undiscounted XI+captain over the horizon, net of hits
    baseline_xpts: float  # same, with no transfers at all
    gain: float  # xpts_total - baseline_xpts
    discount: float
    solve_seconds: float

    def summary(self) -> str:
        lines = [
            f"plan over GW{self.steps[0].gw}-{self.steps[-1].gw} | "
            f"expected {self.xpts_total:.1f} pts vs {self.baseline_xpts:.1f} holding "
            f"({self.gain:+.1f}) | solved in {self.solve_seconds:.1f}s"
        ]
        for s in self.steps:
            if s.moves:
                mv = "; ".join(f"{m.out_player} → {m.in_player}" for m in s.moves)
                hit = f" (−{4 * s.hits} hit)" if s.hits else ""
                lines.append(
                    f"  GW{s.gw}: {mv}{hit} | bank £{s.bank_after / 10:.1f}m | FTs left {s.ft_after}"
                )
            else:
                lines.append(f"  GW{s.gw}: hold (bank FT → {s.ft_after})")
        return "\n".join(lines)


def select_pool(
    projections: pd.DataFrame,
    squad_codes: set[int],
    discount: float = GW_DISCOUNT,
    top_per_position: int = POOL_TOP_PER_POSITION,
    cheap_per_position: int = POOL_CHEAP_PER_POSITION,
) -> set[int]:
    """Candidate codes: owned + top-k by discounted horizon xPts + cheapest few
    per position (the enablers a budget-constrained plan routes money through)."""
    gws = sorted(projections["gw"].unique())
    disc = {g: discount**i for i, g in enumerate(gws)}
    p = projections.copy()
    p["_dx"] = p["xpts"] * p["gw"].map(disc)
    per = p.groupby("code", as_index=False).agg(
        position=("position", "first"), price=("price", "first"), dx=("_dx", "sum")
    )
    keep = set(squad_codes)
    for _, d in per.groupby("position"):
        keep |= set(d.nlargest(top_per_position, "dx")["code"])
        keep |= set(
            d.sort_values(["price", "dx"], ascending=[True, False]).head(cheap_per_position)["code"]
        )
    return keep


def optimize_transfers(
    projections: pd.DataFrame,
    squad: dict[int, int],
    bank: int,
    free_transfers: int,
    rules: SeasonRules | None = None,
    discount: float = GW_DISCOUNT,
    max_hits_per_gw: int = 3,
    forbid_first_gw: list[tuple[frozenset[int], frozenset[int]]] | None = None,
    force_move: bool = False,
    hold_first: bool = False,
    restrict_pool: bool = True,
    time_limit: float | None = 20.0,
) -> TransferPlan:
    """Solve the multi-period transfer MILP.

    ``projections``: one row per (code, gw) over the horizon with
    REQUIRED_COLS (price in tenths — current price, assumed flat; players
    with no fixture in a GW simply have no row and score 0).
    ``squad``: owned code -> sell value in tenths (FPL sell price).
    ``bank``/``free_transfers``: current state. ``forbid_first_gw`` excludes
    exact first-week (buys, sells) pairs (used to enumerate alternatives);
    ``force_move`` requires at least one first-week transfer; ``hold_first``
    forbids any (both used to price this week's decision against the plan).
    """
    rules = rules or load_season()
    sq_rules, tr_rules = rules.squad, rules.transfers

    missing = [c for c in REQUIRED_COLS if c not in projections.columns]
    if missing:
        raise ValueError(f"projections missing columns: {missing}")
    own = {int(k): int(v) for k, v in squad.items()}
    if len(own) != sq_rules.size:
        raise ValueError(f"squad needs exactly {sq_rules.size} players, got {len(own)}")

    pool = (
        select_pool(projections, set(own), discount)
        if restrict_pool
        else set(projections["code"].astype(int))
    )
    proj = projections[projections["code"].isin(pool)].copy()
    proj["code"] = proj["code"].astype(int)

    gws = sorted(proj["gw"].unique())
    T = len(gws)
    meta = (
        proj.sort_values("gw")
        .groupby("code")
        .agg(
            player=("player", "first"),
            team=("team", "first"),
            position=("position", "first"),
            price=("price", "first"),
        )
    )
    missing_own = [c for c in own if c not in meta.index]
    if missing_own:
        raise ValueError(f"owned players missing from projections: {missing_own}")
    codes = list(meta.index)
    n = len(codes)
    idx = {c: i for i, c in enumerate(codes)}
    xp = (
        proj.pivot_table(index="code", columns="gw", values="xpts", aggfunc="sum")
        .reindex(index=codes, columns=gws)
        .fillna(0.0)
        .to_numpy(dtype=float)
    )
    price = meta["price"].to_numpy(dtype=int)
    pos = meta["position"].astype(str).to_numpy()
    team = meta["team"].astype(str).to_numpy()
    bench_w = meta["position"].map(BENCH_WEIGHTS).to_numpy(dtype=float)
    owned0 = [1 if c in own else 0 for c in codes]
    # Sell value: owned at their FPL sell price, in-plan buys at cost.
    sell_val = [own.get(c, int(meta.at[c, "price"])) for c in codes]

    prob = pulp.LpProblem("fpl_transfers", pulp.LpMaximize)
    rng, ts = range(n), range(T)
    sq = pulp.LpVariable.dicts("sq", (rng, ts), cat="Binary")
    xi = pulp.LpVariable.dicts("xi", (rng, ts), cat="Binary")
    cap = pulp.LpVariable.dicts("cap", (rng, ts), cat="Binary")
    vice = pulp.LpVariable.dicts("vice", (rng, ts), cat="Binary")
    buy = pulp.LpVariable.dicts("buy", (rng, ts), cat="Binary")
    sell = pulp.LpVariable.dicts("sell", (rng, ts), cat="Binary")
    hits = pulp.LpVariable.dicts("hits", ts, lowBound=0, upBound=max_hits_per_gw, cat="Integer")
    ft = pulp.LpVariable.dicts("ft", ts, lowBound=0, upBound=tr_rules.max_banked, cat="Integer")
    bk = pulp.LpVariable.dicts("bank", ts, lowBound=0)

    disc = [discount**t for t in ts]
    prob += pulp.lpSum(
        disc[t]
        * (
            pulp.lpSum(
                xp[i][t] * (xi[i][t] + cap[i][t] + VICE_WEIGHT * vice[i][t])
                + xp[i][t] * bench_w[i] * (sq[i][t] - xi[i][t])
                for i in rng
            )
            - tr_rules.hit_cost * hits[t]
        )
        for t in ts
    )

    for t in ts:
        n_t = pulp.lpSum(buy[i][t] for i in rng)
        # Squad evolution + money flow.
        for i in rng:
            prev = owned0[i] if t == 0 else sq[i][t - 1]
            prob += sq[i][t] == prev + buy[i][t] - sell[i][t]
            prob += buy[i][t] + sell[i][t] <= 1
            if owned0[i]:
                prob += buy[i][t] == 0  # sell price would not survive a re-buy
        prev_bank = bank if t == 0 else bk[t - 1]
        prob += bk[t] == prev_bank + pulp.lpSum(
            sell_val[i] * sell[i][t] - price[i] * buy[i][t] for i in rng
        )
        # Free-transfer state and hits.
        prev_ft = free_transfers if t == 0 else ft[t - 1]
        prob += hits[t] >= n_t - prev_ft
        prob += hits[t] <= n_t
        if t + 1 < T:
            prob += ft[t] <= prev_ft - n_t + hits[t] + 1
            prob += ft[t] <= tr_rules.max_banked
        # Squad shape, clubs, lineup.
        for position, count in sq_rules.positions.items():
            prob += pulp.lpSum(sq[i][t] for i in rng if pos[i] == position) == count
        for club in set(team):
            prob += pulp.lpSum(sq[i][t] for i in rng if team[i] == club) <= sq_rules.max_per_club
        prob += pulp.lpSum(xi[i][t] for i in rng) == 11
        for position, (lo, hi) in sq_rules.formation.items():
            in_pos = pulp.lpSum(xi[i][t] for i in rng if pos[i] == position)
            prob += in_pos >= lo
            prob += in_pos <= hi
        prob += pulp.lpSum(cap[i][t] for i in rng) == 1
        prob += pulp.lpSum(vice[i][t] for i in rng) == 1
        for i in rng:
            prob += xi[i][t] <= sq[i][t]
            prob += cap[i][t] <= xi[i][t]
            prob += vice[i][t] <= xi[i][t]
            prob += cap[i][t] + vice[i][t] <= 1

    if force_move:
        prob += pulp.lpSum(buy[i][0] for i in rng) >= 1
    if hold_first:
        prob += pulp.lpSum(buy[i][0] for i in rng) == 0
    for buys, sells in forbid_first_gw or []:
        prob += (
            pulp.lpSum(buy[idx[c]][0] for c in buys if c in idx)
            + pulp.lpSum(sell[idx[c]][0] for c in sells if c in idx)
        ) <= len(buys) + len(sells) - 1

    t0 = time.perf_counter()
    prob.solve(_solver(time_limit))
    elapsed = time.perf_counter() - t0
    if pulp.LpStatus[prob.status] != "Optimal" and sq[0][0].value() is None:
        raise RuntimeError(f"transfer MILP infeasible: {pulp.LpStatus[prob.status]}")

    # Report FT/hit state from the analytic recursion over the executed moves
    # (the MILP's ft/hits are slack-bounded; the recursion is the game rule).
    steps: list[GWStep] = []
    cur_ft = free_transfers
    for t in ts:
        moves = _moves(codes, meta, sell_val, buy, sell, t)
        n_moves = len(moves)
        h = max(0, n_moves - cur_ft)
        ft_after = min(tr_rules.max_banked, max(cur_ft - n_moves, 0) + 1)
        rows = []
        for i in rng:
            if (sq[i][t].value() or 0) > 0.5:
                rows.append(
                    {
                        "code": codes[i],
                        "player": meta.at[codes[i], "player"],
                        "team": team[i],
                        "position": pos[i],
                        "price": int(price[i]),
                        "xpts": float(xp[i][t]),
                        "in_xi": (xi[i][t].value() or 0) > 0.5,
                        "is_captain": (cap[i][t].value() or 0) > 0.5,
                        "is_vice": (vice[i][t].value() or 0) > 0.5,
                    }
                )
        sq_df = pd.DataFrame(rows)
        xi_df = sq_df[sq_df["in_xi"]]
        xpts_xi = float(xi_df["xpts"].sum() + xi_df.loc[xi_df["is_captain"], "xpts"].sum())
        steps.append(
            GWStep(
                gw=int(gws[t]),
                moves=moves,
                hits=h,
                ft_before=cur_ft,
                ft_after=ft_after,
                bank_after=int(round(bk[t].value())),
                xpts_xi=xpts_xi,
                squad=sq_df,
            )
        )
        cur_ft = ft_after

    total_hits = sum(s.hits for s in steps)
    xpts_total = sum(s.xpts_xi for s in steps) - tr_rules.hit_cost * total_hits
    baseline = _hold_xpts(proj, own, gws, rules)
    return TransferPlan(
        steps=steps,
        objective=float(pulp.value(prob.objective)),
        xpts_total=xpts_total,
        baseline_xpts=baseline,
        gain=xpts_total - baseline,
        discount=discount,
        solve_seconds=elapsed,
    )


def _moves(codes, meta, sell_val, buy, sell, t) -> list[PlannedMove]:
    """Pair the period's sells with buys, same-position first (presentation only)."""
    bought = [i for i, c in enumerate(codes) if (buy[i][t].value() or 0) > 0.5]
    sold = [i for i, c in enumerate(codes) if (sell[i][t].value() or 0) > 0.5]
    moves = []
    for b in bought:
        pos_b = meta.iloc[b]["position"]
        s = next((s for s in sold if meta.iloc[s]["position"] == pos_b), sold[0] if sold else None)
        if s is None:
            continue
        sold.remove(s)
        moves.append(
            PlannedMove(
                out_code=int(codes[s]),
                out_player=str(meta.iloc[s]["player"]),
                in_code=int(codes[b]),
                in_player=str(meta.iloc[b]["player"]),
                price_out=int(sell_val[s]),
                price_in=int(meta.iloc[b]["price"]),
            )
        )
    return moves


def _hold_xpts(proj: pd.DataFrame, own: dict[int, int], gws, rules: SeasonRules) -> float:
    """Undiscounted XI+captain total from keeping the current 15 all horizon."""
    from engine.optimize.squad import optimize_lineup

    ident = (
        proj.sort_values("gw")
        .groupby("code")
        .agg(
            player=("player", "first"),
            team=("team", "first"),
            position=("position", "first"),
            price=("price", "first"),
        )
        .reindex(list(own))
    )
    total = 0.0
    for g in gws:
        xp_g = proj[proj["gw"] == g].set_index("code")["xpts"]
        rows = ident.reset_index()
        rows["xpts"] = rows["code"].map(xp_g).fillna(0.0)  # no fixture -> 0
        sol = optimize_lineup(rows[["code", "player", "team", "position", "price", "xpts"]], rules)
        total += sol.xpts_xi
    return float(total)


def _solver(time_limit: float | None):
    try:
        return pulp.HiGHS(msg=False, timeLimit=time_limit)
    except Exception:
        return pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit)


# -- smoke test on live data ------------------------------------------------


def _demo() -> None:
    """Plan from the current live projections: draft the optimal GW1 squad,
    then ask the planner what it would do with £0.0m bank and 1 FT."""
    from pathlib import Path

    from engine.optimize.squad import optimize_squad

    live = Path(__file__).resolve().parents[2] / "data" / "live"
    per_gw = pd.read_parquet(live / "projections_gw.parquet")
    fixture = pd.read_parquet(live / "projections_fixture.parquet")
    prices = fixture.groupby("code").agg(price=("price", "first"), p_play=("p_start", "mean"))
    proj = per_gw.merge(prices, on="code", how="left")
    proj = proj[["code", "player", "team", "position", "price", "gw", "xpts", "p_play"]]

    pool = proj.groupby("code", as_index=False).agg(
        player=("player", "first"),
        team=("team", "first"),
        position=("position", "first"),
        price=("price", "first"),
        xpts=("xpts", "sum"),
        p_play=("p_play", "mean"),
    )
    draft = optimize_squad(pool)
    own = {int(r.code): int(r.price) for r in draft.squad.itertuples()}
    bank = load_season().squad.budget - int(draft.squad["price"].sum())

    plan = optimize_transfers(proj, own, bank=bank, free_transfers=1)
    print(plan.summary())


if __name__ == "__main__":
    import sys

    if (sys.stdout.encoding or "").lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _demo()
