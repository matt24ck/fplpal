"use client";

/** Planner — the multi-GW transfer plan, solved by the engine's MILP over
 * the projection window. With an imported team (saved ID, post-GW1) it
 * plans from the REAL squad, bank, free transfers, and sell prices; before
 * that it runs as an honestly-labeled preview on the draft. */

import Link from "next/link";
import { useAuth, useClerk } from "@clerk/nextjs";
import { useMutation } from "@tanstack/react-query";
import { ChipsCard } from "@/components/ChipsCard";
import { PageShell } from "@/components/PageShell";
import { api } from "@/lib/api";
import { pts } from "@/lib/format";
import { useDraftSquad, useMeta, useTeamState } from "@/lib/hooks";
import { useApp } from "@/lib/store";
import type {
  ChipAdviceResponse,
  PlanWeek,
  TransferMove,
  TransferPlan,
} from "@/lib/types";

export default function PlannerPage() {
  const { data: meta } = useMeta();
  const { teamId } = useApp();
  const team = useTeamState(teamId);
  const real = team.data?.status === "ok" ? team.data : null;
  const { players, names, complete, ready } = useDraftSquad();
  const { isLoaded: authLoaded, isSignedIn, getToken } = useAuth();
  const clerk = useClerk();

  const budget = meta?.squad_rules.budget ?? 1000;
  const spent = players.reduce((s, p) => s + p.price, 0);
  const bank = Math.max(0, budget - spent) / 10;
  const canPlan = !!real || complete;

  const plan = useMutation({
    mutationFn: async () =>
      api.planTransfers(
        real
          ? { team_id: real.team_id, alternatives: 1 }
          : { players: names, bank, free_transfers: 1, alternatives: 1 },
        (await getToken()) ?? undefined,
      ),
  });

  const chips = useMutation({
    mutationFn: async () =>
      api.adviseChips(
        real
          ? { team_id: real.team_id }
          : { players: names, bank, free_transfers: 1 },
        (await getToken()) ?? undefined,
      ),
  });

  if (!ready || (teamId && team.isLoading))
    return <PageShell title="Planner">Loading the player pool…</PageShell>;

  return (
    <PageShell title="Planner">
      <div className="grid items-start gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {!canPlan ? (
            <div className="border-line bg-chalk rounded-xl border p-5">
              <h3 className="font-chip text-sm font-semibold tracking-wide">
                The planner works from your 15
              </h3>
              <p className="text-slate mt-2 text-sm leading-relaxed">
                Pick a full squad in the Squad Builder first ({players.length}/15 so
                far). The planner then solves transfers over the next{" "}
                {meta?.provenance
                  ? meta.provenance.gw_window[1] - meta.provenance.gw_window[0] + 1
                  : 6}{" "}
                gameweeks in one optimization: which moves, in which week, whether a −4
                hit ever pays, and when banking a free transfer beats using it.
              </p>
              <Link
                href="/builder"
                className="btn-primary mt-4 inline-block rounded-full px-4 py-2 text-sm"
              >
                Open the Squad Builder
              </Link>
            </div>
          ) : (
            <div className="border-line bg-chalk rounded-xl border p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="font-chip text-sm font-semibold tracking-wide">
                    Transfer plan
                  </h3>
                  <p className="text-slate mt-1 text-sm">
                    One MILP over GW{meta?.provenance.gw_window[0]}–
                    {meta?.provenance.gw_window[1]}: moves, timing, hits vs. banking —{" "}
                    {real ? (
                      <>
                        from your imported team{" "}
                        <span className="text-ink">“{real.team_name}”</span> with £
                        {((real.bank ?? 0) / 10).toFixed(1)}m in the bank,{" "}
                        {real.free_transfers} FT, and real sell prices.
                      </>
                    ) : (
                      <>from your draft with £{bank.toFixed(1)}m in the bank.</>
                    )}
                  </p>
                </div>
                <button
                  onClick={() => {
                    if (!isSignedIn) return clerk.openSignIn();
                    plan.mutate();
                  }}
                  disabled={plan.isPending || !authLoaded}
                  className="btn-primary rounded-full px-4 py-2 text-sm disabled:opacity-50"
                >
                  {plan.isPending
                    ? "Solving…"
                    : plan.data
                      ? "Re-plan"
                      : "Plan my transfers"}
                </button>
              </div>
              {plan.isPending && (
                <p className="text-slate mt-3 font-mono text-xs">
                  Solving the multi-week MILP — usually 10–20 seconds…
                </p>
              )}
              {plan.error && (
                <p className="text-card-red mt-3 text-sm">
                  {String((plan.error as Error).message)}
                </p>
              )}
            </div>
          )}

          {plan.data && <PlanResult plan={plan.data} />}

          {canPlan && (
            <div className="border-line bg-chalk rounded-xl border p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="font-chip text-sm font-semibold tracking-wide">
                    Chip timing
                  </h3>
                  <p className="text-slate mt-1 text-sm">
                    Expected gain from playing each chip in every visible week, on top
                    of the transfer plan.
                  </p>
                </div>
                <button
                  onClick={() => {
                    if (!isSignedIn) return clerk.openSignIn();
                    chips.mutate();
                  }}
                  disabled={chips.isPending || !authLoaded}
                  className="border-line hover:border-royal hover:text-royal rounded-full border px-4 py-2 text-sm font-medium disabled:opacity-50"
                >
                  {chips.isPending ? "Pricing chips…" : chips.data ? "Refresh" : "Advise chips"}
                </button>
              </div>
              {chips.error && (
                <p className="text-card-red mt-3 text-sm">
                  {String((chips.error as Error).message)}
                </p>
              )}
              {chips.data && <ChipAdviceResult advice={chips.data} />}
            </div>
          )}
        </div>

        <div className="space-y-4">
          <ChipsCard state={real} />
          {meta?.next_deadline && (
            <div className="border-line bg-chalk rounded-xl border p-4">
              <h3 className="font-chip text-slate mb-1 text-xs font-semibold tracking-wide">
                Next deadline
              </h3>
              <p className="font-mono text-sm">
                GW{meta.next_deadline.gw} ·{" "}
                {new Date(meta.next_deadline.deadline_time).toLocaleString()}
              </p>
            </div>
          )}
        </div>
      </div>
    </PageShell>
  );
}

