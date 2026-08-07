"use client";

/** My Team — home. With a saved team ID and picks public (post-GW1), the
 * real imported squad is the board: FPL's XI, captain, and bench order,
 * bank/value/FT state, and real chip usage. Otherwise the draft flow:
 * the draft on the board with overlays, or onboarding. */

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AskPalBar, useAskPal } from "@/components/AskPal";
import { ChipsCard } from "@/components/ChipsCard";
import { PageShell, Segmented } from "@/components/PageShell";
import { PitchView, type ChipData, type Slot } from "@/components/PitchView";
import { PlayerDrawer } from "@/components/PlayerDrawer";
import { PalMark, SparkIcon } from "@/components/Shell";
import { countdown, formatDeadline, pts } from "@/lib/format";
import {
  useDraftLineup,
  useDraftSquad,
  useExplorer,
  useMeta,
  useTeamState,
} from "@/lib/hooks";
import { useApp } from "@/lib/store";
import type { ExplorerPlayer, Position, TeamState } from "@/lib/types";

type Overlay = "xpts" | "fixtures";
type Horizon = "next" | "window";

/** The minimal lineup shape the board renders — the MILP solution and the
 * imported real team both produce it. */
type BoardPlayer = {
  player: string;
  position: Position;
  captain?: boolean;
  vice_captain?: boolean;
};
type BoardLineup = {
  formation: string;
  xi_plus_captain_xpts?: number; // over the projection window
  xi_plus_captain_xpts_this_gw?: number; // upcoming GW only
  starting_xi: BoardPlayer[];
  bench_in_order: BoardPlayer[];
};

/** The imported team as a board lineup: FPL's own XI/captain/bench order,
 * projected with the engine's per-GW xPts. */
function realLineup(
  state: TeamState,
  byName: Map<string, ExplorerPlayer>,
  firstGw: number | undefined,
): BoardLineup {
  const squad = state.squad ?? [];
  const pos = (p: { squad_position: number | null }) => p.squad_position ?? 99;
  const xi = squad.filter((p) => pos(p) <= 11);
  const bench = squad.filter((p) => pos(p) > 11).sort((a, b) => pos(a) - pos(b));
  const gwXp = (name: string) =>
    firstGw != null ? (byName.get(name)?.gw_xpts[String(firstGw)] ?? 0) : 0;
  const toBoard = (p: (typeof squad)[number]): BoardPlayer => ({
    player: p.player,
    position: p.position,
    captain: p.is_captain || undefined,
    vice_captain: p.is_vice_captain || undefined,
  });
  const counts = { DEF: 0, MID: 0, FWD: 0 } as Record<string, number>;
  for (const p of xi) if (p.position !== "GKP") counts[p.position] += 1;
  const base = xi.reduce((s, p) => s + gwXp(p.player), 0);
  const capExtra = xi.filter((p) => p.is_captain).reduce((s, p) => s + gwXp(p.player), 0);
  return {
    formation: `${counts.DEF}-${counts.MID}-${counts.FWD}`,
    xi_plus_captain_xpts_this_gw: Math.round((base + capExtra) * 10) / 10,
    starting_xi: xi.map(toBoard),
    bench_in_order: bench.map(toBoard),
  };
}

