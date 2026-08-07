"""The engine's typed tool surface (PLAN.md §6, GW1 scope).

Every function returns a JSON-safe dict computed entirely by the engine —
the chat layer narrates these payloads and must never invent numbers beyond
them. Each payload carries ``provenance`` (snapshot + computation timestamps)
for the "computed from data through X" badge. The same functions back the
REST endpoints, so UI tables and chat answers can never disagree.

The full optimizer surface is live: ``plan_transfers`` solves the
multi-period transfer MILP and ``chip_advice`` prices every chip week in
the projection window on top of the plan's trajectory (pre-season both run
as previews on the user's draft, honestly labeled).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from api.data import LiveStore, get_store
from engine.config.season import load_season
from engine.ingest.team_state import fetch_team_state
from engine.models.event_rates import data_basis
from engine.models.points import COMPONENTS
from engine.models.ratings import SUBSCORES
from engine.optimize.chips import CHIPS, advise_chips
from engine.optimize.squad import optimize_lineup, optimize_squad
from engine.optimize.transfers import optimize_transfers

COMPONENT_LABELS = {
    "pts_appearance": "appearance",
    "pts_goals": "goals",
    "pts_assists": "assists",
    "pts_cs": "clean_sheets",
    "pts_gc": "goals_conceded",
    "pts_saves": "saves",
    "pts_dc": "defensive_contribution",
    "pts_bonus": "bonus",
    "pts_cards": "cards",
    "pts_other": "other",
}


def _r(x, nd: int = 2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def _resolve(store: LiveStore, query: str) -> tuple[pd.Series | None, dict | None]:
    matches = store.find_players(query)
    if len(matches) == 0:
        return None, {
            "error": f"no player matching '{query}' in the {store.provenance['season']} pool",
            "hint": "the engine only knows players registered in FPL this season",
        }
    if len(matches) > 1:
        exact_team = matches[matches["player"].str.casefold() == query.strip().casefold()]
        if len(exact_team) == 1:
            return exact_team.iloc[0], None
        return None, {
            "ambiguous": f"multiple players match '{query}'",
            "candidates": [
                f"{m.player} ({m.team}, {m.position}, £{m.price / 10:.1f}m)"
                for m in matches.itertuples()
            ],
        }
    return matches.iloc[0], None


def _player_summary(store: LiveStore, row: pd.Series) -> dict:
    code = int(row["code"])
    rating = store.player_rating(code)
    out = {
        "player": row["player"],
        "team": row["team"],
        "position": row["position"],
        "price": f"£{row['price'] / 10:.1f}m",
        "xpts_next_gws": _r(row["xpts"]),
        "p_start_avg": _r(row["p_play"]),
        # how much of the projection is observed PL data vs the position ×
        # price-tier prior — surface it when it's prior-heavy (new signings)
        "data_basis": data_basis(row.get("exposure_90")),
    }
    if rating is not None:
        out["rating"] = _r(rating["rating"], 0)
        out["sub_scores"] = {
            name: _r(rating[f"score_{name}"], 0) for name in SUBSCORES.get(str(row["position"]), [])
        }
    return out


# -- tool implementations --------------------------------------------------


def get_player(query: str) -> dict:
    """Player profile: price, projected points, rating with sub-scores, fixtures."""
    store = get_store()
    row, err = _resolve(store, query)
    if err:
        return err
    fx = store.player_fixtures(int(row["code"]))
    out = _player_summary(store, row)
    out["fixtures"] = [
        {
            "gw": int(f.gw),
            "opponent": f.opponent,
            "home": bool(f.was_home),
            "xpts": _r(f.xpts),
        }
        for f in fx.itertuples()
    ]
    out["provenance"] = store.provenance
    return out


def project_points(players: list[str]) -> dict:
    """Per-GW expected points with the full component decomposition per player."""
    store = get_store()
    results, errors = [], []
    for q in players:
        row, err = _resolve(store, q)
        if err:
            errors.append(err)
            continue
        fx = store.player_fixtures(int(row["code"]))
        results.append(
            {
                "player": row["player"],
                "team": row["team"],
                "position": row["position"],
                "total_xpts": _r(fx["xpts"].sum()),
                "per_gw": [
                    {
                        "gw": int(f.gw),
                        "opponent": f.opponent,
                        "home": bool(f.was_home),
                        "xpts": _r(f.xpts),
                        "ceiling": _r(f.xpts + 1.65 * np.sqrt(f.var_pts)),
                        "breakdown": {
                            COMPONENT_LABELS[c]: _r(getattr(f, c))
                            for c in COMPONENTS
                            if abs(getattr(f, c)) >= 0.005
                        },
                    }
                    for f in fx.itertuples()
                ],
            }
        )
    return {"projections": results, "errors": errors, "provenance": store.provenance}


def compare_players(players: list[str]) -> dict:
    """Side-by-side summaries (price, xPts, rating, sub-scores) for 2+ players."""
    store = get_store()
    results, errors = [], []
    for q in players:
        row, err = _resolve(store, q)
        if err:
            errors.append(err)
        else:
            results.append(_player_summary(store, row))
    return {"comparison": results, "errors": errors, "provenance": store.provenance}


def rank_players(
    position: str | None = None,
    max_price: float | None = None,
    team: str | None = None,
    sort_by: str = "xpts",
    limit: int = 10,
) -> dict:
    """Top players by projected points, rating, or value, with optional filters."""
    store = get_store()
    pool = store.players.merge(store.ratings[["code", "rating"]], on="code", how="left")
    if position:
        pos = position.strip().upper()[:3]
        pos = {"GK": "GKP", "GOA": "GKP"}.get(pos, pos)
        if pos not in ("GKP", "DEF", "MID", "FWD"):
            return {"error": f"unknown position '{position}' (use GKP/DEF/MID/FWD)"}
        pool = pool[pool["position"] == pos]
    if max_price is not None:
        pool = pool[pool["price"] <= float(max_price) * 10]
    if team:
        t = store.find_team(team)
        if t is None:
            return {"error": f"unknown team '{team}'", "teams": store.teams}
        pool = pool[pool["team"] == t]

    pool = pool.assign(value=pool["xpts"] / (pool["price"] / 10.0))
    key = {"xpts": "xpts", "rating": "rating", "value": "value"}.get(sort_by, "xpts")
    top = pool.nlargest(int(limit), key)

    def _rank_row(r) -> dict:
        d = {
            "player": r.player,
            "team": r.team,
            "position": r.position,
            "price": f"£{r.price / 10:.1f}m",
            "xpts_next_gws": _r(r.xpts),
            "rating": _r(r.rating, 0),
            "xpts_per_million": _r(r.value),
        }
        # compact flag only when the projection is prior-heavy — keeps the
        # ranking payload lean but stops a pure-prior new signing passing as
        # an observed-data pick
        basis = data_basis(r.exposure_90)
        if basis["level"] in ("pure_prior", "mostly_prior"):
            d["data_basis"] = basis["level"]
        return d

    return {
        "ranked_by": key,
        "players": [_rank_row(r) for r in top.itertuples()],
        "provenance": store.provenance,
    }


def get_fixtures(team: str) -> dict:
    """A team's upcoming fixtures with model-based difficulty (expected goals for/against)."""
    store = get_store()
    t = store.find_team(team)
    if t is None:
        return {"error": f"unknown team '{team}'", "teams": store.teams}
    fx = store.proj[store.proj["team"] == t].drop_duplicates("fixture").sort_values("gw")
    return {
        "team": t,
        "fixtures": [
            {
                "gw": int(f.gw),
                "opponent": f.opponent,
                "home": bool(f.was_home),
                "expected_goals_for": _r(f.lam_for),
                "expected_goals_against": _r(f.lam_against),
                "clean_sheet_probability": _r(f.p_cs),
            }
            for f in fx.itertuples()
        ],
        "provenance": store.provenance,
    }


