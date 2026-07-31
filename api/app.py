"""FastAPI app: REST endpoints over the engine + the grounded chat stream.

REST serves the same tool functions the chat model calls, so UI tables and
chat answers always come from identical payloads. ``/chat`` streams SSE:
``text`` deltas, ``tool_use`` / ``tool_result`` events (the UI renders these
as provenance cards), then ``done``.

Run: ``uvicorn api.app:app --reload``
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api import db
from api import tools as t
from api.auth import require_user
from api.data import get_store
from api.jobs import jobs_enabled, start_background
from engine.config.season import load_season
from engine.ingest.snapshot import latest_snapshot
from engine.models.ratings import SUBSCORES


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if jobs_enabled():
        start_background()
    yield


app = FastAPI(title="FPL AI Engine", version="0.1.0", lifespan=lifespan)


@app.exception_handler(FileNotFoundError)
async def _data_not_ready(_request: Request, _exc: FileNotFoundError):
    # live parquets absent (first-boot seeding / mid-rebuild): a clean 503,
    # not a 500 traceback — the UI shows its "engine offline" state
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=503,
        content={"detail": "engine data not ready — seeding or refresh in progress"},
    )


app.add_middleware(
    CORSMiddleware,
    # deployed: set CORS_ORIGINS to the web app's origin(s), comma-separated —
    # tolerate stray spaces and trailing slashes, which browsers never send
    allow_origins=[
        o.strip().rstrip("/")
        for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
        if o.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    try:
        return {"ok": True, **get_store().provenance}
    except FileNotFoundError:
        # first boot on an empty volume: the jobs thread is still seeding
        return {"ok": False, "status": "no live data yet — seeding/pipeline pending"}


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
    pool = store.players.merge(store.ratings[["code", "rating", *sub_cols]], on="code", how="left")
    gw_xpts = {
        code: {int(r.gw): round(float(r.xpts), 2) for r in grp.itertuples()}
        for code, grp in store.per_gw.groupby("code")
    }
    from engine.models.event_rates import data_basis

    players = []
    for r in pool.itertuples():
        subs = {
            name: None
            if np.isnan(getattr(r, f"score_{name}"))
            else round(getattr(r, f"score_{name}"))
            for name in SUBSCORES.get(str(r.position), [])
        }
        basis = data_basis(r.exposure_90)
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
                "data_basis": {"level": basis["level"], "effective_90s": basis["effective_90s"]},
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
        "teams": [{"team": t, "cells": [cells[t][g] for g in gws]} for t in store.teams],
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
def squad_optimize(req: SquadRequest, user: str = Depends(require_user)) -> dict:
    return _ok(t.build_squad(req.budget, req.locked, req.excluded))


class DraftRequest(BaseModel):
    players: list[str] = Field(min_length=15, max_length=15)


@app.post("/squad/rate")
def squad_rate(req: DraftRequest) -> dict:
    return _ok(t.rate_my_draft(req.players))


class TransferPlanRequest(BaseModel):
    players: list[str] | None = Field(default=None, min_length=15, max_length=15)
    team_id: int | None = Field(default=None, ge=1)
    bank: float = Field(default=0.0, ge=0.0)
    free_transfers: int = Field(default=1, ge=0, le=5)
    horizon: int | None = Field(default=None, ge=2, le=8)
    alternatives: int = Field(default=1, ge=0, le=2)


# On-demand MILP over the projection window — the heaviest solve we expose,
# so it sits behind auth like the squad optimizer.
@app.post("/transfers/plan")
def transfers_plan(req: TransferPlanRequest, user: str = Depends(require_user)) -> dict:
    return _ok(
        t.plan_transfers(
            req.players, req.bank, req.free_transfers, req.horizon, req.alternatives, req.team_id
        )
    )


class ChipAdviceRequest(BaseModel):
    players: list[str] | None = Field(default=None, min_length=15, max_length=15)
    team_id: int | None = Field(default=None, ge=1)
    bank: float = Field(default=0.0, ge=0.0)
    free_transfers: int = Field(default=1, ge=0, le=5)
    chips: list[str] | None = None


@app.post("/chips/advise")
def chips_advise(req: ChipAdviceRequest, user: str = Depends(require_user)) -> dict:
    return _ok(t.chip_advice(req.players, req.bank, req.free_transfers, req.chips, req.team_id))


# Public FPL data (entry endpoints), briefly cached server-side; no auth —
# picks are public by design once a GW starts, and no engine compute runs.
@app.get("/team/{team_id}")
def team_state(team_id: int) -> dict:
    from engine.ingest.team_state import fetch_team_state

    rules = load_season(get_store().provenance["season"])
    return _ok(fetch_team_state(team_id, rules.chips.first_half_deadline_gw))


# --- live accuracy (public credibility surface) ----------------------------


@app.get("/accuracy")
def accuracy() -> dict:
    """The accuracy report: deadline-frozen projections scored against
    realized points per finished GW, plus pending freezes. Public — the whole
    point is that anyone can check the model's track record."""
    import json

    from engine.accuracy import report_path
    from engine.ingest.played_gw import LIVE_SEASON

    path = report_path()
    if not path.exists():
        return {
            "available": False,
            "season": LIVE_SEASON,
            "gws": [],
            "pending": [],
            "aggregate": None,
        }
    return {"available": True, **json.loads(path.read_text(encoding="utf-8"))}