export default function MyTeamPage() {
  const { teamId } = useApp();
  const team = useTeamState(teamId);
  const real = team.data?.status === "ok" ? team.data : null;
  const { names, complete, ready, players } = useDraftSquad();
  const lineup = useDraftLineup(names, complete && !real);
  const { data: explorer } = useExplorer();
  const { data: meta } = useMeta();
  const [overlay, setOverlay] = useState<Overlay>("xpts");
  const [horizon, setHorizon] = useState<Horizon>("next");
  const [selected, setSelected] = useState<ExplorerPlayer | null>(null);

  const byName = useMemo(
    () => new Map((explorer?.players ?? []).map((p) => [p.player, p])),
    [explorer],
  );
  const firstGw = meta?.provenance.gw_window[0];

  if (!ready || (teamId && team.isLoading))
    return <PageShell title="My Team">Loading the board…</PageShell>;
  if (!real && !complete)
    return (
      <PageShell title="My Team">
        <Onboarding
          drafted={players.length}
          teamPending={team.data?.status === "pending"}
          teamError={team.error ? String((team.error as Error).message) : null}
        />
      </PageShell>
    );

  const sol: BoardLineup | undefined = real
    ? realLineup(real, byName, firstGw)
    : lineup.data;
  // The XI is picked for the upcoming GW, so the headline is that GW's points
  // (older payloads only carry the window figure).
  const projected = sol?.xi_plus_captain_xpts_this_gw ?? sol?.xi_plus_captain_xpts;
  const squadNames = real ? (real.squad ?? []).map((p) => p.player) : names;
  const toChip = (sp: {
    player: string;
    position: Position;
    captain?: boolean;
    vice_captain?: boolean;
  }): ChipData => {
    const p = byName.get(sp.player);
    const nextGwXpts = p && firstGw != null ? p.gw_xpts[String(firstGw)] : undefined;
    return {
      code: p?.code,
      player: sp.player,
      team: p?.team ?? "",
      position: sp.position,
      price: p?.price,
      captain: sp.captain,
      vice: sp.vice_captain,
      flag: p ? (p.p_play < 0.05 ? "out" : p.p_play < 0.55 ? "doubt" : null) : null,
      ...(overlay === "fixtures"
        ? { fixtures: p ? (explorer?.fixtures[p.team] ?? []) : [] }
        : {
            primary: pts(horizon === "next" ? nextGwXpts : p?.xpts),
          }),
    };
  };

  const rows: Slot[][] = sol
    ? (["GKP", "DEF", "MID", "FWD"] as Position[]).map((pos) =>
        sol.starting_xi
          .filter((p) => p.position === pos)
          .map((p) => ({ chip: toChip(p), position: pos })),
      )
    : [];
  const bench: ChipData[] = sol ? sol.bench_in_order.map(toChip) : [];
  const flagged = sol
    ? sol.starting_xi.filter((p) => {
        const e = byName.get(p.player);
        return e && e.p_play < 0.55;
      })
    : [];

  return (
    <PageShell
      title="My Team"
      right={
        !real ? (
          <Link href="/builder" className="text-royal text-sm font-medium hover:underline">
            Edit draft →
          </Link>
        ) : undefined
      }
    >
      {/* Pal is a tab away on mobile — put the question box in reach */}
      <div className="mb-4 lg:hidden">
        <AskPalBar className="border-line border shadow-sm" />
      </div>

      {real && (
        <p className="text-slate mb-3 text-sm">
          <span className="text-ink font-medium">{real.team_name}</span> ·{" "}
          {real.manager} · imported from FPL after GW{real.gw}
          {real.overall_rank != null && (
            <>
              {" "}
              · rank <span className="font-mono">{real.overall_rank.toLocaleString()}</span>
            </>
          )}
          {real.note && <span className="text-slate/80 block text-xs">{real.note}</span>}
          {real.warnings?.map((w) => (
            <span key={w} className="text-card-yellow block text-xs">
              ⚠ {w}
            </span>
          ))}
        </p>
      )}

      <div className="flex flex-col gap-6 xl:flex-row">
        <div className="min-w-0 flex-1">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Segmented
              value={overlay}
              onChange={(v) => setOverlay(v as Overlay)}
              options={[
                { value: "xpts", label: "xPts" },
                { value: "fixtures", label: "Fixtures" },
              ]}
              label="Overlay"
            />
            {overlay === "xpts" && (
              <Segmented
                value={horizon}
                onChange={(v) => setHorizon(v as Horizon)}
                options={[
                  { value: "next", label: `GW${firstGw ?? "…"}` },
                  { value: "window", label: "Next 6" },
                ]}
                label="Horizon"
              />
            )}
            {sol && (
              <span className="text-slate ml-auto font-mono text-sm">
                XI + captain, GW{firstGw ?? "…"}:{" "}
                <strong className="text-ink">{pts(projected)} pts</strong>
              </span>
            )}
          </div>

          {!real && lineup.isLoading && (
            <p className="text-slate text-sm">Picking your best XI…</p>
          )}
          {sol && (
            <PitchView
              rows={rows}
              bench={bench}
              onSlotClick={(slot) => {
                const p = slot.chip?.code != null ? byName.get(slot.chip.player) : null;
                if (p) setSelected(p);
              }}
            />
          )}
        </div>

        <div className="w-full space-y-4 xl:w-72">
          <ThisWeek
            projected={projected}
            captain={sol?.starting_xi.find((p) => p.captain)?.player}
            formation={sol?.formation}
            flagged={flagged.map((f) => f.player)}
            names={squadNames}
            real={real}
          />
          <ChipsCard state={real} />
          {/* desktop finds About in the masthead nav; mobile gets it here */}
          <Link
            href="/about"
            className="border-line bg-chalk flex items-center gap-2.5 rounded-xl border p-3.5 text-sm lg:hidden"
          >
            <PalMark className="h-6 w-6 shrink-0" />
            <span className="text-slate min-w-0">
              <span className="text-ink font-medium">How FPL Pal works</span> — the
              engine computes, Pal explains.
            </span>
            <span className="text-royal ml-auto shrink-0">→</span>
          </Link>
        </div>
      </div>

      <PlayerDrawer player={selected} onClose={() => setSelected(null)} />
    </PageShell>
  );
}

