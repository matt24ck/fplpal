/** Shapes mirrored from the FastAPI engine (api/app.py, api/tools.py). */

export interface Provenance {
  season: string;
  gw_window: [number, number];
  data_snapshot: string;
  computed_at: string;
}

export interface Meta {
  provenance: Provenance;
  teams: string[];
  squad_rules: {
    size: number;
    budget: number; // tenths of £m
    positions: Record<string, number>;
    max_per_club: number;
    formation: Record<string, [number, number]>;
  };
  chips: Record<string, { count: number; halves: boolean }>;
  first_half_deadline_gw: number;
  next_deadline: { gw: number; deadline_time: string } | null;
}

export type Position = "GKP" | "DEF" | "MID" | "FWD";

export interface FixtureCell {
  gw: number;
  opponent: string;
  home: boolean;
  difficulty: number; // net expected goals against; 0 = even, positive = harder
}

/** Prior-vs-observed provenance: how much of a projection is observed PL
 * data vs the position × price-tier prior (engine.models.event_rates). */
export type BasisLevel = "pure_prior" | "mostly_prior" | "mixed" | "observed";

export interface DataBasis {
  level: BasisLevel;
  effective_90s: number; // time-decayed 90s of PL observation
  prior_weight?: number; // exact shrinkage blend k/(exposure+k)
  note?: string;
}

export interface ExplorerPlayer {
  code: number;
  player: string;
  web_name?: string | null; // FPL's "known as" name ("Evanilson", not "Barbosa")
  team: string;
  position: Position;
  price: number; // tenths of £m
  xpts: number; // sum over the projection window
  p_play: number;
  rating: number | null;
  sub_scores: Record<string, number | null>;
  gw_xpts: Record<string, number>;
  data_basis: DataBasis;
}

export interface ExplorerData {
  players: ExplorerPlayer[];
  fixtures: Record<string, FixtureCell[]>;
  provenance: Provenance;
}

export interface MatrixCell {
  opponent: string;
  home: boolean;
  expected_goals_for: number;
  expected_goals_against: number;
  clean_sheet_probability: number;
  difficulty: number;
}

export interface MatrixData {
  gws: number[];
  teams: { team: string; cells: MatrixCell[][] }[];
  provenance: Provenance;
}

export interface SolutionPlayer {
  player: string;
  web_name?: string; // FPL's "known as" name, when the engine data carries it
  team: string;
  position: Position;
  price: string; // "£5.5m"
  xpts: number; // over the projection window
  xpts_this_gw?: number; // upcoming GW only
  captain?: boolean;
  vice_captain?: boolean;
}

export interface SquadSolution {
  formation: string; // "3-4-3" = DEF-MID-FWD
  cost: string;
  xi_plus_captain_xpts: number; // over the projection window
  xi_plus_captain_xpts_this_gw?: number; // upcoming GW only
  starting_xi: SolutionPlayer[];
  bench_in_order: SolutionPlayer[];
  provenance: Provenance;
  horizons?: string;
  draft_cost?: string;
  optimal_squad_same_budget_xpts?: number;
  gap_to_optimal?: number;
  errors?: unknown[];
  error?: string;
}

/** Screenshot extraction (POST /squad/extract) — the confirm-step payload.
 * The vision model only transcribes labels; resolution is deterministic and
 * nothing is rated until the user confirms the 15. */
export interface ExtractCandidate {
  code: number;
  player: string;
  web_name?: string | null;
  team: string;
  position: Position;
  price: number; // tenths of £m
  xpts: number;
}

export interface ExtractedPlayer {
  shown: string; // the shirt label as read (may end in a truncation ellipsis)
  row: Position | null;
  is_captain: boolean;
  is_vice: boolean;
  price_shown: number | null; // £m as shown (Transfers view), e.g. 5.5
  status: "ok" | "ambiguous" | "none";
  method: string;
  match: ExtractCandidate | null;
  candidates: ExtractCandidate[];
  row_mismatch: boolean; // resolver recovered from a mis-read pitch row
}

export interface SquadExtraction {
  view: "pick_team" | "transfers" | "other" | null;
  players: ExtractedPlayer[];
  counts: Record<Position, number>;
  complete: boolean; // all 15 resolved uniquely into a legal 2/5/5/3
  warnings: string[];
  provenance: Provenance;
}

/** Squad comparison (POST /squad/compare). */
export interface PlayerBrief {
  code: number;
  player: string;
  web_name?: string;
  team: string;
  position: Position;
  price: string; // "£5.5m"
  xpts: number;
}

export interface ComparedSquad extends SquadSolution {
  label: string;
  captain: SolutionPlayer | null;
}

export interface SquadComparison {
  squads: ComparedSquad[];
  verdict: { best: string; margin_xpts: number };
  shared: PlayerBrief[]; // in every squad, sorted by -xpts
  differentials: Record<string, PlayerBrief[]>; // only in that squad
  provenance: Provenance;
}

export interface GwProjection {
  gw: number;
  opponent: string;
  home: boolean;
  xpts: number;
  ceiling: number;
  breakdown: Record<string, number>;
}

export interface PlayerProjection {
  player: string;
  team: string;
  position: Position;
  total_xpts: number;
  per_gw: GwProjection[];
}

export interface ProjectionsResponse {
  projections: PlayerProjection[];
  errors: unknown[];
  provenance: Provenance;
}

export interface RatingExplain {
  player: string;
  position: Position;
  rating: number;
  sub_scores: Record<string, number | null>;
  data_basis?: DataBasis;
  note: string;
  strongest: string;
  weakest: string;
  provenance: Provenance;
}