def explain_rating(query: str) -> dict:
    """Why a player is rated what he's rated: sub-scores and what drives them."""
    store = get_store()
    row, err = _resolve(store, query)
    if err:
        return err
    rating = store.player_rating(int(row["code"]))
    if rating is None:
        return {"error": f"no rating computed for {row['player']}"}
    pos = str(row["position"])
    subs = {name: _r(rating[f"score_{name}"], 0) for name in SUBSCORES.get(pos, [])}
    return {
        "player": row["player"],
        "position": pos,
        "rating": _r(rating["rating"], 0),
        "sub_scores": subs,
        "data_basis": data_basis(row.get("exposure_90")),
        "note": (
            "sub-scores are percentiles (0-100) within position over the projection "
            "window; the headline rating is a weighted blend with weights fitted "
            "against realized points in backtests"
        ),
        "strongest": max(subs, key=lambda k: subs[k] or 0),
        "weakest": min(subs, key=lambda k: subs[k] or 100),
        "provenance": store.provenance,
    }


def build_squad(
    budget: float = 100.0,
    locked: list[str] | None = None,
    excluded: list[str] | None = None,
) -> dict:
    """Solve the optimal 15-man squad (MILP): XI, formation, captain, bench."""
    store = get_store()
    locked_names, excluded_names, errors = [], [], []
    for q in locked or []:
        row, err = _resolve(store, q)
        (errors.append(err) if err else locked_names.append(row["player"]))
    for q in excluded or []:
        row, err = _resolve(store, q)
        (errors.append(err) if err else excluded_names.append(row["player"]))
    if errors:
        return {"errors": errors}

    sol = optimize_squad(
        store.players,
        budget=int(budget * 10),
        locked=tuple(locked_names),
        excluded=tuple(excluded_names),
    )
    return _solution_payload(store, sol)


