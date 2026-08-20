"""The 15 and the captain are horizon decisions; the XI is a weekly one.

Locks in the split introduced when ``xpts_next`` was added: supplying the
upcoming-GW column must move the starting XI and the bench order, and must
leave the squad selection and the armband exactly where they were.
"""

from __future__ import annotations

import pandas as pd

from engine.config.season import load_season
from engine.optimize.squad import optimize_lineup, optimize_squad

# One valid 15 (2/5/5/3). Two keepers disagree across horizons: ALPHA is the
# better keeper over the window, OMEGA the better one this week. STAR tops the
# horizon everywhere; FLASH tops the upcoming GW but is mid-tier over the
# window — the captain must stay on STAR.
SQUAD = [
    # player,  position, xpts (window), xpts_next (upcoming GW)
    ("ALPHA", "GKP", 30.0, 1.0),
    ("OMEGA", "GKP", 20.0, 5.0),
    ("D1", "DEF", 25.0, 3.0),
    ("D2", "DEF", 24.0, 3.0),
    ("D3", "DEF", 23.0, 3.0),
    ("D4", "DEF", 22.0, 3.0),
    ("D5", "DEF", 21.0, 3.0),
    ("STAR", "MID", 60.0, 8.0),
    ("M2", "MID", 26.0, 3.5),
    ("M3", "MID", 25.0, 3.4),
    ("M4", "MID", 24.0, 3.3),
    ("M5", "MID", 23.0, 3.2),
    ("FLASH", "FWD", 25.0, 9.0),
    ("F2", "FWD", 24.0, 3.0),
    ("F3", "FWD", 10.0, 0.5),
]


def _squad15() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "code": i,
                "player": name,
                "team": f"club{i % 5}",
                "position": pos,
                "price": 50,
                "xpts": xp,
                "xpts_next": nxt,
            }
            for i, (name, pos, xp, nxt) in enumerate(SQUAD)
        ]
    )


def _xi(sol) -> set[str]:
    return set(sol.squad.loc[sol.squad["in_xi"], "player"])


def _captain(sol) -> str:
    return sol.squad.loc[sol.squad["is_captain"], "player"].iloc[0]


def test_xi_is_solved_on_the_upcoming_gw():
    s15 = _squad15()
    window = optimize_lineup(s15.drop(columns=["xpts_next"]))
    week = optimize_lineup(s15)

    # exactly one keeper starts, and which one flips with the horizon
    assert "ALPHA" in _xi(window) and "OMEGA" not in _xi(window)
    assert "OMEGA" in _xi(week) and "ALPHA" not in _xi(week)

    # the weekly XI is at least as good on the metric it optimizes
    by_name = s15.set_index("player")["xpts_next"]
    assert by_name[list(_xi(week))].sum() >= by_name[list(_xi(window))].sum()


def test_captain_stays_on_the_horizon():
    """FLASH outscores STAR this week but the armband must not chase it.

    Captaincy is an argmax over 15, so a single-week estimate rewards whoever
    drew the luckiest projection; the horizon sum shrinks toward quality.
    """
    s15 = _squad15()
    assert s15.loc[s15["xpts_next"].idxmax(), "player"] == "FLASH"
    assert s15.loc[s15["xpts"].idxmax(), "player"] == "STAR"

    for sol in (optimize_lineup(s15.drop(columns=["xpts_next"])), optimize_lineup(s15)):
        assert _captain(sol) == "STAR"
        assert "STAR" in _xi(sol)  # the captain always starts


def test_bench_order_ranks_on_the_upcoming_gw():
    sol = optimize_lineup(_squad15())
    bench = sol.squad[~sol.squad["in_xi"]].sort_values("bench_order")
    assert bench.iloc[0]["position"] == "GKP"  # keeper always takes slot 1
    outfield = bench[bench["position"] != "GKP"]
    assert outfield["xpts_next"].is_monotonic_decreasing


def test_next_gw_column_is_optional():
    """Callers that pass only ``xpts`` keep the pre-split behaviour."""
    sol = optimize_lineup(_squad15().drop(columns=["xpts_next"]))
    assert sol.xpts_xi_next is None
    assert len(_xi(sol)) == 11


def _pool() -> pd.DataFrame:
    """A candidate pool whose weekly column tracks the window one, as real
    projections do: broadly the same ordering, with every third player lifted
    by a good upcoming fixture — enough to reshuffle who starts, not enough to
    change who is worth owning."""
    counts = {"GKP": 6, "DEF": 14, "MID": 14, "FWD": 8}
    rows, code = [], 0
    for pos, n in counts.items():
        for j in range(n):
            code += 1
            base = 40.0 - 1.5 * j - 0.1 * code  # unique across the pool, no ties
            rows.append(
                {
                    "code": code,
                    "player": f"{pos}{j}",
                    "team": f"club{code % 12}",
                    "position": pos,
                    "price": 40 + (j % 6) * 5,
                    "xpts": base,
                    "xpts_next": base / 6.0 + (0.5 if code % 3 == 0 else 0.0),
                }
            )
    return pd.DataFrame(rows)


def test_squad_selection_ignores_the_upcoming_gw():
    """Which 15 to own is a horizon call — the weekly column must not shift it."""
    rules = load_season("2026-27")
    pool = _pool()

    window = optimize_squad(pool.drop(columns=["xpts_next"]), rules)
    week = optimize_squad(pool, rules)

    assert set(window.squad["code"]) == set(week.squad["code"])
    assert window.cost == week.cost
    assert _captain(window) == _captain(week)
    # ...but the XI genuinely moved, so the headline this-GW figure exists
    assert week.xpts_xi_next is not None
    assert _xi(window) != _xi(week)


def test_a_blanking_leader_hands_over_the_armband():
    """A captain with no fixture scores nothing, so the armband moves down.

    This is the one case where the weekly column touches captaincy: the
    horizon ranking is unchanged, we just skip a player who cannot score.
    """
    s15 = _squad15()
    s15.loc[s15["player"] == "STAR", "xpts_next"] = 0.0  # blanks this week

    ranked = s15.sort_values("xpts", ascending=False)
    expected = ranked[ranked["xpts_next"] > 0].iloc[0]["player"]
    assert expected != "STAR"

    sol = optimize_lineup(s15)
    assert _captain(sol) == expected  # next-best over the window that does play
    assert _captain(sol) in _xi(sol)

    # with a fixture, however small, the horizon leader keeps it
    s15.loc[s15["player"] == "STAR", "xpts_next"] = 0.4
    assert _captain(optimize_lineup(s15)) == "STAR"
