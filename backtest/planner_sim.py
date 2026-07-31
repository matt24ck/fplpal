"""Planner backtest: the multi-GW transfer planner replays 2025-26.

The acceptance test from TODO §2: the bot-manager simulation (myopic greedy
same-position transfers, single-GW projections) scored **2,020 points** on
the 2025-26 replay — the planner must beat it under the same rules, or it
has no business shipping. The real 13.1M-manager average was 1,895 (with
chips; neither bot plays them).

Same-terms setup, differences from the myopic bot disclosed:

- Projections are **frozen at the decision date** (``replay_season_frozen``):
  the planner sees GW g..g+h-1 exactly as the live pipeline would have
  published them before GW g. The myopic bot's single-GW projection for GW g
  is the same quantity, so week-one information is identical.
- The planner obeys the FPL sell-price rule (purchase + half the profit,
  rounded down); the myopic bot sold at full current price — a small edge
  *for the bot*.
- Both are news-blind (no historical injury flags), play no chips, and score
  with real autosubs + vice doubling on actual minutes.

Rules enforced: £100.0m start, 2/5/5/3 shape, ≤3 per club, 1 FT/GW banked to
5, −4 per extra transfer, per-GW historical buy prices.

Run:
  python -m backtest.planner_sim                # build/caches the frozen frame, then one season
  python -m backtest.planner_sim --discount 0.9 --horizon 6
  python -m backtest.planner_sim --sweep        # discount + horizon grid
  python -m backtest.planner_sim --validate     # frozen(g,g) vs the myopic replay frame
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from engine.config.season import load_season
from engine.models.points import PLAYER_GW_PATH
from engine.optimize.chips import CHIPS, _suffix_pool, _week_pool, advise_chips
from engine.optimize.squad import optimize_squad
from engine.optimize.transfers import GW_DISCOUNT, optimize_transfers

REPO_ROOT = Path(__file__).resolve().parents[1]
FROZEN_DIR = REPO_ROOT / "data" / "backtest"
BUILD_HORIZON = 8  # cache the widest window once; runs slice what they need

SEASON = "2025-26"
FORMATION_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
MAX_BANKED_FT = 5
HIT_COST = 4
BUDGET = 1000

# Play a chip early only when its expected gain clears the bar AND this is
# the best visible week for it; anything unused is force-played before its
# half expires (a >0 EV chip is never worth losing).
CHIP_THRESH = {"triple_captain": 8.0, "bboost": 10.0, "freehit": 8.0, "wildcard": 12.0}
FIRST_HALF_END = load_season().chips.first_half_deadline_gw  # 19; 2025-26 had the same split


def frozen_frame(rebuild: bool = False) -> pd.DataFrame:
    path = FROZEN_DIR / f"frozen_{SEASON}_h{BUILD_HORIZON}.parquet"
    if path.exists() and not rebuild:
        return pd.read_parquet(path)
    from engine.models.points import replay_season_frozen

    frozen = replay_season_frozen(SEASON, horizon=BUILD_HORIZON)
    FROZEN_DIR.mkdir(parents=True, exist_ok=True)
    frozen.to_parquet(path, index=False)
    print(f"cached frozen replay -> {path}")
    return frozen


def load_actuals() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(per-GW actual points/minutes, price pivot, per-code meta) for the season."""
    h = pd.read_parquet(PLAYER_GW_PATH)
    h = h[h["season"] == SEASON]
    actuals = h.groupby(["gw", "code"], as_index=False).agg(
        points=("total_points", "sum"), minutes=("minutes", "sum")
    )
    prices = (
        h.groupby(["gw", "code"], as_index=False)
        .agg(price=("price", "first"))
        .pivot(index="code", columns="gw", values="price")
        .reindex(columns=range(1, 39))
        .ffill(axis=1)
        .bfill(axis=1)
    )
    meta = h.groupby("code").agg(
        player=("player", "last"), team=("team", "last"), position=("position", "last")
    )
    return actuals, prices, meta


def sell_value(current: int, purchase: int) -> int:
    """FPL sell price in tenths: full price at a loss, half the profit kept."""
    return current if current <= purchase else purchase + (current - purchase) // 2


