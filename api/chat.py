"""Grounded chat: Claude as orchestrator over the engine's typed tools.

PLAN.md §6. The model interprets the question, calls engine tools, and
narrates their results — it never computes or invents a statistic. The
grounding contract lives in the system prompt; the SSE stream surfaces every
tool call and result so the UI can render provenance cards next to the prose.

Model: ``claude-sonnet-5`` per PLAN §6 — the grounded design pushes all hard
reasoning into the engine, so the LLM only parses intent, sequences tools,
and narrates faithfully. The system prompt and tool definitions are cached
(``cache_control``) to keep per-turn cost down.

Requires Anthropic credentials (``ANTHROPIC_API_KEY`` or an ``ant auth
login`` profile).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import anthropic
from anthropic import beta_tool
from dotenv import load_dotenv

from api import tools as t
from api.data import get_store

# Repo-root .env (gitignored) — the place to put ANTHROPIC_API_KEY. Loaded here
# so both the API server and the evals entry point pick it up.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

MODEL = "claude-sonnet-5"  # PLAN §6: orchestrator only — the engine does the math
MAX_TOKENS = 4096


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


@beta_tool
def get_player(query: str) -> str:
    """Get a player's profile: price, projected points, 0-100 rating with
    sub-scores, and upcoming fixtures. Call this whenever the user asks about
    a specific player.

    Args:
        query: Player name (partial names like "Haaland" are fine).
    """
    return _json(t.get_player(query))


@beta_tool
def project_points(players: list[str]) -> str:
    """Per-gameweek expected points for one or more players, decomposed by
    source (goals, assists, clean sheets, bonus, ...). Call this to explain
    WHY a player is projected what he's projected, or for captaincy ceilings.

    Args:
        players: Player names to project.
    """
    return _json(t.project_points(players))


@beta_tool
def compare_players(players: list[str]) -> str:
    """Side-by-side comparison (price, projected points, rating, sub-scores).
    Call this for any "X or Y?" decision.

    Args:
        players: Two or more player names to compare.
    """
    return _json(t.compare_players(players))


@beta_tool
def rank_players(
    position: str | None = None,
    max_price: float | None = None,
    team: str | None = None,
    sort_by: str = "xpts",
    limit: int = 10,
) -> str:
    """Top players by projection, rating, or value, with filters. Call this
    for "best/cheap X" questions (e.g. best DEF under 5.5).

    Args:
        position: GKP, DEF, MID, or FWD (omit for all positions).
        max_price: Maximum price in millions, e.g. 5.5.
        team: Filter to one club.
        sort_by: "xpts" (projected points), "rating", or "value" (xPts per million).
        limit: How many players to return.
    """
    return _json(t.rank_players(position, max_price, team, sort_by, limit))


@beta_tool
def get_fixtures(team: str) -> str:
    """A team's upcoming fixtures with model difficulty: expected goals for and
    against, clean-sheet probability per match.

    Args:
        team: Club name, e.g. "Arsenal" or "Spurs".
    """
    return _json(t.get_fixtures(team))


@beta_tool
def explain_rating(query: str) -> str:
    """Break down why a player has his rating: each sub-score (percentile
    within position) plus his strongest and weakest dimensions.

    Args:
        query: Player name.
    """
    return _json(t.explain_rating(query))


@beta_tool
def build_squad(
    budget: float = 100.0,
    locked: list[str] | None = None,
    excluded: list[str] | None = None,
) -> str:
    """Solve the optimal 15-man squad with a MILP: starting XI, formation,
    captain, vice, bench order. Call this for "build me a team" requests.

    Args:
        budget: Budget in millions (default 100.0).
        locked: Players that must be in the squad.
        excluded: Players that must not be in the squad.
    """
    return _json(t.build_squad(budget, locked, excluded))


@beta_tool
def rate_my_draft(players: list[str]) -> str:
    """Rate a user's 15-man draft: best XI/captain/bench from it, its expected
    points, and the gap to the optimal squad at the same budget. Requires all
    15 names (2 GKP, 5 DEF, 5 MID, 3 FWD).

    Args:
        players: Exactly 15 player names.
    """
    return _json(t.rate_my_draft(players))


@beta_tool
def plan_transfers(
    players: list[str],
    bank: float = 0.0,
    free_transfers: int = 1,
    horizon: int | None = None,
) -> str:
    """Multi-gameweek transfer plan solved by the engine's MILP: which moves
    to make and when, whether a −4 hit pays for itself, and when to bank a
    free transfer. Call this when the user asks about transfers, hits, or
    planning ahead — it needs their current 15 players (ask for them, or use
    the draft if they've shared it). Before GW1 it runs as a preview that
    treats the draft as locked from GW1.

    Args:
        players: The user's current 15 players (2 GKP, 5 DEF, 5 MID, 3 FWD).
        bank: Money in the bank in millions, e.g. 0.5.
        free_transfers: Free transfers available now (1-5).
        horizon: How many gameweeks to plan over (default: the full projection window).
    """
    return _json(t.plan_transfers(players, bank, free_transfers, horizon))


@beta_tool
def chip_advice(
    players: list[str],
    bank: float = 0.0,
    free_transfers: int = 1,
    chips: list[str] | None = None,
) -> str:
    """Chip advice (wildcard / free hit / bench boost / triple captain):
    engine-computed expected gain for playing each chip in every visible
    gameweek, on top of the optimal transfer plan. Call this when the user
    asks when to play a chip — it needs their current 15 (ask if you don't
    have them). Report the engine's assessment honestly, including "no
    standout week visible" — the window only covers the next few GWs.

    Args:
        players: The user's current 15 players (2 GKP, 5 DEF, 5 MID, 3 FWD).
        bank: Money in the bank in millions.
        free_transfers: Free transfers available now (1-5).
        chips: Which chips they still hold, from: wildcard, freehit, bboost,
            triple_captain (omit for all four).
    """
    return _json(t.chip_advice(players, bank, free_transfers, chips))


TOOLS = [
    get_player,
    project_points,
    compare_players,
    rank_players,
    get_fixtures,
    explain_rating,
    build_squad,
    rate_my_draft,
    plan_transfers,
    chip_advice,
]


def system_prompt() -> str:
    prov = get_store().provenance
    return f"""You are the assistant for an FPL (Fantasy Premier League) analytics site. You sit \
on top of a statistical engine that computes projections, ratings, and optimal squads; your job \
is to interpret the user's question, call the engine's tools, and explain the results clearly.

THE GROUNDING CONTRACT (non-negotiable):
- Every statistic, projection, rating, ranking, price, probability, or recommendation you state \
must come from a tool result in this conversation. Never estimate, extrapolate, or fill gaps \
from your own knowledge — if a tool doesn't cover the question, say so plainly.
- Your football knowledge may be used for context and phrasing only ("a tough away fixture"), \
never for numbers or picks. Your knowledge of current squads, prices, form, and transfers is \
stale; the tools are current — trust them over your priors, and don't editorialize disagreement.
- If a tool returns an error or no match, report that honestly. Never invent a player, price, \
or projection to be helpful.
- General football history questions (e.g. "who won the league in 2019") are fine to answer \
from knowledge, but make clear that's general knowledge, not engine output.

Current data: season {prov["season"]}, gameweeks {prov["gw_window"][0]}-{prov["gw_window"][1]}, \
computed {prov["computed_at"][:16]} from API snapshot {prov["data_snapshot"]}.

Style: be direct and concrete, like a sharp analyst friend. Lead with the answer, then the \
supporting numbers. Use the decomposition tools to explain *why* (e.g. "mostly clean-sheet \
points — his attacking sub-score is only 41"). Prices in £m, points to one decimal. When the \
user must make a judgment call (risk appetite, differentials vs template), lay out the \
engine's numbers for each side rather than pretending there's a computed answer."""


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def chat_stream(messages: list[dict]) -> Iterator[str]:
    """Run one assistant turn; yield SSE events: text deltas, tool cards, done."""
    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
        tools=TOOLS,
        messages=messages,
        stream=True,
    )
    try:
        for stream in runner:
            for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield sse("text", {"delta": event.delta.text})
            final = stream.get_final_message()
            for block in final.content:
                if block.type == "tool_use":
                    yield sse(
                        "tool_use", {"id": block.id, "name": block.name, "input": block.input}
                    )
            tool_response = runner.generate_tool_call_response()
            if tool_response is not None:
                for blk in tool_response["content"]:
                    payload = blk["content"]
                    try:
                        payload = json.loads(payload)
                    except (TypeError, ValueError):
                        pass
                    yield sse("tool_result", {"tool_use_id": blk["tool_use_id"], "result": payload})
        yield sse("done", {})
    except Exception as e:  # missing credentials raise TypeError, not APIError —
        # whatever happens, the UI must get an error event, not a dead stream
        yield sse("error", {"message": f"{type(e).__name__}: {getattr(e, 'message', str(e))}"})


def run_chat(messages: list[dict]) -> dict:
    """Non-streaming turn for evals/tests: final text + every tool call made."""
    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
        tools=TOOLS,
        messages=messages,
    )
    tool_calls: list[dict] = []
    text = ""
    for message in runner:
        text = "".join(b.text for b in message.content if b.type == "text")
        tool_calls += [
            {"name": b.name, "input": b.input} for b in message.content if b.type == "tool_use"
        ]
    return {"text": text, "tool_calls": tool_calls}