@app.get("/accuracy/{gw}")
def accuracy_gw(gw: int) -> dict:
    """Player-level projected-vs-realized rows for one scored GW (the
    accuracy page's scatter)."""
    import pandas as pd

    from engine.accuracy import detail_path

    path = detail_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="no scored gameweeks yet")
    d = pd.read_parquet(path)
    d = d[d["gw"] == gw]
    if d.empty:
        raise HTTPException(status_code=404, detail=f"GW{gw} is not scored yet")

    def _f(x, nd=2):
        return None if pd.isna(x) else round(float(x), nd)

    return {
        "gw": gw,
        "players": [
            {
                "code": int(r.code),
                "player": r.player,
                "team": r.team,
                "position": r.position,
                "price": int(r.price),
                "n_fixtures": int(r.n_fixtures),
                "xpts": _f(r.xpts),
                "total_points": int(r.total_points),
                "minutes": int(r.minutes),
                "ep_next": _f(r.ep_next),
                "form4": _f(r.form4),
            }
            for r in d.itertuples()
        ],
    }


# --- per-user state (cross-device draft/team-id sync) ---------------------


def _require_db() -> None:
    if not db.db_enabled():
        raise HTTPException(
            status_code=503,
            detail="persistence not configured — set DATABASE_URL",
        )


class UserStateBody(BaseModel):
    draft: list[int] = Field(default=[], max_length=15)
    team_id: str | None = None


@app.get("/me/state")
def me_state(user: str = Depends(require_user)) -> dict:
    _require_db()
    return db.get_state(user)


@app.put("/me/state")
def me_state_put(body: UserStateBody, user: str = Depends(require_user)) -> dict:
    _require_db()
    db.put_state(user, body.draft, body.team_id)
    return {"ok": True}


class ChatRequest(BaseModel):
    messages: list[dict] = Field(min_length=1)


# Chat spends real money per request — signed-in users only, with a
# fixed-window per-user limit plus a daily all-users token ceiling
# (CHAT_DAILY_TOKEN_CAP, ledger in api.chat where the runner's usage is
# visible; both in-memory, single-process — fine at MVP scale with one
# uvicorn worker).
CHAT_LIMIT_PER_HOUR = int(os.environ.get("CHAT_RATE_LIMIT_PER_HOUR", "30"))
_chat_hits: dict[str, list[float]] = {}


@app.post("/chat")
def chat(req: ChatRequest, user: str = Depends(require_user)) -> StreamingResponse:
    from api.chat import budget_spent

    if budget_spent():
        raise HTTPException(
            status_code=429,
            detail="daily chat budget spent — resets at midnight UTC",
        )
    now = time.time()
    hits = [ts for ts in _chat_hits.get(user, []) if now - ts < 3600]
    if len(hits) >= CHAT_LIMIT_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail="chat rate limit reached — try again in a little while",
        )
    hits.append(now)
    _chat_hits[user] = hits

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
