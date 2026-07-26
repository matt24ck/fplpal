"""Verify season-rules config against the live game's bootstrap snapshot.

Checks every rule the public API exposes — squad shape, budget, club limit,
formation bounds, banked-transfer cap, chip counts and half-season windows —
against ``seasons/<season>.json``. Scoring point values (goal/CS/DC/etc.) are
NOT in the API (they live in the game client), so they remain a manual check
against the game's rules page; this script lists exactly what it could not
verify. Flip ``verified_against_game`` in the JSON by hand once both halves
pass.

Run: ``python -m engine.config.verify``
"""

from __future__ import annotations

from collections import Counter

from engine.config.season import load_season
from engine.ingest.snapshot import latest_snapshot

API_CHIP_NAMES = {
    "wildcard": "wildcard",
    "freehit": "freehit",
    "bboost": "bboost",
    "3xc": "triple_captain",
}


def verify(season: str = "2026-27") -> bool:
    snap = latest_snapshot("bootstrap_static")
    if snap is None:
        raise SystemExit("no bootstrap snapshot archived — run: python -m engine.ingest.snapshot")
    path, bs = snap
    rules = load_season(season)
    gs = bs["game_settings"]

    checks: list[tuple[str, object, object]] = []
    checks.append(("budget (tenths)", rules.squad.budget, gs["squad_total_spend"]))
    checks.append(("squad size", rules.squad.size, gs["squad_squadsize"]))
    checks.append(("starting XI size", 11, gs["squad_squadplay"]))
    checks.append(("max per club", rules.squad.max_per_club, gs["squad_team_limit"]))
    checks.append(
        ("banked transfers cap", rules.transfers.max_banked, 1 + gs["max_extra_free_transfers"])
    )

    et = {e["singular_name_short"]: e for e in bs["element_types"]}
    for pos, count in rules.squad.positions.items():
        checks.append((f"squad {pos} count", count, et[pos]["squad_select"]))
    for pos, (lo, hi) in rules.squad.formation.items():
        checks.append((f"XI {pos} min", lo, et[pos]["squad_min_play"]))
        checks.append((f"XI {pos} max", hi, et[pos]["squad_max_play"]))

    api_chips = bs.get("chips", [])
    counts = Counter(API_CHIP_NAMES.get(c["name"], c["name"]) for c in api_chips)
    for attr in ("wildcard", "freehit", "bboost", "triple_captain"):
        rule = getattr(rules.chips, attr)
        checks.append((f"chip {attr} total", rule.count, counts.get(attr, 0)))
    first_half_stops = sorted({c["stop_event"] for c in api_chips if c["start_event"] <= 2})
    checks.append(
        ("chip half boundary GW", rules.chips.first_half_deadline_gw, first_half_stops[0])
    )

    print(f"config {season} vs bootstrap snapshot {path.name}:")
    failures = 0
    for name, expected, actual in checks:
        ok = expected == actual
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}: config {expected} | api {actual}")

    print(
        f"\n{len(checks) - failures}/{len(checks)} API-verifiable rules match."
        + ("" if failures == 0 else f" {failures} MISMATCH — fix seasons/{season}.json!")
    )
    print(
        "\nnot API-verifiable (check manually against the game's rules page, then flip\n"
        "verified_against_game in the season JSON): scoring point values (appearance,\n"
        "goal/assist/CS by position, conceded, saves-per-3, penalty save/miss, cards,\n"
        "own goal, bonus 3/2/1) and the defensive-contribution thresholds (DEF 10 CBIT,\n"
        "MID/FWD 12 CBIRT) + its 2-point award."
    )
    return failures == 0


if __name__ == "__main__":
    verify()