def rate_my_draft(players: list[str]) -> dict:
    """Rate a 15-man draft: best XI/captain from it, and the gap to the optimal squad."""
    store = get_store()
    rows, errors = [], []
    for q in players:
        row, err = _resolve(store, q)
        (errors.append(err) if err else rows.append(row))
    if errors:
        return {"errors": errors}
    if len(rows) != 15:
        return {"error": f"a draft needs exactly 15 players, got {len(rows)}"}

    squad_df = pd.DataFrame(rows)
    counts = squad_df["position"].value_counts().to_dict()
    if counts != {"DEF": 5, "MID": 5, "GKP": 2, "FWD": 3}:
        return {"error": f"invalid squad shape {counts}, need 2 GKP / 5 DEF / 5 MID / 3 FWD"}

    sol = optimize_lineup(squad_df)
    optimal = optimize_squad(store.players, budget=int(squad_df["price"].sum()))
    out = _solution_payload(store, sol)
    out["draft_cost"] = f"£{squad_df['price'].sum() / 10:.1f}m"
    out["optimal_squad_same_budget_xpts"] = _r(optimal.xpts_xi, 1)
    out["gap_to_optimal"] = _r(optimal.xpts_xi - sol.xpts_xi, 1)
    return out


def _solution_payload(store: LiveStore, sol) -> dict:
    sq = sol.squad
    xi = sq[sq["in_xi"]]
    bench = sq[~sq["in_xi"]].sort_values("bench_order")

    def fmt(r) -> dict:
        d = {
            "player": r.player,
            "team": r.team,
            "position": r.position,
            "price": f"£{r.price / 10:.1f}m",
            "xpts": _r(r.xpts, 1),
        }
        if hasattr(r, "xpts_next"):
            d["xpts_this_gw"] = _r(r.xpts_next, 1)
        if r.is_captain:
            d["captain"] = True
        if r.is_vice:
            d["vice_captain"] = True
        return d

    out = {
        "formation": sol.formation,
        "cost": f"£{sol.cost / 10:.1f}m",
        "xi_plus_captain_xpts": _r(sol.xpts_xi, 1),
        "starting_xi": [fmt(r) for r in xi.itertuples()],
        "bench_in_order": [fmt(r) for r in bench.itertuples()],
        "provenance": store.provenance,
    }
    if sol.xpts_xi_next is not None:
        out["xi_plus_captain_xpts_this_gw"] = _r(sol.xpts_xi_next, 1)
        out["horizons"] = (
            "the 15 and the captain are picked over the whole projection window "
            "(xpts); the starting XI and bench order are picked for the upcoming "
            "gameweek alone (xpts_this_gw)"
        )
    return out