/** Multi-GW transfer plan (POST /transfers/plan). */
export interface TransferMove {
  out: string;
  out_sell_price: string;
  in: string;
  in_price: string;
}

export interface PlanWeek {
  gw: number;
  action: "hold" | "transfer";
  moves: TransferMove[];
  hit_cost?: number;
  free_transfers_after: number;
  bank_after: string;
  xi_xpts: number;
}

export interface TransferPlan {
  horizon_gws: [number, number];
  expected_pts_with_plan: number;
  expected_pts_holding: number;
  expected_gain: number;
  this_week: { action: "hold" | "transfer"; moves: TransferMove[]; hit_cost?: number };
  steps: PlanWeek[];
  alternatives?: {
    label: string;
    this_week: { action: "hold" | "transfer"; moves: TransferMove[]; hit_cost?: number };
    expected_pts_over_horizon: number;
    delta_vs_plan: number;
  }[];
  note?: string;
  provenance: Provenance;
  error?: string;
  errors?: unknown[];
}

/** Chip advisor (POST /chips/advise). */
export interface ChipAdviceEntry {
  label: string;
  best_gw: number | null;
  expected_gain: number | null;
  detail: string | null;
  assessment: string;
  weeks: { gw: number; ev: number }[];
}

export interface ChipAdviceResponse {
  horizon_gws: [number, number];
  chips: Record<string, ChipAdviceEntry>;
  note?: string;
  provenance: Provenance;
  error?: string;
  errors?: unknown[];
}

/** Real team import (GET /team/{id}) — live FPL entry state. */
export interface TeamPlayer {
  element: number;
  code: number;
  player: string;
  web_name?: string | null; // FPL's "known as" name
  position: Position;
  team: string;
  current_price: number; // tenths of £m
  purchase_price: number;
  selling_price: number;
  squad_position: number | null; // 1-11 XI, 12-15 bench, from the last picks
  is_captain: boolean;
  is_vice_captain: boolean;
}

export interface TeamState {
  status: "ok" | "pending";
  team_id: number;
  team_name?: string;
  manager?: string;
  gw?: number;
  overall_points?: number | null;
  overall_rank?: number | null;
  last_gw_points?: number | null;
  squad?: TeamPlayer[];
  bank?: number; // tenths
  team_value?: number; // tenths
  free_transfers?: number;
  active_chip?: string | null;
  chips_played?: { name: string; event: number }[];
  chips_available?: string[];
  approx_purchase_prices?: boolean;
  pending_transfers?: number;
  fetched_at?: string;
  note?: string;
  warnings?: string[];
}

/** Live accuracy report (GET /accuracy) — the credibility surface. Frozen
 * at each GW deadline, scored once the GW is finished and data-checked. */
export interface AccuracyMetrics {
  rmse: number | null;
  mae: number | null;
  rank_corr: number | null; // within-position Spearman, players who played
  top10_overlap: number | null;
}

export interface AccuracyCaptainPick {
  player: string;
  points: number; // realized points of that pick
}

export interface AccuracyGwEntry {
  gw: number;
  deadline_time: string;
  frozen_at: string;
  data_snapshot: string;
  fixtures_frozen: number;
  fixtures_scored: number; // < frozen when fixtures were postponed out
  players: number;
  played: number;
  model: AccuracyMetrics;
  ep_next: AccuracyMetrics; // FPL's own projection, frozen at the deadline
  form4: AccuracyMetrics; // naive last-4-fixture form baseline
  captain: {
    model: AccuracyCaptainPick | null;
    ep_next: AccuracyCaptainPick | null;
    hindsight: AccuracyCaptainPick | null;
  };
  xpts_total_ratio: number | null; // >1 = projected more than reality paid
  cs_brier: number | null;
  start_brier: number | null;
}

export interface AccuracyPending {
  gw: number;
  deadline_time: string;
  frozen_at: string;
  players: number;
  fixtures: number;
}

export interface AccuracyAggregate {
  gws_scored: number;
  model: AccuracyMetrics;
  ep_next: AccuracyMetrics;
  beat_ep_next_rank_corr: { gws: number; of: number };
  captain_pts_per_gw: {
    model: number | null;
    ep_next: number | null;
    hindsight: number | null;
  };
  cs_brier: number | null;
  xpts_total_ratio: number | null;
}

export interface AccuracyData {
  available: boolean;
  season: string;
  scored_at?: string;
  gws: AccuracyGwEntry[];
  pending: AccuracyPending[];
  aggregate: AccuracyAggregate | null;
}

/** Player-level rows for one scored GW (GET /accuracy/{gw}). */
export interface AccuracyPlayerRow {
  code: number;
  player: string;
  team: string;
  position: Position;
  price: number; // tenths of £m
  n_fixtures: number;
  xpts: number | null;
  total_points: number;
  minutes: number;
  ep_next: number | null;
  form4: number | null;
}

export interface AccuracyGwDetail {
  gw: number;
  players: AccuracyPlayerRow[];
}

/** Chat stream events (api/chat.py SSE). */
export type ChatEvent =
  | { event: "text"; data: { delta: string } }
  | { event: "tool_use"; data: { id: string; name: string; input: Record<string, unknown> } }
  | { event: "tool_result"; data: { tool_use_id: string; result: unknown } }
  | { event: "done"; data: Record<string, never> }
  | { event: "error"; data: { message: string } };

export type ChatPart =
  | { type: "text"; text: string }
  | {
      type: "tool";
      id: string;
      name: string;
      input: Record<string, unknown>;
      result?: unknown;
    };

export interface ChatMessage {
  role: "user" | "assistant";
  parts: ChatPart[];
  error?: string;
}
