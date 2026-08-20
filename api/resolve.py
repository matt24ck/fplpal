"""Name resolution for screenshot-extracted squads.

Maps one shirt-label string (an FPL ``web_name``, possibly truncated with an
ellipsis) to a store player row. FPL's own web_names are nearly unique per
position — the site adds disambiguating initials itself ("Sarr" vs
"P.M.Sarr") — so exact web_name + pitch-row matching resolves almost
everything. The stages run strongest-first and a kit hint is only ever a
tiebreaker between same-name candidates, never trusted on its own (vision
models mis-read kits often).

Graded against the labelled screenshot set by ``test/spike_extract.py``.
"""

from __future__ import annotations

import difflib
import unicodedata

import pandas as pd

# fuzzy matching is the safety net for blurry uploads — on clean screenshots
# the exact stages do all the work (spike: 105/105 without a single fuzzy hit)
FUZZY_CUTOFF = 0.75
FUZZY_BAND = 0.05  # candidates within this of the best score stay visible
PREFIX_MIN = 6  # shortest label treated as a truncation even without "…"
MAX_CANDIDATES = 5


def norm(s: str) -> str:
    """Accent-fold and canonicalise a name for matching.

    Dots and hyphens become spaces ("B.Fernandes" == "B. Fernandes"),
    apostrophes vanish ("O'Shea" == "OShea"), casefold turns ß into ss, and a
    trailing truncation ellipsis is dropped.
    """
    s = s.replace("…", " ").replace("...", " ")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    for ch in ".-":
        s = s.replace(ch, " ")
    for ch in "'’":
        s = s.replace(ch, "")
    return " ".join(s.split())


def _clean(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


class Resolver:
    """Matches extracted shirt labels against a ``LiveStore.players`` frame."""

    def __init__(self, players: pd.DataFrame) -> None:
        self.rows = players.to_dict("records")
        for r in self.rows:
            r["_web"] = norm(_clean(r.get("web_name")))
            r["_full"] = norm(_clean(r.get("player")))
            r["_sur"] = r["_full"].rsplit(" ", 1)[-1] if r["_full"] else ""

    def resolve(self, name: str, row_pos: str | None = None, team_hint: str | None = None) -> dict:
        """Match one extracted label.

        Returns ``{status, method, match, candidates}`` — status "ok" means a
        unique match, "ambiguous" means the top candidate needs the user's
        confirmation, "none" means nothing plausible was found.
        """
        q = norm(name)
        if not q:
            return {"status": "none", "method": "empty", "match": None, "candidates": []}
        truncated = name.rstrip().endswith(("…", "..."))
        # search the extracted position band first (the pitch row is reliable),
        # fall back to the whole pool in case the row was mis-read
        pools: list[list[dict]] = []
        if row_pos:
            pos_pool = [p for p in self.rows if p["position"] == row_pos]
            if pos_pool:
                pools.append(pos_pool)
        pools.append(self.rows)

        for pool in pools:
            for method, hit in (
                ("web", lambda r: r["_web"] == q),
                ("full", lambda r: r["_full"] == q),
                ("token", lambda r: q in r["_full"].split() or q in r["_web"].split()),
                (
                    "prefix",
                    lambda r: (
                        (truncated or len(q) >= PREFIX_MIN)
                        and (r["_web"].startswith(q) or r["_full"].startswith(q))
                    ),
                ),
            ):
                cands = [r for r in pool if hit(r)]
                if cands:
                    return self._pick(cands, method, team_hint)
            scored = []
            for r in pool:
                score = max(
                    difflib.SequenceMatcher(None, q, r["_web"]).ratio(),
                    difflib.SequenceMatcher(None, q, r["_sur"]).ratio(),
                )
                if score >= FUZZY_CUTOFF:
                    scored.append((score, r))
            if scored:
                scored.sort(key=lambda t: (-t[0], -t[1]["xpts"]))
                top = scored[0][0]
                cands = [r for s, r in scored if s >= top - FUZZY_BAND]
                return self._pick(cands, "fuzzy", team_hint)
        return {"status": "none", "method": "none", "match": None, "candidates": []}

    def _pick(self, cands: list[dict], method: str, team_hint: str | None) -> dict:
        if len(cands) > 1 and team_hint:
            th = norm(team_hint)
            narrowed = [r for r in cands if th and (th in norm(r["team"]) or norm(r["team"]) in th)]
            if narrowed:
                cands, method = narrowed, method + "+kit"
        cands = sorted(cands, key=lambda r: -r["xpts"])
        return {
            "status": "ok" if len(cands) == 1 else "ambiguous",
            "method": method,
            "match": cands[0],
            "candidates": cands[:MAX_CANDIDATES],
        }