def _resolve_squad(store: LiveStore, players: list[str]) -> tuple[pd.DataFrame | None, dict | None]:
    """Resolve 15 names to rows; error payload if names or shape are off."""
    rows, errors = [], []
    for q in players:
        row, err = _resolve(store, q)
        (errors.append(err) if err else rows.append(row))
    if errors:
        return None, {"errors": errors}
    if len(rows) != 15:
        return None, {"error": f"a squad needs exactly 15 players, got {len(rows)}"}
    squad_df = pd.DataFrame(rows)
    counts = squad_df["position"].value_counts().to_dict()
    if counts != {"DEF": 5, "MID": 5, "GKP": 2, "FWD": 3}:
        return None, {"error": f"invalid squad shape {counts}, need 2 GKP / 5 DEF / 5 MID / 3 FWD"}
    return squad_df, None


def _fmt_m(tenths: float | None) -> str | None:
    return None if tenths is None else f"£{tenths / 10:.1f}m"


def import_team(team_id: int) -> dict:
    """A manager's live FPL state from their public team ID: squad with
    purchase/sell prices, bank, free transfers, chips. Pre-deadline this is
    an honest ``pending`` payload."""
    store = get_store()
    rules = load_season(store.provenance["season"])
    state = fetch_team_state(int(team_id), rules.chips.first_half_deadline_gw)
    if "error" in state or state.get("status") == "pending":
        return state
    return {
        **{k: v for k, v in state.items() if k not in ("squad", "bank", "team_value")},
        "squad": [
            {
                "player": p["player"],
                "position": p["position"],
                "team": p["team"],
                "price": _fmt_m(p["current_price"]),
                "selling_price": _fmt_m(p["selling_price"]),
                **({"captain": True} if p["is_captain"] else {}),
                **({"vice_captain": True} if p["is_vice_captain"] else {}),
                **({"benched": True} if (p["squad_position"] or 0) > 11 else {}),
            }
            for p in state["squad"]
        ],
        "bank": _fmt_m(state["bank"]),
        "team_value": _fmt_m(state["team_value"]),
        "source": "live FPL API (public entry endpoints), not engine projections",
    }


def _team_inputs(store: LiveStore, team_id: int) -> tuple[dict | None, dict | None]:
    """Resolve an imported team to planner inputs: squad rows keyed by the
    stable player code, sell values, bank, and free transfers."""
    rules = load_season(store.provenance["season"])
    state = fetch_team_state(int(team_id), rules.chips.first_half_deadline_gw)
    if "error" in state:
        return None, {"error": state["error"]}
    if state.get("status") == "pending":
        return None, {"error": state["note"], "status": "pending"}
    if state.get("warnings"):
        return None, {"error": f"imported squad can't be planned: {'; '.join(state['warnings'])}"}
    codes = [int(p["code"]) for p in state["squad"]]
    pool = store.players[store.players["code"].isin(codes)]
    if len(pool) != 15:
        missing = set(codes) - {int(c) for c in pool["code"]}
        names = [p["player"] for p in state["squad"] if p["code"] in missing]
        return None, {"error": f"imported players not in the engine's pool: {names}"}
    return {
        "state": state,
        "squad_df": pool,
        "own": {int(p["code"]): int(p["selling_price"]) for p in state["squad"]},
        "bank": state["bank"] / 10.0,
        "free_transfers": int(state["free_transfers"]),
    }, None


def _import_note(state: dict) -> str:
    return (
        f"planned from imported FPL team {state['team_id']} (“{state['team_name']}”): "
        f"bank £{state['bank'] / 10:.1f}m, {state['free_transfers']} free transfer(s), "
        "real sell prices from purchase history"
    )