function ThisWeek({
  projected,
  captain,
  formation,
  flagged,
  names,
  real,
}: {
  projected?: number;
  captain?: string;
  formation?: string;
  flagged: string[];
  names: string[];
  real?: TeamState | null;
}) {
  const { data: meta } = useMeta();
  const ask = useAskPal();
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(t);
  }, []);
  const dl = meta?.next_deadline;

  return (
    <div className="border-line bg-chalk rounded-xl border p-4">
      <h3 className="font-chip text-slate mb-2 text-xs font-semibold tracking-wide">
        This week
      </h3>
      <dl className="space-y-1.5 text-sm">
        {dl && (
          <Row label={`GW${dl.gw} deadline`}>
            {formatDeadline(dl.deadline_time)}
            {now && (
              <span className="text-hot ml-1 font-mono text-xs font-semibold">
                {countdown(dl.deadline_time, now)}
              </span>
            )}
          </Row>
        )}
        <Row label="Projected">
          <span className="font-mono font-semibold">{pts(projected)} pts</span>
        </Row>
        <Row label="Captain">{captain ?? "—"}</Row>
        <Row label="Formation">{formation ?? "—"}</Row>
        {real && (
          <>
            <Row label="Bank">
              <span className="font-mono">£{((real.bank ?? 0) / 10).toFixed(1)}m</span>
            </Row>
            <Row label="Team value">
              <span className="font-mono">£{((real.team_value ?? 0) / 10).toFixed(1)}m</span>
            </Row>
            <Row label="Free transfers">
              <span className="font-mono">{real.free_transfers}</span>
            </Row>
            {real.last_gw_points != null && (
              <Row label={`GW${real.gw} points`}>
                <span className="font-mono">{real.last_gw_points}</span>
              </Row>
            )}
          </>
        )}
        <Row label="Flags">
          {flagged.length === 0 ? (
            "none"
          ) : (
            <span className="text-card-yellow font-medium">
              ⚠ {flagged.join(", ")}
            </span>
          )}
        </Row>
      </dl>
      <button
        onClick={() =>
          ask(
            real
              ? `Review my FPL team (ID ${real.team_id}) and its weak spots`
              : `Review my draft and its weak spots: ${names.join(", ")}`,
          )
        }
        className="border-line hover:border-royal hover:text-royal mt-3 flex w-full items-center justify-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium"
      >
        <SparkIcon className="h-3 w-3" />
        Ask Pal to review this team
      </button>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-slate shrink-0">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}

function Onboarding({
  drafted,
  teamPending,
  teamError,
}: {
  drafted: number;
  teamPending?: boolean;
  teamError?: string | null;
}) {
  const { teamId, setTeamId } = useApp();
  const [idInput, setIdInput] = useState("");

  return (
    <div className="mx-auto max-w-3xl">
      {/* the handshake: Pal, front and center */}
      <section className="masthead text-chalk rounded-2xl px-6 py-8 sm:px-10 sm:py-12">
        <p className="font-chip text-neon text-xs font-bold tracking-wider">
          2026/27 · Pre-season
        </p>
        <h2 className="font-hero mt-2 text-3xl leading-tight sm:text-5xl">
          Draft it like an analyst.
        </h2>
        <p className="text-chalk/75 mt-3 max-w-lg leading-relaxed">
          Projections, ratings, and optimal squads — computed by a statistical
          engine, explained by Pal. It never invents a number.{" "}
          <Link href="/about" className="text-neon font-medium hover:underline">
            How it works →
          </Link>
        </p>
        <AskPalBar className="mt-6 max-w-xl" />
      </section>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <div className="border-line bg-chalk rounded-xl border p-5">
          <h3 className="font-chip text-sm font-semibold tracking-wide">Draft your squad</h3>
          <p className="text-slate mt-1 text-sm">
            {drafted > 0
              ? `You've picked ${drafted}/15 — carry on.`
              : "Build a £100m squad on the board, or let the optimizer solve it."}
          </p>
          <Link
            href="/builder"
            className="btn-primary mt-4 inline-block rounded-full px-4 py-2 text-sm"
          >
            {drafted > 0 ? "Continue draft" : "Open the Squad Builder"}
          </Link>
        </div>

        <div className="border-line bg-chalk rounded-xl border p-5">
          <h3 className="font-chip text-sm font-semibold tracking-wide">Have an FPL team?</h3>
          <p className="text-slate mt-1 text-sm">
            Save your team ID now — squad import opens after the GW1 deadline
            (FPL only makes picks public then).
          </p>
          {teamId ? (
            <div className="mt-4 text-sm">
              <p>
                Saved: <span className="font-mono">{teamId}</span>{" "}
                <button onClick={() => setTeamId(null)} className="text-royal underline">
                  change
                </button>
              </p>
              {teamPending && (
                <p className="text-neon-deep mt-1.5 text-xs">
                  ✓ ID checked — your squad imports here automatically once FPL
                  makes picks public after the GW1 deadline.
                </p>
              )}
              {teamError && (
                <p className="text-card-red mt-1.5 text-xs">{teamError}</p>
              )}
            </div>
          ) : (
            <form
              className="mt-4 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (idInput.trim()) setTeamId(idInput.trim());
              }}
            >
              <input
                value={idInput}
                onChange={(e) => setIdInput(e.target.value)}
                inputMode="numeric"
                placeholder="Team ID"
                aria-label="FPL team ID"
                className="border-line bg-paper w-32 rounded-full border px-3 py-2 font-mono text-sm"
              />
              <button className="border-line hover:border-royal rounded-full border px-4 py-2 text-sm font-medium">
                Save
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