def autosub_score(sol_df: pd.DataFrame, cap_mult: int = 2) -> tuple[float, str]:
    """Score the XI on actual points with autosubs + the vice rule.

    ``cap_mult=3`` is triple captain (the armband, vice fallback included,
    multiplies instead of doubling).
    """
    xi = sol_df[sol_df["in_xi"]].copy()
    bench = sol_df[~sol_df["in_xi"]].sort_values("bench_order")
    counts = xi["position"].value_counts().to_dict()

    final = xi.to_dict("records")
    used = set()
    for i, starter in enumerate(list(final)):
        if starter["minutes"] > 0:
            continue
        for b in bench.itertuples():
            if b.Index in used or b.minutes == 0:
                continue
            if (starter["position"] == "GKP") != (b.position == "GKP"):
                continue
            new_counts = dict(counts)
            new_counts[starter["position"]] -= 1
            new_counts[b.position] = new_counts.get(b.position, 0) + 1
            if any(new_counts.get(p, 0) < lo for p, lo in FORMATION_MIN.items()):
                continue
            final[i] = {
                "player": b.player, "position": b.position, "points": b.points,
                "minutes": b.minutes, "is_captain": False, "is_vice": False,
            }  # fmt: skip
            counts = new_counts
            used.add(b.Index)
            break

    total = sum(p["points"] for p in final)
    cap = next((p for p in final if p.get("is_captain")), None)
    vice = next((p for p in final if p.get("is_vice")), None)
    armband = "none"
    if cap is not None and cap["minutes"] > 0:
        total += (cap_mult - 1) * cap["points"]
        armband = f"C {cap['player']} ({cap['points']:.0f})"
    elif vice is not None and vice["minutes"] > 0:
        total += (cap_mult - 1) * vice["points"]
        armband = f"V {vice['player']} ({vice['points']:.0f})"
    return total, armband


def bench_boost_score(sol_df: pd.DataFrame) -> tuple[float, str]:
    """All 15 count; the armband still doubles (vice fallback applies)."""
    total = float(sol_df["points"].sum())
    cap = sol_df[sol_df["is_captain"]]
    vice = sol_df[sol_df["is_vice"]]
    armband = "none"
    if len(cap) and cap.iloc[0]["minutes"] > 0:
        total += float(cap.iloc[0]["points"])
        armband = f"C {cap.iloc[0]['player']} ({cap.iloc[0]['points']:.0f})"
    elif len(vice) and vice.iloc[0]["minutes"] > 0:
        total += float(vice.iloc[0]["points"])
        armband = f"V {vice.iloc[0]['player']} ({vice.iloc[0]['points']:.0f})"
    return total, armband


def window_projections(
    frozen: pd.DataFrame,
    g: int,
    horizon: int,
    owned: dict[int, int],
    prices: pd.DataFrame,
    meta: pd.DataFrame,
) -> pd.DataFrame:
    """The planner's view at decision GW g: frozen rows, owned codes guaranteed."""
    w = frozen[(frozen["decision_gw"] == g) & (frozen["gw"] < g + horizon)].copy()
    missing = set(owned) - set(w["code"])
    if missing:  # a whole-window blank (rare): zero rows keep the MILP fed
        rows = []
        for c in missing:
            rows.append(
                {
                    "code": c,
                    "player": meta.at[c, "player"],
                    "team": meta.at[c, "team"],
                    "position": meta.at[c, "position"],
                    "price": int(prices.at[c, g]),
                    "gw": g,
                    "xpts": 0.0,
                    "p_play": 0.0,
                    "decision_gw": g,
                    "n_fixtures": 0,
                }
            )
        w = pd.concat([w, pd.DataFrame(rows)], ignore_index=True)
    return w


