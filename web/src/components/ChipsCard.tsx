"use client";

import { useMeta } from "@/lib/hooks";
import type { TeamState } from "@/lib/types";

const CHIP_LABELS: Record<string, string> = {
  wildcard: "Wildcard",
  freehit: "Free Hit",
  bboost: "Bench Boost",
  triple_captain: "Triple Captain",
};

/** Chip status (UI_PLAN §5). With an imported team, this shows the REAL
 * state — played gameweeks and what's still in hand this half — otherwise
 * the season's allowance. Timing advice lives on the Planner, where the
 * engine prices every chip week on top of the transfer plan. */
export function ChipsCard({ state }: { state?: TeamState | null }) {
  const { data } = useMeta();
  if (!data) return null;
  const played = state?.chips_played ?? null;
  const available = state?.chips_available ?? null;
  return (
    <div className="border-line bg-chalk rounded-xl border p-4">
      <h3 className="font-chip text-slate mb-2 text-xs font-semibold tracking-wide">Chips</h3>
      <ul className="space-y-1.5">
        {Object.entries(data.chips).map(([key, chip]) => {
          const events = played?.filter((c) => c.name === key).map((c) => c.event) ?? [];
          return (
            <li key={key} className="flex items-center justify-between text-sm">
              <span>{CHIP_LABELS[key] ?? key}</span>
              {available ? (
                available.includes(key) ? (
                  <span className="text-slate flex items-center gap-1 font-mono text-xs">
                    <span className="text-neon-deep" aria-hidden>
                      ●
                    </span>
                    available
                    {events.length > 0 && ` · played GW${events.join(", GW")}`}
                  </span>
                ) : (
                  <span className="text-slate font-mono text-xs">
                    {events.length > 0
                      ? `played GW${events.join(", GW")}`
                      : "next half"}
                  </span>
                )
              ) : (
                <span className="text-slate flex items-center gap-1 font-mono text-xs">
                  {Array.from({ length: chip.count }).map((_, i) => (
                    <span key={i} className="text-neon-deep" aria-hidden>
                      ●
                    </span>
                  ))}
                  available
                </span>
              )}
            </li>
          );
        })}
      </ul>
      <p className="text-slate mt-2.5 text-[11px] leading-snug">
        One of each per half-season; the first half ends at GW
        {data.first_half_deadline_gw}. The engine prices every chip week on the
        Planner — expected gain per gameweek, on top of your transfer plan.
      </p>
    </div>
  );
}
