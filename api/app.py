"""FastAPI app: REST endpoints over the engine + the grounded chat stream.

REST serves the same tool functions the chat model calls, so UI tables and
chat answers always come from identical payloads. ``/chat`` streams SSE:
``text`` deltas, ``tool_use`` / ``tool_result`` events (the UI renders these
as provenance cards), then ``done``.

Run: ``uvicorn api.app:app --reload``
"""

from __future__ import annotations

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api import tools as t
from api.data import get_store
from engine.config.season import load_season
from engine.ingest.snapshot import latest_snapshot
from engine.models.ratings import SUBSCORES

app = FastAPI(title="FPL AI Engine", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev server
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"ok": True, **get_store().provenance}


@app.get("/meta")
def meta() -> dict:
    """Everything the UI shell needs that isn't a projection: provenance,
    the next deadline (from the latest bootstrap snapshot), and the season's
    squad/chip rules (from the versioned config) — so no rule or date is ever
    hardcoded client-side."""
    store = get_store()
    prov = store.provenance
    rules = load_season(prov["season"])
    out: dict = {
        "provenance": prov,
        "teams": store.teams,
        "squad_rules": {
            "size": rules.squad.size,
            "budget": rules.squad.budget,
            "positions": rules.squad.positions,
            "max_per_club": rules.squad.max_per_club,
            "formation": rules.squad.formation,
        },
        "chips": {
            name: {"count": chip.count, "halves": chip.halves}
            for name, chip in (
                ("wildcard", rules.chips.wildcard),
                ("freehit", rules.chips.freehit),
                ("bboost", rules.chips.bboost),
                ("triple_captain", rules.chips.triple_captain),
            )
        },
        "first_half_deadline_gw": rules.chips.first_half_deadline_gw,
        "next_deadline": None,
    }
    snap = latest_snapshot("bootstrap_static")
    if snap is not None:
        _, boot = snap
        gw = prov["gw_window"][0]
        event = next((e for e in boot.get("events", []) if e.get("id") == gw), None)
        if event is not None:
            out["next_deadline"] = {"gw": gw, "deadline_time": event.get("deadline_time")}
    return out


def _difficulty(lam_for: float, lam_against: float) -> float:
    """Continuous fixture difficulty from the team's perspective: net expected
    goals against. 0 = even match; positive = harder."""
    return round(float(lam_against) - float(lam_for), 2)


@app.get("/explorer")
def explorer() -> dict:
    """The players-explorer table: every player with rating, position-specific
    sub-scores, per-GW xPts, plus each team's fixture ticker."""
    store = get_store()
    sub_cols = [c for c in store.ratings.columns if c.startswith("score_")]
    pool = store.players.merge(
        store.ratings[["code", "rating", *sub_cols]], on="code", how="left"
    )
    gw_xpts = {
        code: {int(r.gw): round(float(r.xpts), 2) for r in grp.itertuples()}
        for code, grp in store.per_gw.groupby("code")
    }
    players = []
    for r in pool.itertuples():
        subs = {
            name: None if np.isnan(getattr(r, f"score_{name}")) else round(getattr(r, f"score_{name}"))
            for name in SUBSCORES.get(str(r.position), [])
        }
        players.append(
            {
                "code": int(r.code),
                "player": r.player,
                "team": r.team,
                "position": r.position,
                "price": int(r.price),
                "xpts": round(float(r.xpts), 2),
                "p_play": round(float(r.p_play), 3),
                "rating": None if np.isnan(r.rating) else round(float(r.rating)),
                "sub_scores": subs,
                "gw_xpts": gw_xpts.get(int(r.code), {}),
            }
        )
    fx = store.proj.drop_duplicates(["team", "fixture"]).sort_values("gw")
    fixtures = {
        team: [
            {
                "gw": int(f.gw),
                "opponent": f.opponent,
                "home": bool(f.was_home),
                "difficulty": _difficulty(f.lam_for, f.lam_against),
            }
            for f in grp.itertuples()
        ]
        for team, grp in fx.groupby("team")
    }
    return {"players": players, "fixtures": fixtures, "provenance": store.provenance}


@app.get("/fixtures-matrix")
def fixtures_matrix() -> dict:
    """Team × GW matrix with model difficulty per cell (DGW cells carry two
    fixtures, blank cells none)."""
    store = get_store()
    fx = store.proj.drop_duplicates(["team", "fixture"]).sort_values(["team", "gw"])
    gws = sorted(int(g) for g in store.proj["gw"].unique())
    cells: dict[str, dict[int, list[dict]]] = {t: {g: [] for g in gws} for t in store.teams}
    for f in fx.itertuples():
        cells[f.team][int(f.gw)].append(
            {
                "opponent": f.opponent,
                "home": bool(f.was_home),
                "expected_goals_for": round(float(f.lam_for), 2),
                "expected_goals_against": round(float(f.lam_against), 2),
                "clean_sheet_probability": round(float(f.p_cs), 3),
                "difficulty": _difficulty(f.lam_for, f.lam_against),
            }
        )
    return {
        "gws": gws,
        "teams": [
            {"team": t, "cells": [cells[t][g] for g in gws]} for t in store.teams
        ],
        "provenance": store.provenance,
    }


@app.get("/players")
def players(
    position: str | None = None,
    max_price: float | None = None,
    team: str | None = None,
    sort_by: str = "xpts",
    limit: int = 20,
) -> dict:
    return _ok(t.rank_players(position, max_price, team, sort_by, limit))


@app.get("/players/{query}")
def player(query: str) -> dict:
    return _ok(t.get_player(query))


@app.get("/players/{query}/rating")
def rating(query: str) -> dict:
    return _ok(t.explain_rating(query))


@app.get("/fixtures/{team}")
def fixtures(team: str) -> dict:
    return _ok(t.get_fixtures(team))


class ProjectRequest(BaseModel):
    players: list[str] = Field(min_length=1, max_length=20)


@app.post("/projections")
def projections(req: ProjectRequest) -> dict:
    return _ok(t.project_points(req.players))


class SquadRequest(BaseModel):
    budget: float = 100.0
    locked: list[str] = []
    excluded: list[str] = []


@app.post("/squad/optimize")
def squad_optimize(req: SquadRequest) -> dict:
    return _ok(t.build_squad(req.budget, req.locked, req.excluded))


class DraftRequest(BaseModel):
    players: list[str] = Field(min_length=15, max_length=15)


@app.post("/squad/rate")
def squad_rate(req: DraftRequest) -> dict:
    return _ok(t.rate_my_draft(req.players))


class ChatRequest(BaseModel):
    messages: list[dict] = Field(min_length=1)


@app.post("/chat")
def chat(req: ChatRequest) -> StreamingResponse:
    from api.chat import chat_stream

    return StreamingResponse(chat_stream(req.messages), media_type="text/event-stream")


@app.post("/reload")
def reload_data() -> dict:
    get_store().reload()
    return {"ok": True, **get_store().provenance}


def _ok(payload: dict) -> dict:
    if "error" in payload:
        raise HTTPException(status_code=404, detail=payload)
    return payload