def run_season(
    frozen: pd.DataFrame,
    horizon: int,
    discount: float,
    verbose: bool = True,
    time_limit: float = 30.0,
    chips: bool = False,
) -> dict:
    actuals, prices, meta = load_actuals()
    act = actuals.set_index(["gw", "code"])

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    # GW1 draft on the frozen decision-1 window (discounted horizon sum).
    w1 = window_projections(frozen, 1, horizon, {}, prices, meta)
    w1["_dx"] = w1["xpts"] * discount ** (w1["gw"] - 1)
    pool = w1.groupby("code", as_index=False).agg(
        player=("player", "first"),
        team=("team", "first"),
        position=("position", "first"),
        price=("price", "first"),
        xpts=("_dx", "sum"),
        p_play=("p_play", "mean"),
    )
    draft = optimize_squad(pool, budget=BUDGET)
    purchase = {int(r.code): int(r.price) for r in draft.squad.itertuples()}
    bank = BUDGET - int(draft.squad["price"].sum())
    ft_avail = 0
    total, n_hits, n_moves = 0.0, 0, 0

    def merge_actuals(squad_df: pd.DataFrame, g: int) -> pd.DataFrame:
        codes = squad_df["code"]
        return squad_df.merge(
            pd.DataFrame(
                {
                    "code": codes,
                    "points": [act["points"].get((g, int(c)), 0.0) for c in codes],
                    "minutes": [act["minutes"].get((g, int(c)), 0.0) for c in codes],
                }
            ),
            on="code",
            how="left",
        )

    def owned_lineup(g: int, owned: dict[int, int]):
        """This GW's frozen rows for the owned 15 (zero rows for blanks) -> lineup."""
        gw_rows = frozen[(frozen["decision_gw"] == g) & (frozen["gw"] == g)]
        rows = gw_rows[gw_rows["code"].isin(owned)][
            ["code", "player", "team", "position", "price", "xpts", "p_play"]
        ].copy()
        missing = set(owned) - set(rows["code"])
        if missing:
            rows = pd.concat(
                [
                    rows,
                    pd.DataFrame(
                        {
                            "code": list(missing),
                            "player": [meta.at[c, "player"] for c in missing],
                            "team": [meta.at[c, "team"] for c in missing],
                            "position": [meta.at[c, "position"] for c in missing],
                            "price": [int(prices.at[c, g]) for c in missing],
                            "xpts": 0.0,
                            "p_play": 0.0,
                        }
                    ),
                ],
                ignore_index=True,
            )
        return optimize_squad(rows, fix_squad=True, budget=100_000)

    chip_unused = {1: set(CHIPS), 2: set(CHIPS)} if chips else {1: set(), 2: set()}
    chip_log: list[dict] = []

    for g in range(1, 39):
        half = 1 if g <= FIRST_HALF_END else 2
        half_end = FIRST_HALF_END if half == 1 else 38
        chip_played: str | None = None
        w = squad_sv = None

        if g > 1:
            ft_avail = min(ft_avail + 1, MAX_BANKED_FT)
            w = window_projections(frozen, g, horizon, purchase, prices, meta)
            squad_sv = {c: sell_value(int(prices.at[c, g]), p) for c, p in purchase.items()}
            plan = optimize_transfers(
                w,
                squad_sv,
                bank=bank,
                free_transfers=ft_avail,
                discount=discount,
                time_limit=time_limit,
            )

            # Chip decision: play early only on a cleared threshold at the
            # best visible week (within this half); force-play before expiry.
            avail = chip_unused[half]
            if avail:
                advice = advise_chips(
                    w, squad_sv, bank=bank, free_transfers=ft_avail, discount=discount,
                    chips=tuple(sorted(avail)), plan=plan, time_limit=time_limit,
                )  # fmt: skip
                force = len(avail) >= half_end - g + 1
                pick_ev = -1.0
                for chip, adv in advice.items():
                    weeks = [wk for wk in adv.weeks if wk.gw <= half_end]
                    if not weeks or weeks[0].gw != g:
                        continue
                    now = weeks[0]
                    best = max(weeks, key=lambda x: x.ev)
                    if (
                        force or (now.ev >= CHIP_THRESH[chip] and best.gw == g)
                    ) and now.ev > pick_ev:
                        chip_played, pick_ev = chip, now.ev
                if chip_played:
                    chip_unused[half].discard(chip_played)
                    log(f"  GW{g} CHIP: {chip_played} (expected +{pick_ev:.1f})")

            if chip_played == "wildcard":
                # Rebuild from scratch at full current value; FTs preserved.
                budget_now = bank + sum(squad_sv.values())
                pool = _suffix_pool(w, sorted(w["gw"].unique()), discount)
                scratch = optimize_squad(pool, budget=budget_now)
                new_codes = [int(c) for c in scratch.squad["code"]]
                turnover = len(set(new_codes) - set(purchase))
                purchase = {c: int(prices.at[c, g]) for c in new_codes}
                bank = budget_now - int(scratch.squad["price"].sum())
                chip_log.append(
                    {"gw": g, "chip": "wildcard", "gain": None, "note": f"{turnover} new players"}
                )
                log(f"  GW{g} wildcard: {turnover} new players, bank £{bank / 10:.1f}m")
            elif chip_played != "freehit":  # freehit skips transfers entirely
                moves = plan.steps[0].moves
                hits = max(0, len(moves) - ft_avail)
                for m in moves:
                    bank += squad_sv[m.out_code] - int(prices.at[m.in_code, g])
                    del purchase[m.out_code]
                    purchase[m.in_code] = int(prices.at[m.in_code, g])
                    log(f"  GW{g} transfer: {m.out_player} -> {m.in_player}")
                if hits:
                    log(f"  GW{g}: {len(moves)} moves on {ft_avail} FTs -> -{HIT_COST * hits} hit")
                n_moves += len(moves)
                n_hits += hits
                total -= hits * HIT_COST
                # consume this week's transfers; next week's +1 lands at loop top
                ft_avail = max(ft_avail - len(moves), 0)

        # Score the week.
        if chip_played == "freehit":
            budget_now = bank + sum(squad_sv.values())
            fh_sol = optimize_squad(_week_pool(w, g), budget=budget_now)
            merged = merge_actuals(fh_sol.squad, g)
            pts, armband = autosub_score(merged)
            held_pts, _ = autosub_score(merge_actuals(owned_lineup(g, purchase).squad, g))
            chip_log.append({"gw": g, "chip": "freehit", "gain": pts - held_pts, "note": ""})
        else:
            merged = merge_actuals(owned_lineup(g, purchase).squad, g)
            if chip_played == "triple_captain":
                pts, armband = autosub_score(merged, cap_mult=3)
                base, _ = autosub_score(merged)
                chip_log.append(
                    {"gw": g, "chip": "triple_captain", "gain": pts - base, "note": armband}
                )
            elif chip_played == "bboost":
                pts, armband = bench_boost_score(merged)
                base, _ = autosub_score(merged)
                chip_log.append({"gw": g, "chip": "bboost", "gain": pts - base, "note": ""})
            else:
                pts, armband = autosub_score(merged)
        total += pts
        tag = f" | {chip_played.upper()}" if chip_played else ""
        log(
            f"GW{g}: {pts:.0f} pts | season {total:.0f} | {armband} | "
            f"bank £{bank / 10:.1f}m | FTs {ft_avail}{tag}"
        )

    return {"total": total, "hits": n_hits, "moves": n_moves, "horizon": horizon,
            "discount": discount, "chips": chip_log}  # fmt: skip


