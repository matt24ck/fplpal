"""Season rules as versioned, validated configuration.

FPL changes rules most summers (defensive contribution arrived in 2025/26,
banked transfers went to 5 in 2024/25, chips doubled in 2025/26). All rules the
engine depends on live in ``seasons/<season>.json`` and are loaded through the
models here — nothing downstream hardcodes a point value or squad constraint.

Money convention: tenths of £m throughout, matching the API's ``now_cost``
(so ``budget = 1000`` means £100.0m).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Position = Literal["GKP", "DEF", "MID", "FWD"]

# The API's element_type integer -> position short name.
ELEMENT_TYPE_TO_POSITION: dict[int, Position] = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

SEASONS_DIR = Path(__file__).parent / "seasons"


class SquadRules(BaseModel):
    size: int
    budget: int  # tenths of £m
    positions: dict[Position, int]
    max_per_club: int
    formation: dict[Position, tuple[int, int]]  # (min, max) in the starting XI


class TransferRules(BaseModel):
    free_per_gw: int
    max_banked: int
    hit_cost: int


class DefensiveContribution(BaseModel):
    points: int
    threshold: dict[str, int]  # DEF/MID/FWD -> per-match count threshold
    def_counts: str
    mid_fwd_counts: str


class Scoring(BaseModel):
    appearance_short: int
    appearance_60: int
    goal: dict[Position, int]
    assist: int
    clean_sheet: dict[Position, int]
    goals_conceded_per_2: dict[Position, int]
    saves_per_3: int
    penalty_save: int
    penalty_miss: int
    defensive_contribution: DefensiveContribution
    yellow_card: int
    red_card: int
    own_goal: int
    bonus: list[int]  # points for 1st/2nd/3rd in match BPS


class ChipRule(BaseModel):
    count: int
    halves: bool  # one use per half-season (split at first_half_deadline_gw)


class Chips(BaseModel):
    wildcard: ChipRule
    freehit: ChipRule
    bboost: ChipRule
    triple_captain: ChipRule  # the API names this chip "3xc"
    first_half_deadline_gw: int


class SeasonRules(BaseModel):
    season: str
    verified_against_game: bool
    notes: str
    squad: SquadRules
    transfers: TransferRules
    scoring: Scoring
    chips: Chips


@lru_cache
def load_season(season: str = "2026-27") -> SeasonRules:
    path = SEASONS_DIR / f"{season}.json"
    return SeasonRules.model_validate_json(path.read_text(encoding="utf-8"))
