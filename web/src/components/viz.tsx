"use client";

/** Small data-viz primitives. Colors come from the validated decomposition
 * palette and difficulty ramp in globals.css — number + color everywhere,
 * never color alone (dataviz rules). */

import { useId } from "react";
import {
  DECOMP_COLORS,
  DECOMP_LABELS,
  DECOMP_ORDER,
  SUBSCORE_LABELS,
  diffBand,
  diffBg,
  diffFg,
  pts,
  teamAbbrev,
} from "@/lib/format";
import type { FixtureCell, GwProjection } from "@/lib/types";

export function RatingDial({ rating, size = 72 }: { rating: number | null; size?: number }) {
  const r = 30;
  const c = 2 * Math.PI * r;
  const frac = rating == null ? 0 : Math.max(0, Math.min(1, rating / 100));
  const id = useId().replace(/[^a-zA-Z0-9-]/g, "");
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg viewBox="0 0 72 72" width={size} height={size} role="img" aria-label={`Rating ${rating ?? "not rated"}`}>
        <defs>
          <linearGradient id={`dial-${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--color-neon-deep)" />
            <stop offset="100%" stopColor="var(--color-cyan)" />
          </linearGradient>
        </defs>
        <circle cx="36" cy="36" r={r} fill="none" stroke="var(--color-paper-2)" strokeWidth="6" />
        <circle
          cx="36"
          cy="36"
          r={r}
          fill="none"
          stroke={`url(#dial-${id})`}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={`${frac * c} ${c}`}
          transform="rotate(-90 36 36)"
        />
      </svg>
      <span className="font-hero absolute inset-0 flex items-center justify-center text-xl">
        {rating ?? "—"}
      </span>
    </div>
  );
}

export function SubScoreBars({
  subScores,
  order,
}: {
  subScores: Record<string, number | null>;
  order: string[];
}) {
  return (
    <div className="space-y-1.5">
      {order.map((name) => {
        const v = subScores[name];
        return (
          <div key={name} className="flex items-center gap-2 text-xs">
            <span className="text-slate w-24 shrink-0">{SUBSCORE_LABELS[name] ?? name}</span>
            <div className="bg-paper-2 h-2 flex-1 rounded-full" role="presentation">
              <div
                className="h-2 rounded-full"
                style={{
                  width: `${v ?? 0}%`,
                  background:
                    "linear-gradient(90deg, var(--color-neon-deep), var(--color-cyan))",
                }}
              />
            </div>
            <span className="w-7 text-right font-mono">{v ?? "—"}</span>
          </div>
        );
      })}
      <p className="text-slate pt-1 text-[10px]">
        Percentiles within position over the projection window.
      </p>
    </div>
  );
}

/** Stacked xPts decomposition per GW. Category stack order is the
 * CVD-validated adjacency chain; 2px surface gaps between segments;
 * negatives below the baseline. */
export function DecompositionChart({ perGw }: { perGw: GwProjection[] }) {
  const H = 110;
  const NEG_H = 22;
  const posTotal = (g: GwProjection) =>
    Object.entries(g.breakdown).reduce((s, [, v]) => s + Math.max(0, v), 0);
  // ×1.15 leaves headroom for the 2px inter-segment gaps so the tallest
  // column never collides with its total label
  const scale = Math.max(1, ...perGw.map(posTotal)) * 1.15;
  const negScale = Math.max(
    0.5,
    ...perGw.map((g) =>
      Object.entries(g.breakdown).reduce((s, [, v]) => s + Math.max(0, -v), 0),
    ),
  );
  const present = new Set<string>();
  for (const g of perGw)
    for (const [k, v] of Object.entries(g.breakdown)) if (Math.abs(v) >= 0.02) present.add(k);

  return (
    <div>
      <div className="flex items-end gap-1.5" role="img" aria-label="Expected points by source per gameweek">
        {perGw.map((g) => {
          const positives = DECOMP_ORDER.filter(
            (k) => (g.breakdown[k] ?? 0) >= 0.02,
          );
          const negatives = Object.entries(g.breakdown)
            .filter(([, v]) => v <= -0.02)
            .map(([k, v]) => [k, -v] as const);
          return (
            <div key={g.gw} className="flex min-w-0 flex-1 flex-col items-stretch">
              <span className="mb-0.5 text-center font-mono text-[10px] font-semibold">
                {pts(g.xpts)}
              </span>
              <div className="flex flex-col justify-end" style={{ height: H }}>
                <div className="flex flex-col-reverse gap-[2px]">
                  {positives.map((k) => (
                    <div
                      key={k}
                      className="w-full rounded-[2px]"
                      style={{
                        height: Math.max(2, ((g.breakdown[k] ?? 0) / scale) * H),
                        background: DECOMP_COLORS[k],
                      }}
                      title={`${DECOMP_LABELS[k]}: ${pts(g.breakdown[k], 2)} pts`}
                    />
                  ))}
                </div>
              </div>
              <div style={{ height: NEG_H }} className="border-line border-t">
                <div className="flex flex-col gap-[2px] pt-[2px]">
                  {negatives.map(([k, v]) => (
                    <div
                      key={k}
                      className="w-full rounded-[2px] opacity-80"
                      style={{ height: Math.max(2, (v / negScale) * (NEG_H - 4)), background: DECOMP_COLORS[k] }}
                      title={`${DECOMP_LABELS[k]}: −${pts(v, 2)} pts`}
                    />
                  ))}
                </div>
              </div>
              <span className="text-slate mt-0.5 truncate text-center text-[9px]">
                GW{g.gw}
              </span>
              <span className="text-slate truncate text-center text-[9px]">
                {g.home ? "" : "@"}
                {teamAbbrev(g.opponent)}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
        {[...DECOMP_ORDER, "cards", "goals_conceded"]
          .filter((k) => present.has(k))
          .map((k) => (
            <span key={k} className="text-slate flex items-center gap-1 text-[10px]">
              <span
                className="inline-block h-2.5 w-2.5 rounded-[2px]"
                style={{ background: DECOMP_COLORS[k] }}
              />
              {DECOMP_LABELS[k]}
            </span>
          ))}
      </div>
    </div>
  );
}

/** Difficulty ticker cell: opponent + band number on the ramp color. */
export function FixtureTickerStrip({ fixtures, n = 6 }: { fixtures: FixtureCell[]; n?: number }) {
  return (
    <div className="flex gap-0.5">
      {fixtures.slice(0, n).map((f, i) => (
        <span
          key={i}
          className="flex w-8 flex-col items-center rounded-[3px] py-0.5 leading-tight"
          style={{ background: diffBg(f.difficulty), color: diffFg(f.difficulty) }}
          title={`GW${f.gw}: ${f.home ? "home vs" : "away at"} ${f.opponent} · model difficulty ${f.difficulty > 0 ? "+" : ""}${f.difficulty.toFixed(2)}`}
        >
          <span className="font-chip text-[8px]">
            {teamAbbrev(f.opponent)}
            {f.home ? "" : "*"}
          </span>
          <span className="font-mono text-[9px] font-semibold">{diffBand(f.difficulty)}</span>
        </span>
      ))}
    </div>
  );
}
