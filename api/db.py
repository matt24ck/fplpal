"""Per-user state persistence (Postgres) — the cross-device home of the draft
and team ID that previously lived only in the browser's localStorage.

One table, keyed by the Clerk user id ``require_user`` returns. The schema is
created lazily on first use (a single table needs no migration framework at
this scale). ``DATABASE_URL`` unset means persistence is off: the endpoints
503 and the web app silently stays local-only — same graceful posture as the
engine's own not-ready state.
"""

from __future__ import annotations

import json
import os
import threading

from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None
_lock = threading.Lock()

_SCHEMA = """
create table if not exists user_state (
    user_id    text primary key,
    draft      jsonb not null default '[]'::jsonb,
    team_id    text,
    updated_at timestamptz not null default now()
)
"""


def db_enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def _get_pool() -> ConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            # sync endpoints run in FastAPI's threadpool — a small sync pool
            # fits the single-worker deployment
            pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=0, max_size=4, open=True)
            with pool.connection() as conn:
                conn.execute(_SCHEMA)
            _pool = pool
    return _pool


def get_state(user_id: str) -> dict:
    with _get_pool().connection() as conn:
        row = conn.execute(
            "select draft, team_id from user_state where user_id = %s", (user_id,)
        ).fetchone()
    if row is None:
        return {"draft": [], "team_id": None}
    return {"draft": row[0], "team_id": row[1]}


def put_state(user_id: str, draft: list[int], team_id: str | None) -> None:
    with _get_pool().connection() as conn:
        conn.execute(
            """
            insert into user_state (user_id, draft, team_id)
            values (%s, %s::jsonb, %s)
            on conflict (user_id) do update
                set draft = excluded.draft,
                    team_id = excluded.team_id,
                    updated_at = now()
            """,
            (user_id, json.dumps(draft), team_id),
        )