def validate(frozen: pd.DataFrame) -> None:
    """frozen(g, g) should match the myopic replay's per-GW projections."""
    myopic_path = REPO_ROOT / "test" / "pergw_actuals.parquet"
    if not myopic_path.exists():
        print("no test/pergw_actuals.parquet (gitignored scratch) — skipping")
        return
    myopic = pd.read_parquet(myopic_path)
    week1 = frozen[frozen["decision_gw"] == frozen["gw"]]
    m = week1.merge(myopic, on=["gw", "code"], suffixes=("_frozen", "_myopic"))
    diff = (m["xpts_frozen"] - m["xpts_myopic"]).abs()
    corr = m["xpts_frozen"].corr(m["xpts_myopic"])
    print(
        f"decision-week rows vs myopic replay: n={len(m):,} | "
        f"mean |Δxpts| {diff.mean():.4f} | max {diff.max():.3f} | corr {corr:.5f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the multi-GW transfer planner.")
    parser.add_argument("--horizon", type=int, default=6)
    parser.add_argument("--discount", type=float, default=GW_DISCOUNT)
    parser.add_argument("--rebuild", action="store_true", help="rebuild the frozen frame")
    parser.add_argument("--sweep", action="store_true", help="run a discount/horizon grid")
    parser.add_argument("--chips", action="store_true", help="play chips via the advisor")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    frozen = frozen_frame(rebuild=args.rebuild)
    if args.validate:
        validate(frozen)
        return

    if args.sweep:
        results = []
        grid = [(6, d) for d in (1.0, 0.9, 0.85, 0.8)] + [(4, 0.85), (8, 0.85)]
        for horizon, discount in grid:
            r = run_season(frozen, horizon, discount, verbose=False)
            results.append(r)
            print(
                f"h={horizon} γ={discount}: {r['total']:.0f} pts "
                f"({r['moves']} moves, {r['hits']} hits)"
            )
        best = max(results, key=lambda r: r["total"])
        print(f"\nbest: h={best['horizon']} γ={best['discount']} -> {best['total']:.0f}")
    else:
        r = run_season(
            frozen, args.horizon, args.discount, verbose=not args.quiet, chips=args.chips
        )
        print(
            f"\n== SEASON TOTAL: {r['total']:.0f} pts | transfers {r['moves']} | "
            f"hits {r['hits']} (-{r['hits'] * HIT_COST}) =="
        )
        for c in r["chips"]:
            gain = "n/a (squad rebuild)" if c["gain"] is None else f"{c['gain']:+.0f} pts"
            note = f" {c['note']}" if c["note"] else ""
            print(f"  {c['chip']} @ GW{c['gw']}: {gain}{note}")
        print("acceptance: beat the myopic bot's 2,020 (real manager average 1,895, with chips)")


if __name__ == "__main__":
    if (sys.stdout.encoding or "").lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
