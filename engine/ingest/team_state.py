"""Real team import: a manager's live FPL state from the public entry endpoints.

TODO §2's "real team import" — the bridge from a team ID to the exact inputs
the transfer planner and chip advisor need: the current 15, bank, free
transfers, *sell* prices, and which chips are still in hand. Everything comes
from public endpoints (``entry``, ``entry/history``, ``entry/{gw}/picks``,
``entry/transfers``), which FPL only populates once the manager's first
gameweek deadline has passed — before that this module returns an honest
``status: "pending"`` payload instead of guessing.

Two reconstructions the public API doesn't hand over directly:

- **Free transfers** — walked forward from the manager's first GW with the
  banking rule ``f' = min(5, max(f - n, 0) + 1)``; wildcard/free-hit weeks
  consume nothing (and still accrue the +1), matching the post-2024 rules.
- **Purchase prices** (the sell-price rule needs them; only the
  authenticated my-team endpoint exposes them) — season-start prices come
  from bootstrap (``now_cost - cost_change_start``), later buys from the
  transfer history's exact ``element_in_cost``. Free-hit transfers revert
  after their GW, so any transfer made for a free-hit week is skipped.
  Managers who joined after GW1 bought their first squad at unknowable
  historical prices — those fall back to current price with an explicit
  ``approx_purchase_prices`` flag rather than a silent wrong number.

Sell price = purchase + half the profit rounded down (or current price when
at or below purchase) — the same rule the planner MILP models.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from engine.ingest.fpl_api import FplApi
from engine.ingest.snapshot import latest_snapshot

POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
# entry/history chip names -> the season-config names used everywhere else
CHIP_NAMES = {"wildcard": "wildcard", "freehit": "freehit", "bboost": "bboost",
              "3xc": "triple_captain"}  # fmt: skip
MAX_BANKED_FT = 5

PENDING_NOTE = (
    "FPL makes picks public only after the team's first gameweek deadline — "
    "squad import opens then; until that, the site works from your draft"
)


def sell_price(purchase: int, current: int) -> int:
    """FPL sell value in tenths: full price at/below purchase, else purchase
    plus half the profit rounded down (to whole £0.1m)."""
    if current <= purchase:
        return current
    return purchase + (current - purchase) // 2


def reconstruct_free_transfers(history_current: list[dict], chips_by_event: dict[int, str]) -> int:
    """Free transfers available for the next deadline, walked from GW-by-GW
    ``event_transfers``. The manager's first event is squad creation (no FT
    concept); every later event consumes then banks +1, capped at 5;
    wildcard/free-hit weeks consume nothing."""
    ft = 1
    for h in sorted(history_current, key=lambda h: h["event"])[1:]:
        chip = chips_by_event.get(int(h["event"]))
        n = 0 if chip in ("wildcard", "freehit") else int(h.get("event_transfers", 0))
        ft = min(MAX_BANKED_FT, max(ft - n, 0) + 1)
    return ft


def reconstruct_purchase_prices(
    first_picks: list[dict],
    transfers: list[dict],
    chips_by_event: dict[int, str],
    start_prices: dict[int, int],
    joined_at_gw1: bool,
) -> dict[int, int | None]:
    """element -> purchase price in tenths (None = unknowable, caller
    approximates with current price). Last buy wins; free-hit transfers
    revert and are skipped."""
    price: dict[int, int | None] = {}
    for p in first_picks:
        el = int(p["element"])
        price[el] = start_prices.get(el) if joined_at_gw1 else None
    for t in sorted(transfers, key=lambda t: t["time"]):
        if chips_by_event.get(int(t["event"])) == "freehit":
            continue
        price[int(t["element_in"])] = int(t["element_in_cost"])
    return price


def chips_available_now(
    chips_played: list[dict], next_gw: int, first_half_deadline_gw: int
) -> list[str]:
    """Chips playable at the next deadline: one of each per half-season, the
    unused first-half set expiring after the split gameweek."""
    second_half = next_gw > first_half_deadline_gw
    used_this_half = {
        c["name"] for c in chips_played if (int(c["event"]) > first_half_deadline_gw) == second_half
    }
    return [c for c in CHIP_NAMES.values() if c not in used_this_half]


def build_team_state(
    entry: dict,
    history: dict,
    picks_now: dict,
    picks_first: dict,
    transfers: list[dict],
    bootstrap: dict,
    first_half_deadline_gw: int = 19,
) -> dict[str, Any]:
    """Pure assembly of the import payload from raw endpoint payloads."""
    current_event = int(entry["current_event"])
    started_event = int(entry.get("started_event") or 1)
    next_gw = current_event + 1

    els = {int(e["id"]): e for e in bootstrap["elements"]}
    teams = {int(t["id"]): t["name"] for t in bootstrap["teams"]}

    chips_played = [
        {"name": CHIP_NAMES.get(c["name"], c["name"]), "event": int(c["event"])}
        for c in history.get("chips", [])
    ]
    chips_by_event = {c["event"]: c["name"] for c in chips_played}

    # Squad now = the last public picks plus any pending transfers made since
    # that deadline (transfers for a pending free-hit week revert, so skip).
    pending = [
        t
        for t in transfers
        if int(t["event"]) > current_event and chips_by_event.get(int(t["event"])) != "freehit"
    ]
    picks_by_el = {int(p["element"]): p for p in picks_now["picks"]}
    squad_els = [int(p["element"]) for p in picks_now["picks"]]
    for t in pending:
        if int(t["element_out"]) in squad_els:
            squad_els.remove(int(t["element_out"]))
        squad_els.append(int(t["element_in"]))

    start_prices = {
        el: int(e["now_cost"]) - int(e.get("cost_change_start") or 0) for el, e in els.items()
    }
    purchase = reconstruct_purchase_prices(
        picks_first["picks"], transfers, chips_by_event, start_prices, started_event == 1
    )
    approx = False

    squad = []
    for el in squad_els:
        e = els.get(el)
        if e is None:
            continue  # left the game pool entirely — surfaced via shape warning
        bought = purchase.get(el)
        if bought is None:
            bought = int(e["now_cost"])
            approx = True
        pick = picks_by_el.get(el)
        squad.append(
            {
                "element": el,
                "code": int(e["code"]),
                "player": f"{e['first_name']} {e['second_name']}".strip(),
                "web_name": e.get("web_name"),
                "position": POSITIONS.get(int(e["element_type"]), "?"),
                "team": teams.get(int(e["team"]), "?"),
                "current_price": int(e["now_cost"]),
                "purchase_price": bought,
                "selling_price": sell_price(bought, int(e["now_cost"])),
                "squad_position": int(pick["position"]) if pick else None,
                "is_captain": bool(pick and pick.get("is_captain")),
                "is_vice_captain": bool(pick and pick.get("is_vice_captain")),
            }
        )
    squad.sort(key=lambda p: (p["squad_position"] is None, p["squad_position"] or 99))

    hist_now = picks_now.get("entry_history", {})
    bank = int(hist_now.get("bank") or entry.get("last_deadline_bank") or 0)
    for t in pending:
        bank += int(t["element_out_cost"]) - int(t["element_in_cost"])

    warnings = []
    shape = {"GKP": 0, "DEF": 0, "MID": 0, "FWD": 0}
    for p in squad:
        shape[p["position"]] = shape.get(p["position"], 0) + 1
    if len(squad) != 15 or shape != {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}:
        warnings.append(f"unexpected squad shape {shape} ({len(squad)} players)")
    if approx:
        warnings.append(
            "some purchase prices are approximated with current prices "
            "(team started after GW1), so sell values may be slightly off"
        )

    out: dict[str, Any] = {
        "status": "ok",
        "team_id": int(entry["id"]),
        "team_name": entry.get("name"),
        "manager": f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}".strip(),
        "gw": current_event,
        "overall_points": entry.get("summary_overall_points"),
        "overall_rank": entry.get("summary_overall_rank"),
        "last_gw_points": entry.get("summary_event_points"),
        "squad": squad,
        "bank": bank,
        "team_value": int(hist_now.get("value") or entry.get("last_deadline_value") or 0),
        "free_transfers": reconstruct_free_transfers(history.get("current", []), chips_by_event),
        "active_chip": CHIP_NAMES.get(picks_now.get("active_chip") or "", None),
        "chips_played": chips_played,
        "chips_available": chips_available_now(chips_played, next_gw, first_half_deadline_gw),
        "approx_purchase_prices": approx,
        "pending_transfers": len(pending),
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    if pending:
        out["note"] = (
            f"{len(pending)} transfer(s) already made for GW{next_gw} are applied "
            "to the squad and bank; captain/bench shown are from "
            f"GW{current_event}'s picks"
        )
    if warnings:
        out["warnings"] = warnings
    return out


# One import is 4-5 FPL API calls; My Team refetches on every visit, so cache
# briefly (in-memory, single-process — same posture as the chat rate limiter).
_CACHE_TTL = 300.0
_cache: dict[int, tuple[float, dict]] = {}


def fetch_team_state(team_id: int, first_half_deadline_gw: int = 19) -> dict[str, Any]:
    """Live fetch + assembly. Returns the state payload, a ``pending`` payload
    pre-deadline, or an ``error`` payload for unknown IDs."""
    team_id = int(team_id)
    hit = _cache.get(team_id)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]

    snap = latest_snapshot("bootstrap_static")
    if snap is None:
        return {"error": "engine has no bootstrap snapshot yet — try again shortly"}
    _, bootstrap = snap

    import httpx

    with FplApi() as api:
        try:
            entry = api.entry(team_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return {"error": f"no FPL team with ID {team_id} — check the number"}
            raise
        if not entry.get("current_event"):
            return {
                "status": "pending",
                "team_id": team_id,
                "team_name": entry.get("name"),
                "note": PENDING_NOTE,
            }
        current_event = int(entry["current_event"])
        started_event = int(entry.get("started_event") or 1)
        history = api.entry_history(team_id)
        try:
            picks_now = api.entry_picks(team_id, current_event)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return {
                    "status": "pending",
                    "team_id": team_id,
                    "team_name": entry.get("name"),
                    "note": PENDING_NOTE,
                }
            raise
        picks_first = (
            picks_now if started_event == current_event else api.entry_picks(team_id, started_event)
        )
        transfers = api.entry_transfers(team_id)

    state = build_team_state(
        entry, history, picks_now, picks_first, transfers, bootstrap,
        first_half_deadline_gw,
    )  # fmt: skip
    _cache[team_id] = (time.monotonic(), state)
    return state
