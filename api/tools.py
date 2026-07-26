"""The engine's typed tool surface (PLAN.md §6, GW1 scope).

Every function returns a JSON-safe dict computed entirely by the engine —
the chat layer narrates these payloads and must never invent numbers beyond
them. Each payload carries ``provenance`` (snapshot + computation timestamps)
for the "computed from data through X" badge. The same functions back the
REST endpoints, so UI tables and chat answers can never disagree.

Transfer planning and chip advice are in-season tools (PLAN §5) and appear
here only as honest not-yet-available stubs the model can cite.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from api.data import LiveStore, get_store
from engine.models.points import COMPONENTS
from engine.models.ratings import SUBSCORES
from engine.optimize.squad import optimize_lineup, optimize_squad

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
    return {
        "ranked_by": key,
        "players": [
            {
                "player": r.player,
                "team": r.team,
                "position": r.position,
                "price": f"£{r.price / 10:.1f}m",
                "xpts_next_gws": _r(r.xpts),
                "rating": _r(r.rating, 0),
                "xpts_per_million": _r(r.value),
            }
            for r in top.itertuples()
        ],
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
        if r.is_captain:
            d["captain"] = True
        if r.is_vice:
            d["vice_captain"] = True
        return d

    return {
        "formation": sol.formation,
        "cost": f"£{sol.cost / 10:.1f}m",
        "xi_plus_captain_xpts": _r(sol.xpts_xi, 1),
        "starting_xi": [fmt(r) for r in xi.itertuples()],
        "bench_in_order": [fmt(r) for r in bench.itertuples()],
        "provenance": store.provenance,
    }


def transfer_advice() -> dict:
    """Multi-GW transfer planning — not available until the season starts."""
    return {
        "not_available": (
            "the transfer planner ships in-season (transfers are unlimited before "
            "GW1, so it has nothing to optimize yet); before the season, use "
            "build_squad or rate_my_draft instead"
        )
    }


def chip_advice() -> dict:
    """Chip timing advice — not available until the season starts."""
    return {
        "not_available": (
            "the chip advisor ships in-season (~GW4, ahead of the first realistic "
            "chip windows); chips cannot be played before GW1"
        )
    }