def _gw_projections(store: LiveStore, horizon: int | None = None) -> pd.DataFrame:
    proj = store.per_gw.merge(store.players[["code", "price", "p_play"]], on="code", how="left")
    proj = proj[["code", "player", "team", "position", "price", "gw", "xpts", "p_play"]]
    if horizon:
        keep = sorted(proj["gw"].unique())[:horizon]
        proj = proj[proj["gw"].isin(keep)]
    return proj


def plan_transfers(
    players: list[str] | None = None,
    bank: float = 0.0,
    free_transfers: int = 1,
    horizon: int | None = None,
    alternatives: int = 1,
    team_id: int | None = None,
) -> dict:
    """Multi-GW transfer plan (MILP): which moves, when, hits vs. banking FTs.

    Either ``team_id`` (imported live state: real squad, bank, FTs, and sell
    prices from purchase history) or ``players`` (the current 15 by name;
    ``bank`` in £m; sell prices assumed = current prices).
    """
    store = get_store()
    import_note = None
    if team_id is not None:
        inputs, err = _team_inputs(store, team_id)
        if err:
            return err
        own, bank, free_transfers = inputs["own"], inputs["bank"], inputs["free_transfers"]
        import_note = _import_note(inputs["state"])
    else:
        if not players:
            return {"error": "provide either the 15 players or a team_id to import"}
        squad_df, err = _resolve_squad(store, players)
        if err:
            return err
        own = {int(r.code): int(r.price) for r in squad_df.itertuples()}

    proj = _gw_projections(store, horizon)

    plan = optimize_transfers(
        proj, own, bank=round(bank * 10), free_transfers=free_transfers, time_limit=10.0
    )
    out = _plan_payload(plan)

    alts = []
    week1_moved = bool(plan.steps[0].moves)
    variants: list[tuple[str, dict]] = []
    if alternatives >= 1:
        if week1_moved:
            variants.append(("hold this week instead", {"hold_first": True}))
            if alternatives >= 2:
                variants.append(
                    (
                        "a different move this week",
                        {
                            "forbid_first_gw": [
                                (
                                    frozenset(m.in_code for m in plan.steps[0].moves),
                                    frozenset(m.out_code for m in plan.steps[0].moves),
                                )
                            ]
                        },
                    )
                )
        else:
            variants.append(("best move now instead of banking", {"force_move": True}))
    for label, kwargs in variants:
        try:
            alt = optimize_transfers(
                proj, own, bank=round(bank * 10), free_transfers=free_transfers,
                time_limit=8.0, **kwargs,
            )  # fmt: skip
        except RuntimeError:
            continue
        alts.append(
            {
                "label": label,
                "this_week": _moves_payload(alt.steps[0]),
                "expected_pts_over_horizon": _r(alt.xpts_total, 1),
                "delta_vs_plan": _r(alt.xpts_total - plan.xpts_total, 1),
            }
        )
    if alts:
        out["alternatives"] = alts

    notes = []
    if import_note:
        notes.append(import_note)
    if store.provenance["gw_window"][0] == 1:
        notes.append(
            "pre-season: transfers are unlimited until the GW1 deadline, so this is "
            "a preview that treats the draft as locked from GW1"
        )
    if notes:
        out["note"] = "; ".join(notes)
    out["provenance"] = store.provenance
    return out


def _moves_payload(step) -> dict:
    if not step.moves:
        return {"action": "hold", "moves": []}
    return {
        "action": "transfer",
        "moves": [
            {
                "out": m.out_player,
                "out_sell_price": f"£{m.price_out / 10:.1f}m",
                "in": m.in_player,
                "in_price": f"£{m.price_in / 10:.1f}m",
            }
            for m in step.moves
        ],
        "hit_cost": -4 * step.hits if step.hits else 0,
    }


