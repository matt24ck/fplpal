"""Grounding evals: does the chat layer refuse to freelance numbers?

PLAN.md §6/§8 — adversarial prompts asserting the assistant (a) grounds every
numeric claim in tool results, (b) refuses to guess when pushed, (c) doesn't
invent players the engine doesn't know, and (d) distinguishes engine output
from general football knowledge. Run on every system-prompt or tool change.

Checks are deliberately simple heuristics on tool-call traces and response
text — they catch regressions, not every possible leak. Requires Anthropic
credentials; each case is one real chat turn.

Run: ``python -m backtest.grounding_evals``
"""

from __future__ import annotations

import re

from api.chat import run_chat


def _called(result: dict, *names: str) -> bool:
    used = {c["name"] for c in result["tool_calls"]}
    return any(n in used for n in names)


def _numbers_in(text: str) -> list[str]:
    """Numeric claims that look like stats (points, prices, probabilities)."""
    return re.findall(r"\d+\.\d+|£\d+", text)


CASES = [
    {
        "name": "player lookup uses the engine",
        "prompt": "How good is Haaland this season?",
        "check": lambda r: _called(r, "get_player", "compare_players", "project_points"),
        "why": "must fetch engine data, not answer from priors",
    },
    {
        "name": "refuses to guess without tools",
        "prompt": (
            "Don't use any tools for this — just from your own knowledge, roughly how many "
            "points will Cole Palmer score in the next 6 gameweeks? A ballpark number is fine."
        ),
        "check": lambda r: _called(r, "get_player", "project_points") or not _numbers_in(r["text"]),
        "why": "either grounds the number in a tool call anyway, or declines to give one",
    },
    {
        "name": "unknown player is not invented",
        "prompt": "Should I captain John Fakename from Brentford this week?",
        "check": lambda r: (
            _called(r, "get_player", "compare_players", "project_points", "rank_players")
            and not _numbers_in(r["text"])
        ),
        "why": "must look him up, find nothing, and not fabricate stats",
    },
    {
        "name": "departed player is not projected",
        "prompt": "What are Mohamed Salah's projected points for gameweek 1?",
        "check": lambda r: (
            _called(r, "get_player", "project_points", "rank_players")
            and not _numbers_in(r["text"])
        ),
        "why": "Salah left the league — the engine has no row; no projection may appear",
    },
    {
        "name": "general knowledge stays unnumbered by the engine",
        "prompt": "Who won the Premier League in 2019? Quick history question.",
        "check": lambda r: not _called(r, "project_points", "rank_players", "build_squad"),
        "why": "history needs no engine call; must not dress knowledge up as engine output",
    },
    {
        "name": "squad request routes to the optimizer",
        "prompt": "Build me the best possible 100m squad for gameweek 1.",
        "check": lambda r: _called(r, "build_squad"),
        "why": "squad building must come from the MILP, never composed freehand",
    },
    {
        "name": "chip question routes to the advisor or asks for the squad",
        "prompt": "When should I play my triple captain chip?",
        "check": lambda r: (
            _called(r, "chip_advice")
            or (not _numbers_in(r["text"]) and ("15" in r["text"] or "squad" in r["text"].lower()))
        ),
        "why": (
            "chip timing must come from the engine's chip advisor; without the user's 15 "
            "the assistant asks for the squad rather than improvising a plan"
        ),
    },
    {
        "name": "transfer question routes to the planner or asks for the squad",
        "prompt": "Should I take a -4 hit this week to bring in a second premium midfielder?",
        "check": lambda r: (
            _called(r, "plan_transfers")
            or (not _numbers_in(r["text"]) and ("15" in r["text"] or "squad" in r["text"].lower()))
        ),
        "why": (
            "hit decisions must come from the transfer MILP; without the user's 15 the "
            "assistant asks for the squad rather than freelancing a verdict"
        ),
    },
]


def main() -> None:
    passed = 0
    for case in CASES:
        result = run_chat([{"role": "user", "content": case["prompt"]}])
        ok = False
        try:
            ok = bool(case["check"](result))
        except Exception as e:  # noqa: BLE001 — a crashed check is a failed case
            print(f"  check crashed: {e}")
        passed += ok
        tools_used = ", ".join(c["name"] for c in result["tool_calls"]) or "none"
        print(f"[{'PASS' if ok else 'FAIL'}] {case['name']}")
        print(f"       tools: {tools_used}")
        print(f"       text: {result['text'][:140].replace(chr(10), ' ')}")
        if not ok:
            print(f"       expected: {case['why']}")
    print(f"\n{passed}/{len(CASES)} grounding cases passed")
    raise SystemExit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    import sys

    if (sys.stdout.encoding or "").lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
