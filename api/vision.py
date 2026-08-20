"""Screenshot → squad extraction: one narrow vision call + deterministic resolution.

The model only transcribes pixels — shirt labels, pitch rows, C/V badges. It
never produces a number the user sees (PLAN §6 grounding contract): resolution
against the store is deterministic, and rating happens in a separate request
after the user has confirmed the 15. The payload therefore carries per-player
candidates and confidence for the client's confirm step, and ``complete`` only
says whether auto-confirm is safe — a partial or ambiguous read is a normal
200, never discarded.

Spike findings this design bakes in (test/spike_extract.py):
- only name/row/badges are required of the model — it omits optional fields
  (like ``view``) even when the schema marks them required;
- kit-based team hints are wrong often enough that they are only ever a
  tiebreaker between same-name candidates;
- truncated labels ("Calvert-Le…") must be transcribed verbatim — the
  resolver's prefix stage handles them.
"""

from __future__ import annotations

import base64
import binascii

import anthropic

from api.chat import MODEL, record_usage
from api.data import LiveStore

ALLOWED_MEDIA = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # the API's per-image ceiling
MAX_TOKENS = 2000
SQUAD_SHAPE = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}


class ExtractionError(ValueError):
    """Client-fixable problem with the uploaded image (422, not 500)."""


EXTRACT_TOOL = {
    "name": "record_squad",
    "description": "Record every player visible in the FPL squad screenshot.",
    "input_schema": {
        "type": "object",
        "properties": {
            "view": {"type": "string", "enum": ["pick_team", "transfers", "other"]},
            "players": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "row": {"type": "string", "enum": list(SQUAD_SHAPE)},
                        "is_captain": {"type": "boolean"},
                        "is_vice": {"type": "boolean"},
                        "price": {"type": ["number", "null"]},
                        "team_hint": {"type": ["string", "null"]},
                    },
                    "required": ["name", "row", "is_captain", "is_vice"],
                },
            },
        },
        "required": ["players"],
    },
}

PROMPT = """\
This is a screenshot of a Fantasy Premier League (official FPL app/site) squad — either
the Pick Team view (starting XI on the pitch plus a bench strip at the bottom labelled
with positions) or the Transfers/squad view (all 15 players in four position rows, with
prices above the shirts: 2 GKP, 5 DEF, 5 MID, 3 FWD).

Record every player via the record_squad tool:
- name: the text on the white label under the shirt, copied EXACTLY as rendered — keep
  accents, dots, hyphens and apostrophes; if the name is cut off with an ellipsis (…),
  keep the ellipsis. Do NOT expand truncated names or "correct" spellings. The label's
  second line (e.g. "BRE (A)") is the fixture, never part of the name.
- row: the player's position band — GKP, DEF, MID or FWD. On the pitch the top row is
  the goalkeeper(s), then defenders, then midfielders, then forwards at the bottom.
  Bench players have a position label printed above them (GK means GKP).
- is_captain / is_vice: true only when the shirt carries a small round C or V badge.
  Yellow warning triangles are availability flags — ignore them, they are not badges.
- price: the £X.Xm value above the shirt if shown, as a number (5.5 for £5.5m), else null.
- team_hint: your best guess at the player's club from the shirt design/sponsor, or null
  if unsure. A hint only — guess conservatively.

List players in reading order: pitch rows top-to-bottom, each row left-to-right, then
the bench left-to-right. Record exactly what is visible — if fewer than 15 players are
shown, record only what you see."""


def _decode_image(image_b64: str, media_type: str) -> str:
    """Validate the upload; returns the bare base64 payload."""
    if media_type not in ALLOWED_MEDIA:
        raise ExtractionError(f"unsupported media type {media_type!r} — use JPEG, PNG or WebP")
    if image_b64.startswith("data:"):  # tolerate a full data URL from the client
        image_b64 = image_b64.split(",", 1)[-1]
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ExtractionError("image is not valid base64") from e
    if not raw:
        raise ExtractionError("image is empty")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ExtractionError(
            f"image too large ({len(raw) / 1e6:.1f}MB > {MAX_IMAGE_BYTES / 1e6:.0f}MB) "
            "— downscale before uploading"
        )
    return image_b64


def extract_squad(image_b64: str, media_type: str) -> dict:
    """One vision call: screenshot in, raw transcription out (no resolution)."""
    msg = anthropic.Anthropic().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        tools=[EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "record_squad"},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                },
                {"type": "text", "text": PROMPT},
            ],
        }],
    )
    record_usage(msg.usage)
    block = next((b for b in msg.content if b.type == "tool_use"), None)
    if block is None:
        raise ExtractionError("could not read a squad from this image")
    return dict(block.input)


def _fmt(r: dict) -> dict:
    """A store row shaped for the client (price in tenths, like the parquets)."""
    return {
        "code": int(r["code"]),
        "player": r["player"],
        "web_name": r.get("web_name") or None,
        "team": r["team"],
        "position": r["position"],
        "price": float(r["price"]),
        "xpts": round(float(r["xpts"]), 1),
    }


def extract_and_resolve(store: LiveStore, image_b64: str, media_type: str) -> dict:
    """The full /squad/extract flow: transcribe, resolve, annotate for confirm.

    Never rates and never discards a partial read — ``complete`` tells the
    client whether all 15 resolved uniquely into a legal 2/5/5/3 squad.
    """
    image_b64 = _decode_image(image_b64, media_type)
    extraction = extract_squad(image_b64, media_type)
    entries = extraction.get("players") or []
    if not entries:
        raise ExtractionError(
            "no players found — is this a screenshot of an FPL Pick Team or Transfers view?"
        )

    players, warnings = [], []
    for e in entries:
        res = store.resolver.resolve(e.get("name", ""), e.get("row"), e.get("team_hint"))
        match = res["match"]
        players.append({
            "shown": e.get("name", ""),
            "row": e.get("row"),
            "is_captain": bool(e.get("is_captain")),
            "is_vice": bool(e.get("is_vice")),
            "price_shown": e.get("price"),
            "status": res["status"],
            "method": res["method"],
            "match": _fmt(match) if match else None,
            "candidates": [_fmt(c) for c in res["candidates"]],
            # resolver may have recovered from a mis-read row — surface it
            "row_mismatch": bool(match) and e.get("row") != match["position"],
        })

    resolved = [p["match"] for p in players if p["status"] == "ok"]
    counts = {pos: sum(1 for m in resolved if m["position"] == pos) for pos in SQUAD_SHAPE}
    codes = [m["code"] for m in resolved]
    dupes = sorted({c for c in codes if codes.count(c) > 1})
    if dupes:
        names = ", ".join(m["web_name"] or m["player"] for m in resolved if m["code"] in dupes)
        warnings.append(f"the same player was read more than once: {names}")
    if len(entries) != 15:
        warnings.append(f"expected 15 players, could read {len(entries)} — "
                        "make sure the whole squad (including the bench) is in the shot")
    unresolved = [p["shown"] for p in players if p["status"] != "ok"]
    if unresolved:
        warnings.append("needs confirmation: " + ", ".join(unresolved))

    complete = (
        len(entries) == 15
        and not unresolved
        and not dupes
        and counts == SQUAD_SHAPE
    )
    if not complete and counts != SQUAD_SHAPE and len(entries) == 15 and not unresolved:
        warnings.append(f"squad shape {counts} is not 2 GKP / 5 DEF / 5 MID / 3 FWD")

    return {
        "view": extraction.get("view"),
        "players": players,
        "counts": counts,
        "complete": complete,
        "warnings": warnings,
        "provenance": store.provenance,
    }
