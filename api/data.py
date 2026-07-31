"""Live data store: the engine's precomputed output, served to tools and REST.

Loads the parquet frames the pipeline writes to ``data/live/`` (per-fixture
projections, per-GW aggregates, ratings) and exposes lookup helpers. Chat is
read-only over this precomputed data plus on-demand MILP solves (PLAN.md §7) —
no model fitting happens in the request path.

Every payload the store hands out carries provenance (``data_snapshot``,
``computed_at``) so the chat layer can cite exactly what the numbers were
computed from.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = REPO_ROOT / "data" / "live"


class LiveStore:
    def __init__(self, live_dir: Path | None = None) -> None:
        self.live_dir = live_dir or LIVE_DIR
        self.proj: pd.DataFrame | None = None
        self.per_gw: pd.DataFrame | None = None
        self.ratings: pd.DataFrame | None = None
        self.reload()

    def reload(self) -> None:
        missing = [
            f
            for f in ("projections_fixture", "projections_gw", "ratings")
            if not (self.live_dir / f"{f}.parquet").exists()
        ]
        if missing:
            raise FileNotFoundError(
                f"missing live data ({', '.join(missing)}) — run: python -m engine.pipeline"
            )
        self.proj = pd.read_parquet(self.live_dir / "projections_fixture.parquet")
        self.per_gw = pd.read_parquet(self.live_dir / "projections_gw.parquet")
        self.ratings = pd.read_parquet(self.live_dir / "ratings.parquet")

        p = self.proj
        self.players = (
            p.sort_values("gw")
            .groupby("code", as_index=False)
            .agg(
                player=("player", "first"),
                team=("team", "first"),
                position=("position", "first"),
                price=("price", "first"),
                xpts=("xpts", "sum"),
                p_play=("p_start", "mean"),
                # decayed effective 90s of PL observation — feeds the
                # prior-vs-observed provenance badge (event_rates.data_basis)
                exposure_90=("exposure_90", "max"),
            )
        )
        self.teams = sorted(p["team"].unique())

    @property
    def provenance(self) -> dict:
        row = self.proj.iloc[0]
        return {
            "season": str(row["season"]),
            "gw_window": [int(self.proj["gw"].min()), int(self.proj["gw"].max())],
            "data_snapshot": str(row["data_snapshot"]),
            "computed_at": str(row["computed_at"]),
        }

    # -- lookups -----------------------------------------------------------

    def find_players(self, query: str, limit: int = 5) -> pd.DataFrame:
        """Case-insensitive name match: exact -> whole-token -> substring.

        Whole-token beats substring so "Saka" finds Bukayo Saka, not Sakamoto.
        """
        q = query.strip().casefold()
        names = self.players["player"].str.casefold()
        exact = self.players[names == q]
        if len(exact):
            return exact
        tokens = self.players[names.str.split().apply(lambda ws: any(w == q for w in ws))]
        if len(tokens):
            return tokens.nlargest(limit, "xpts")
        sub = self.players[names.str.contains(q, regex=False)]
        return sub.nlargest(limit, "xpts")

    def find_team(self, query: str) -> str | None:
        q = query.strip().casefold()
        for t in self.teams:
            if t.casefold() == q:
                return t
        matches = [t for t in self.teams if q in t.casefold()]
        return matches[0] if len(matches) == 1 else None

    def player_fixtures(self, code: int) -> pd.DataFrame:
        return self.proj[self.proj["code"] == code].sort_values("gw")

    def player_rating(self, code: int) -> pd.Series | None:
        r = self.ratings[self.ratings["code"] == code]
        return r.iloc[0] if len(r) else None


_store: LiveStore | None = None


def get_store() -> LiveStore:
    global _store
    if _store is None:
        _store = LiveStore()
    return _store