function PlanResult({ plan }: { plan: TransferPlan }) {
  if (plan.error || plan.errors) {
    return (
      <div className="border-line bg-chalk rounded-xl border p-5">
        <p className="text-card-red text-sm">
          {plan.error ?? "Some players couldn't be resolved — rebuild the draft and retry."}
        </p>
      </div>
    );
  }
  const holdNow = plan.this_week.action === "hold";
  return (
    <>
      {/* verdict */}
      <div className="border-line bg-chalk rounded-xl border p-5">
        <h3 className="font-chip text-slate text-xs font-semibold tracking-wide">
          This week
        </h3>
        <p className="mt-1.5 text-base">
          {holdNow ? (
            <>
              <strong>Hold</strong> — bank the free transfer.
            </>
          ) : (
            <MoveList moves={plan.this_week.moves} hitCost={plan.this_week.hit_cost} />
          )}
        </p>
        <p className="text-slate mt-2 text-sm">
          Full plan:{" "}
          <strong className="text-ink font-mono">
            {pts(plan.expected_pts_with_plan)}
          </strong>{" "}
          expected points over GW{plan.horizon_gws[0]}–{plan.horizon_gws[1]} vs{" "}
          <span className="font-mono">{pts(plan.expected_pts_holding)}</span> never
          transferring —{" "}
          <strong className="text-neon-deep font-mono">
            +{pts(plan.expected_gain)}
          </strong>{" "}
          from planned moves.
        </p>
        {plan.note && (
          <p className="text-slate border-line mt-3 border-t pt-2.5 text-xs leading-snug">
            {plan.note}
          </p>
        )}
      </div>

      {/* week-by-week */}
      <div className="border-line bg-chalk rounded-xl border p-5">
        <h3 className="font-chip text-slate mb-3 text-xs font-semibold tracking-wide">
          Week by week
        </h3>
        <ol className="space-y-2.5">
          {plan.steps.map((s) => (
            <WeekRow key={s.gw} step={s} />
          ))}
        </ol>
      </div>

      {/* alternatives */}
      {plan.alternatives && plan.alternatives.length > 0 && (
        <div className="border-line bg-chalk rounded-xl border p-5">
          <h3 className="font-chip text-slate mb-2 text-xs font-semibold tracking-wide">
            Alternatives considered
          </h3>
          <ul className="space-y-2">
            {plan.alternatives.map((a) => (
              <li key={a.label} className="text-sm">
                <span className="text-ink">{a.label}:</span>{" "}
                {a.this_week.action === "hold" ? (
                  "hold"
                ) : (
                  <MoveList moves={a.this_week.moves} hitCost={a.this_week.hit_cost} inline />
                )}{" "}
                <span className="text-slate font-mono text-xs">
                  ({a.delta_vs_plan >= 0 ? "+" : ""}
                  {pts(a.delta_vs_plan)} pts vs the plan)
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-slate font-mono text-[11px]">
        Computed from data through {plan.provenance.data_snapshot} · projections{" "}
        {plan.provenance.computed_at.slice(0, 16)}
      </p>
    </>
  );
}

function WeekRow({ step }: { step: PlanWeek }) {
  return (
    <li className="border-line flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b pb-2 text-sm last:border-b-0 last:pb-0">
      <span className="font-chip w-12 shrink-0 text-xs font-semibold">GW{step.gw}</span>
      <span className="min-w-0 flex-1">
        {step.action === "hold" ? (
          <span className="text-slate">
            hold — bank the FT ({step.free_transfers_after} after)
          </span>
        ) : (
          <MoveList moves={step.moves} hitCost={step.hit_cost} inline />
        )}
      </span>
      <span className="text-slate shrink-0 font-mono text-xs">
        XI {pts(step.xi_xpts)} · bank {step.bank_after} · {step.free_transfers_after} FT
      </span>
    </li>
  );
}

function ChipAdviceResult({ advice }: { advice: ChipAdviceResponse }) {
  if (advice.error || advice.errors) {
    return (
      <p className="text-card-red mt-3 text-sm">
        {advice.error ?? "Some players couldn't be resolved — rebuild the draft and retry."}
      </p>
    );
  }
  return (
    <div className="mt-4 space-y-3">
      {Object.entries(advice.chips).map(([key, chip]) => {
        const maxEv = Math.max(...chip.weeks.map((w) => w.ev), 0.1);
        return (
          <div key={key} className="border-line border-t pt-3 first:border-t-0 first:pt-0">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
              <span className="text-sm font-semibold">{chip.label}</span>
              <span className="font-mono text-xs">
                best GW{chip.best_gw} · +{pts(chip.expected_gain)} pts
              </span>
            </div>
            <p className="text-slate mt-0.5 text-xs">{chip.assessment}</p>
            {chip.detail && (
              <p className="text-slate mt-0.5 text-xs">{chip.detail}</p>
            )}
            <div className="mt-1.5 flex items-end gap-1" aria-hidden>
              {chip.weeks.map((w) => (
                <div key={w.gw} className="flex-1 text-center">
                  <div
                    className={`mx-auto w-full rounded-sm ${
                      w.gw === chip.best_gw ? "bg-royal" : "bg-line"
                    }`}
                    style={{ height: `${4 + (w.ev / maxEv) * 28}px` }}
                    title={`GW${w.gw}: +${w.ev}`}
                  />
                  <span className="text-slate font-mono text-[10px]">{w.gw}</span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
      {advice.note && (
        <p className="text-slate border-line border-t pt-2.5 text-[11px] leading-snug">
          {advice.note}
        </p>
      )}
      <p className="text-slate font-mono text-[11px]">
        Computed from data through {advice.provenance.data_snapshot}
      </p>
    </div>
  );
}

function MoveList({
  moves,
  hitCost,
  inline,
}: {
  moves: TransferMove[];
  hitCost?: number;
  inline?: boolean;
}) {
  return (
    <span className={inline ? "" : "block"}>
      {moves.map((m, i) => (
        <span key={`${m.out}-${m.in}`} className={inline ? "" : "block"}>
          {inline && i > 0 && "; "}
          <span className="text-slate">{m.out}</span>{" "}
          <span aria-hidden>→</span> <strong>{m.in}</strong>{" "}
          <span className="text-slate font-mono text-xs">
            ({m.out_sell_price} → {m.in_price})
          </span>
        </span>
      ))}
      {hitCost ? (
        <span className="text-card-red ml-1 font-mono text-xs font-semibold">
          {hitCost} hit
        </span>
      ) : null}
    </span>
  );
}
