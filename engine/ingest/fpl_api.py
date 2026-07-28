"""Thin client for the official (but undocumented) FPL API.

All endpoints used here are public and unauthenticated. Responses are returned
as parsed JSON without validation — schema validation happens downstream so
that raw snapshots get archived even when the schema drifts (the API has no
SLA; preserving the bytes is the priority).
"""

from __future__ import annotations

import time
from types import TracebackType
from typing import Any

import httpx

BASE_URL = "https://fantasy.premierleague.com/api"
USER_AGENT = "fpl-ai-site/0.1"


class MaintenanceError(Exception):
    """The FPL API is in maintenance ('Game Updating') — season rollover or GW processing."""


class FplApi:
    """Synchronous FPL API client with basic retry on transient failures."""

    def __init__(self, timeout: float = 30.0, retries: int = 3) -> None:
        self._retries = retries
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )

    # -- endpoints ---------------------------------------------------------

    def bootstrap_static(self) -> dict[str, Any]:
        """Players, teams, gameweeks, prices, ownership, game settings."""
        return self._get("bootstrap-static/")

    def fixtures(self, event: int | None = None) -> list[dict[str, Any]]:
        """All fixtures, or one gameweek's with ``event``."""
        params = {"event": event} if event is not None else None
        return self._get("fixtures/", params=params)

    def element_summary(self, player_id: int) -> dict[str, Any]:
        """One player's per-GW current-season history, past-season totals, upcoming fixtures."""
        return self._get(f"element-summary/{player_id}/")

    def event_live(self, gameweek: int) -> dict[str, Any]:
        """Live per-player stats for a gameweek (in-play and final)."""
        return self._get(f"event/{gameweek}/live/")

    def set_piece_notes(self) -> dict[str, Any]:
        """Penalty/set-piece taker notes per team."""
        return self._get("team/set-piece-notes/")

    def entry(self, team_id: int) -> dict[str, Any]:
        """A manager's public team metadata (name, overall rank, value)."""
        return self._get(f"entry/{team_id}/")

    def entry_history(self, team_id: int) -> dict[str, Any]:
        """A manager's per-GW season history and chips played."""
        return self._get(f"entry/{team_id}/history/")

    def entry_picks(self, team_id: int, gameweek: int) -> dict[str, Any]:
        """A manager's picks for a gameweek (public once the GW starts)."""
        return self._get(f"entry/{team_id}/event/{gameweek}/picks/")

    def entry_transfers(self, team_id: int) -> list[dict[str, Any]]:
        """A manager's full transfer history (element in/out with prices paid)."""
        return self._get(f"entry/{team_id}/transfers/")

    # -- plumbing ----------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_exc: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                resp = self._client.get(path, params=params)
                if resp.status_code == 503:
                    # FPL serves 503 with a "Game Updating" page during season
                    # rollover and GW processing — a state, not a transient fault.
                    raise MaintenanceError(
                        "FPL API is updating (503). During the summer rollover this "
                        "can last days; use snapshot --watch-minutes to poll for launch."
                    )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise  # 4xx is our bug or a changed endpoint — never retry
                last_exc = exc
            except httpx.TransportError as exc:
                last_exc = exc
            if attempt < self._retries:
                time.sleep(1.5 * attempt)
        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FplApi":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
