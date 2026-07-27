"use client";

/** Squad Builder (UI_PLAN §3.2): the pitch in edit mode. Budget and rule
 * validation live at the top; tap a slot to pick; Optimize fills/repairs the
 * draft via the MILP; Rate my draft scores it against the optimal. Illegal
 * states are explained inline, never silently blocked. */

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { PageShell } from "@/components/PageShell";
import { PitchView, type ChipData, type Slot } from "@/components/PitchView";
import { PlayerDrawer } from "@/components/PlayerDrawer";
import { PlayerPicker } from "@/components/PlayerPicker";
import { api } from "@/lib/api";
import { POSITIONS, price, pts, teamAbbrev } from "@/lib/format";
import { useDraftSquad, useExplorer, useMeta } from "@/lib/hooks";
import { useApp } from "@/lib/store";
import type { ExplorerPlayer, Position, SquadSolution } from "@/lib/types";

const SHAPE: Record<Position, number> = { GKP: 2, DEF: 5, MID: 5, FWD: 3 };

export default function BuilderPage() {
  const { byPos, players, names, complete, ready } = useDraftSquad();
  const { data: explorer } = useExplorer();
  const { data: meta } = useMeta();
  const { setDraft, removeFromDraft, addToDraft } = useApp();
  const [picking, setPicking] = useState<Position | null>(null);
  const [selected, setSelected] = useState<ExplorerPlayer | null>(null);
  const [rateResult, setRateResult] = useState<SquadSolution | null>(null);

  const byName = useMemo(
    () => new Map((explorer?.players ?? []).map((p) => [p.player, p])),
    [explorer],
  );

  const optimize = useMutation({
    mutationFn: () =>
      api.optimizeSquad({
        budget: (meta?.squad_rules.budget ?? 1000) / 10,
        locked: names,
      }),
    onSuccess: (sol) => {
      const codes = [...sol.starting_xi, ...sol.bench_in_order]
        .map((p) => byName.get(p.player)?.code)
        .filter((c): c is number => c != null);
      if (codes.length === 15) setDraft(codes);
      setRateResult(null);
    },
  });

  const rate = useMutation({
    mutationFn: () => api.rateDraft(names),
    onSuccess: setRateResult,
  });

  if (!ready) return <PageShell title="Squad Builder">Loading the player pool…</PageShell>;

  const budget = meta?.squad_rules.budget ?? 1000;
  const maxPerClub = meta?.squad_rules.max_per_club ?? 3;
  const spent = players.reduce((s, p) => s + p.price, 0);
  const clubCounts = new Map<string, number>();
  for (const p of players) clubCounts.set(p.team, (clubCounts.get(p.team) ?? 0) + 1);
  const clubViolations = [...clubCounts.entries()].filter(([, n]) => n > maxPerClub);
  const overBudget = spent > budget;

  const problems: string[] = [];
  if (overBudget) problems.push(`£${((spent - budget) / 10).toFixed(1)}m over budget — remove or downgrade someone`);
  for (const [club, n] of clubViolations)
    problems.push(`${n} ${club} players — the limit is ${maxPerClub}, remove ${n - maxPerClub}`);

  const rows: Slot[][] = POSITIONS.map((pos) => {
    const have = byPos[pos];
    return Array.from({ length: SHAPE[pos] }, (_, i) => ({
      chip: have[i] ? toChip(have[i]) : null,
      position: pos,
    }));
  });

  function toChip(p: ExplorerPlayer): ChipData {
    return {
      code: p.code,
      player: p.player,
      team: p.team,
      position: p.position,
      price: p.price,
      primary: pts(p.xpts),
      flag: p.p_play < 0.05 ? "out" : p.p_play < 0.55 ? "doubt" : null,
    };
  }

  return (
    <PageShell title="Squad Builder">
      {/* budget + rules bar */}
      <div className="border-line bg-chalk mb-4 rounded-xl border p-3">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
          <span className="font-mono">
            <strong className={overBudget ? "text-card-red" : ""}>{price(spent)}</strong>
            <span className="text-slate"> / {price(budget)}</span>
          </span>
          <span className="text-slate font-mono text-xs">
            {POSITIONS.map((pos) => `${byPos[pos].length}/${SHAPE[pos]} ${pos}`).join(" · ")}
          </span>
          <span className="ml-auto flex gap-2">
            <button
              onClick={() => optimize.mutate()}
              disabled={optimize.isPending || !explorer}
              className="btn-primary rounded-full px-3.5 py-1.5 text-sm disabled:opacity-50"
            >
              {optimize.isPending
                ? "Solving…"
                : players.length === 0
                  ? "Optimize a squad"
                  : "Optimize around my picks"}
            </button>
            <button
              onClick={() => rate.mutate()}
              disabled={!complete || rate.isPending}
              title={complete ? undefined : "Pick all 15 first (2 GKP / 5 DEF / 5 MID / 3 FWD)"}
              className="border-line hover:border-royal hover:text-royal rounded-full border px-3.5 py-1.5 text-sm font-medium disabled:opacity-50"
            >
              {rate.isPending ? "Rating…" : "Rate my draft"}
            </button>
            {players.length > 0 && (
              <button
                onClick={() => {
                  setDraft([]);
                  setRateResult(null);
                }}
                className="text-slate hover:text-card-red px-2 py-1.5 text-sm"
              >
                Clear
              </button>
            )}
          </span>
        </div>
        {problems.map((p) => (
          <p key={p} className="text-card-red mt-1.5 text-sm">
            {p}
          </p>
        ))}
        {(optimize.error || rate.error) && (
          <p className="text-card-red mt-1.5 text-sm">
            {String(((optimize.error ?? rate.error) as Error).message)}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-6 xl:flex-row">
        <div className="min-w-0 flex-1">
          <PitchView
            rows={rows}
            edit
            onSlotClick={(slot) => {
              if (slot.chip?.code != null) {
                const p = explorer?.players.find((x) => x.code === slot.chip!.code);
                if (p) setSelected(p);
              } else {
                setPicking(slot.position);
              }
            }}
            onRemove={(chip) => {
              if (chip.code != null) removeFromDraft(chip.code);
              setRateResult(null);
            }}
          />
        </div>

        <div className="w-full xl:w-80">
          {rateResult ? (
            <RateCard result={rateResult} onDismiss={() => setRateResult(null)} />
          ) : (
            <div className="border-line bg-chalk rounded-xl border p-4 text-sm">
              <h3 className="font-chip text-slate mb-2 text-xs font-semibold tracking-wide">
                How this works
              </h3>
              <ul className="text-slate list-disc space-y-1.5 pl-4">
                <li>Tap an empty slot to pick a player — sorted by engine rating.</li>
                <li>
                  <strong className="text-ink">Optimize</strong> keeps your picks and solves
                  the rest with the MILP at £{((budget) / 10).toFixed(0)}m.
                </li>
                <li>
                  <strong className="text-ink">Rate my draft</strong> finds your best XI,
                  captain and bench order, and the gap to the optimal squad at the same
                  spend.
                </li>
              </ul>
            </div>
          )}
        </div>
      </div>

      <PlayerPicker
        position={picking}
        onClose={() => setPicking(null)}
        onPick={(p) => {
          addToDraft(p.code);
          setRateResult(null);
        }}
        squad={players}
        maxPerClub={maxPerClub}
        remaining={budget - spent}
      />
      <PlayerDrawer player={selected} onClose={() => setSelected(null)} />
    </PageShell>
  );
}

function RateCard({ result, onDismiss }: { result: SquadSolution; onDismiss: () => void }) {
  const weakest = [...result.starting_xi].sort((a, b) => a.xpts - b.xpts)[0];
  const captain = result.starting_xi.find((p) => p.captain);
  return (
    <div className="border-line bg-chalk rounded-xl border p-4 text-sm">
      <div className="flex items-start justify-between">
        <h3 className="font-chip text-xs font-semibold tracking-wide">Draft verdict</h3>
        <button onClick={onDismiss} className="text-slate -mt-1 px-1" aria-label="Dismiss">
          ×
        </button>
      </div>
      <div className="mt-2 space-y-1.5">
        <KV k="Best XI + captain" v={`${pts(result.xi_plus_captain_xpts)} pts`} strong />
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

function KV({ k, v, strong }: { k: string; v: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-slate">{k}</span>
      <span className={`text-right font-mono ${strong ? "font-semibold" : ""}`}>{v}</span>
    </div>
  );
}
