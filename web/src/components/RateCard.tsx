"use client";

/** Squad verdict card: best XI + captain, gap to the optimal squad at the
 * same spend, bench order. Shared by Builder's "Rate my draft" and Compare. */

import { pts, teamAbbrev } from "@/lib/format";
import type { SquadSolution } from "@/lib/types";

export function RateCard({
  result,
  title = "Draft verdict",
  onDismiss,
}: {
  result: SquadSolution;
  title?: string;
  onDismiss?: () => void;
}) {
  const weakest = [...result.starting_xi].sort((a, b) => a.xpts - b.xpts)[0];
  const captain = result.starting_xi.find((p) => p.captain);
  return (
    <div className="border-line bg-chalk rounded-xl border p-4 text-sm">
      <div className="flex items-start justify-between">
        <h3 className="font-chip text-xs font-semibold tracking-wide">{title}</h3>
        {onDismiss && (
          <button onClick={onDismiss} className="text-slate -mt-1 px-1" aria-label="Dismiss">
            ×
          </button>
        )}
      </div>
      <div className="mt-2 space-y-1.5">
        {result.xi_plus_captain_xpts_this_gw != null && (
          <KV
            k={`Best XI + captain, GW${result.provenance.gw_window[0]}`}
            v={`${pts(result.xi_plus_captain_xpts_this_gw)} pts`}
            strong
          />
        )}
        <KV k="XI + captain, whole window" v={`${pts(result.xi_plus_captain_xpts)} pts`} />
        <KV k="Formation" v={result.formation} />
        <KV k="Captain" v={captain ? captain.player : "—"} />
        <KV k="Draft cost" v={result.draft_cost ?? result.cost} />
        {result.gap_to_optimal != null && (
          <KV
            k="Gap to optimal"
            v={
              result.gap_to_optimal <= 0.05
                ? "none — this is the optimal squad"
                : `−${pts(result.gap_to_optimal)} pts vs the best squad at this spend`
            }
          />
        )}
        {weakest && (
          <p className="text-slate border-line mt-2 border-t pt-2 text-xs">
            Weakest starter: <strong className="text-ink">{weakest.player}</strong> (
            {teamAbbrev(weakest.team)}, {pts(weakest.xpts)} pts). Ask Pal for
            alternatives.
          </p>
        )}
      </div>
      <div className="mt-3">
        <h4 className="font-chip text-slate mb-1 text-[10px] tracking-wide">Bench order</h4>
        <ol className="text-slate list-decimal pl-5 text-xs">
          {result.bench_in_order.map((b) => (
            <li key={b.player}>
              {b.player} <span className="font-mono">({pts(b.xpts)})</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

export function KV({ k, v, strong }: { k: string; v: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-slate">{k}</span>
      <span className={`text-right font-mono ${strong ? "font-semibold" : ""}`}>{v}</span>
    </div>
  );
}