def _plan_payload(plan) -> dict:
    steps = []
    for s in plan.steps:
        steps.append(
            {
                "gw": s.gw,
                **_moves_payload(s),
                "free_transfers_after": s.ft_after,
                "bank_after": f"£{s.bank_after / 10:.1f}m",
                "xi_xpts": _r(s.xpts_xi, 1),
            }
        )
    return {
        "horizon_gws": [plan.steps[0].gw, plan.steps[-1].gw],
        "expected_pts_with_plan": _r(plan.xpts_total, 1),
        "expected_pts_holding": _r(plan.baseline_xpts, 1),
        "expected_gain": _r(plan.gain, 1),
        "this_week": _moves_payload(plan.steps[0]),
        "steps": steps,
    }


CHIP_LABELS = {
    "wildcard": "Wildcard",
    "freehit": "Free Hit",
    "bboost": "Bench Boost",
    "triple_captain": "Triple Captain",
}


def chip_advice(
    players: list[str] | None = None,
    bank: float = 0.0,
    free_transfers: int = 1,
    chips: list[str] | None = None,
    team_id: int | None = None,
) -> dict:
    """Per-chip expected value across the projection window, on top of the
    transfer plan's trajectory. ``team_id`` imports the live squad/bank/FTs
    and restricts to the chips actually still in hand; otherwise ``players``
    names the 15 and ``chips`` limits the set (default: all four)."""
    store = get_store()
    import_note = None
    if team_id is not None:
        inputs, err = _team_inputs(store, team_id)
        if err:
            return err
        own, bank, free_transfers = inputs["own"], inputs["bank"], inputs["free_transfers"]
        if not chips:
            chips = inputs["state"]["chips_available"]
        import_note = _import_note(inputs["state"])
        if not chips:
            return {
                "error": "no chips left to play this half-season",
                "chips_played": inputs["state"]["chips_played"],
            }
    else:
        if not players:
            return {"error": "provide either the 15 players or a team_id to import"}
        squad_df, err = _resolve_squad(store, players)
        if err:
            return err
        own = {int(r.code): int(r.price) for r in squad_df.itertuples()}
    wanted = tuple(chips) if chips else CHIPS
    unknown = [c for c in wanted if c not in CHIPS]
    if unknown:
        return {"error": f"unknown chips {unknown}; valid: {list(CHIPS)}"}

    proj = _gw_projections(store)
    advice = advise_chips(
        proj, own, bank=round(bank * 10), free_transfers=free_transfers,
        chips=wanted, time_limit=8.0,
    )  # fmt: skip

    gws = sorted(proj["gw"].unique())
    out: dict = {"horizon_gws": [int(gws[0]), int(gws[-1])], "chips": {}}
    for chip, adv in advice.items():
        best = adv.best
        out["chips"][chip] = {
            "label": CHIP_LABELS[chip],
            "best_gw": best.gw if best else None,
            "expected_gain": _r(best.ev, 1) if best else None,
            "detail": best.detail if best else None,
            "assessment": _chip_assessment(chip, best.ev if best else 0.0),
            "weeks": [{"gw": w.gw, "ev": _r(w.ev, 1)} for w in adv.weeks],
        }
    out["note"] = (
        "expected gains cover only the visible projection window "
        f"(GW{gws[0]}-{gws[-1]}); stronger chip weeks (blanks/doubles) may exist "
        "beyond it, so a low number means 'no standout week visible', not 'never play it'"
    )
    if import_note:
        out["note"] = f"{import_note}; {out['note']}"
    if store.provenance["gw_window"][0] == 1:
        out["note"] += "; chips cannot be played before GW1"
    out["provenance"] = store.provenance
    return out


def _chip_assessment(chip: str, ev: float) -> str:
    """Engine-side verdict bands so the chat layer never freelances one."""
    strong = {"triple_captain": 8.0, "bboost": 10.0, "freehit": 8.0, "wildcard": 12.0}
    if ev >= strong[chip]:
        return "strong week visible — worth considering now"
    if ev >= 0.6 * strong[chip]:
        return "moderate value — holding is defensible"
    return "no standout week in the visible window — hold"
