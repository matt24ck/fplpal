import type { Position } from "./types";

export const price = (tenths: number) => `£${(tenths / 10).toFixed(1)}m`;

export const pts = (x: number | null | undefined, dp = 1) =>
  x == null ? "—" : x.toFixed(dp);

/** Chip-face name: last word, keeping lowercase particles ("van Dijk"). */
export function chipName(full: string): string {
  const parts = full.trim().split(/\s+/);
  if (parts.length === 1) return parts[0];
  const particles = new Set(["van", "de", "der", "den", "di", "da", "dos", "el", "la", "le"]);
  let i = parts.length - 1;
  while (i > 1 && particles.has(parts[i - 1].toLowerCase())) i--;
  return parts.slice(i).join(" ");
}

const TEAM_ABBREV: Record<string, string> = {
  Arsenal: "ARS",
  "Aston Villa": "AVL",
  Bournemouth: "BOU",
  Brentford: "BRE",
  Brighton: "BHA",
  Burnley: "BUR",
  Chelsea: "CHE",
  "Coventry City": "COV",
  "Crystal Palace": "CRY",
  Everton: "EVE",
  Fulham: "FUL",
  "Hull City": "HUL",
  Ipswich: "IPS",
  "Ipswich Town": "IPS",
  Leeds: "LEE",
  "Leeds United": "LEE",
  Leicester: "LEI",
  Liverpool: "LIV",
  "Man City": "MCI",
  "Manchester City": "MCI",
  "Man Utd": "MUN",
  "Manchester United": "MUN",
  Newcastle: "NEW",
  "Newcastle United": "NEW",
  "Nott'm Forest": "NFO",
  "Nottingham Forest": "NFO",
  Southampton: "SOU",
  Spurs: "TOT",
  Tottenham: "TOT",
  Sunderland: "SUN",
  "West Ham": "WHU",
  "West Ham United": "WHU",
  Wolves: "WOL",
  Wolverhampton: "WOL",
};

export const teamAbbrev = (team: string) =>
  TEAM_ABBREV[team] ?? team.replace(/[^A-Za-z]/g, "").slice(0, 3).toUpperCase();

/** Model difficulty (net xG against) → ramp band 1 (easy) … 5 (hard). */
export function diffBand(d: number): 1 | 2 | 3 | 4 | 5 {
  if (d <= -0.8) return 1;
  if (d <= -0.25) return 2;
  if (d < 0.25) return 3;
  if (d < 0.8) return 4;
  return 5;
}

export const diffBg = (d: number) => `var(--color-diff-${diffBand(d)})`;
/** Ink on the light bands, chalk on the dark — WCAG-checked both ways. */
export const diffFg = (d: number) =>
  diffBand(d) <= 1 ? "var(--color-ink)" : "var(--color-chalk)";

export const POSITIONS: Position[] = ["GKP", "DEF", "MID", "FWD"];

/** Mirrors engine.models.ratings.SUBSCORES — which sub-scores each position has. */
export const SUBSCORES: Record<Position, string[]> = {
  GKP: ["clean_sheets", "saves", "bonus", "value", "minutes"],
  DEF: ["clean_sheets", "attacking", "dc_floor", "bonus", "value", "minutes"],
  MID: ["attacking", "involvement", "floor", "explosiveness", "value", "minutes"],
  FWD: ["attacking", "involvement", "floor", "explosiveness", "value", "minutes"],
};

export const SUBSCORE_LABELS: Record<string, string> = {
  clean_sheets: "Clean sheets",
  saves: "Saves",
  attacking: "Attack",
  dc_floor: "DC floor",
  involvement: "Involvement",
  floor: "Floor",
  explosiveness: "Ceiling",
  bonus: "Bonus",
  value: "Value",
  minutes: "Minutes",
};

/** Decomposition categories in canonical stack/legend order (adjacency is
 * CVD-validated in this order — don't reorder casually). Negatives render
 * below the baseline. */
export const DECOMP_ORDER = [
  "appearance",
  "goals",
  "assists",
  "defensive_contribution",
  "clean_sheets",
  "saves",
  "bonus",
  "other",
] as const;

export const DECOMP_NEGATIVE = ["cards", "goals_conceded"] as const;

export const DECOMP_COLORS: Record<string, string> = {
  appearance: "var(--color-viz-appearance)",
  goals: "var(--color-viz-goals)",
  assists: "var(--color-viz-assists)",
  defensive_contribution: "var(--color-viz-dc)",
  clean_sheets: "var(--color-viz-cs)",
  saves: "var(--color-viz-saves)",
  bonus: "var(--color-viz-bonus)",
  other: "var(--color-viz-other)",
  cards: "var(--color-viz-neg)",
  goals_conceded: "var(--color-viz-neg)",
};

export const DECOMP_LABELS: Record<string, string> = {
  appearance: "Appearance",
  goals: "Goals",
  assists: "Assists",
  defensive_contribution: "Def. contribution",
  clean_sheets: "Clean sheets",
  saves: "Saves",
  bonus: "Bonus",
  other: "Other",
  cards: "Cards",
  goals_conceded: "Conceded",
};

export function formatDeadline(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function countdown(iso: string, now: Date): string {
  const ms = new Date(iso).getTime() - now.getTime();
  if (ms <= 0) return "passed";
  const days = Math.floor(ms / 86_400_000);
  const hours = Math.floor((ms % 86_400_000) / 3_600_000);
  const mins = Math.floor((ms % 3_600_000) / 60_000);
  return days > 0 ? `${days}d ${hours}h` : `${hours}h ${mins}m`;
}
