"use client";

import { useMeta } from "@/lib/hooks";

const CHIP_LABELS: Record<string, string> = {
  wildcard: "Wildcard",
  freehit: "Free Hit",
  bboost: "Bench Boost",
  triple_captain: "Triple Captain",
};

/** Chip status (UI_PLAN §5): state only until the advisor ships — no advice
 * is ever shown that the engine didn't compute. */
export function ChipsCard() {
  const { data } = useMeta();
  if (!data) return null;
  return (
    <div className="border-line bg-chalk rounded-xl border p-4">
      <h3 className="font-chip text-slate mb-2 text-xs font-semibold tracking-wide">Chips</h3>
      <ul className="space-y-1.5">
        {Object.entries(data.chips).map(([key, chip]) => (
          <li key={key} className="flex items-center justify-between text-sm">
            <span>{CHIP_LABELS[key] ?? key}</span>
            <span className="text-slate flex items-center gap-1 font-mono text-xs">
              {Array.from({ length: chip.count }).map((_, i) => (
                <span key={i} className="text-neon-deep" aria-hidden>
                  ●
                </span>
              ))}
              available
            </span>
          </li>
        ))}
      </ul>
      <p className="text-slate mt-2.5 text-[11px] leading-snug">
        One of each per half-season; the first half ends at GW
        {data.first_half_deadline_gw}. Timing advice ships in-season (~GW4), computed
        by the engine.
      </p>
    </div>
  );
}
