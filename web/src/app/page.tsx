"use client";

/** My Team — home. Pre-season: the draft on the board with overlays, the
 * This Week panel, and chip status. No draft yet → the Ask Pal hero and
 * onboarding. */

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AskPalBar, useAskPal } from "@/components/AskPal";
import { ChipsCard } from "@/components/ChipsCard";
import { PageShell, Segmented } from "@/components/PageShell";
import { PitchView, type ChipData, type Slot } from "@/components/PitchView";
import { PlayerDrawer } from "@/components/PlayerDrawer";
import { PalMark, SparkIcon } from "@/components/Shell";
import { countdown, formatDeadline, pts } from "@/lib/format";
import { useDraftLineup, useDraftSquad, useExplorer, useMeta } from "@/lib/hooks";
import { useApp } from "@/lib/store";
import type { ExplorerPlayer, Position } from "@/lib/types";

type Overlay = "xpts" | "fixtures";
type Horizon = "next" | "window";

export default function MyTeamPage() {
  const { names, complete, ready, players } = useDraftSquad();
  const lineup = useDraftLineup(names, complete);
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

  if (!ready) return <PageShell title="My Team">Loading the board…</PageShell>;
  if (!complete)
    return (
      <PageShell title="My Team">
        <Onboarding drafted={players.length} />
      </PageShell>
    );

  const sol = lineup.data;
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
        <Link href="/builder" className="text-royal text-sm font-medium hover:underline">
          Edit draft →
        </Link>
      }
    >
      {/* Pal is a tab away on mobile — put the question box in reach */}
      <div className="mb-4 lg:hidden">
        <AskPalBar className="border-line border shadow-sm" />
      </div>

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
                XI + captain:{" "}
                <strong className="text-ink">{pts(sol.xi_plus_captain_xpts)} pts</strong>
              </span>
            )}
          </div>

          {lineup.isLoading && <p className="text-slate text-sm">Picking your best XI…</p>}
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
            projected={sol?.xi_plus_captain_xpts}
            captain={sol?.starting_xi.find((p) => p.captain)?.player}
            formation={sol?.formation}
            flagged={flagged.map((f) => f.player)}
            names={names}
          />
          <ChipsCard />
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
}: {
  projected?: number;
  captain?: string;
  formation?: string;
  flagged: string[];
  names: string[];
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
        onClick={() => ask(`Review my draft and its weak spots: ${names.join(", ")}`)}
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

function Onboarding({ drafted }: { drafted: number }) {
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
            <p className="mt-4 text-sm">
              Saved: <span className="font-mono">{teamId}</span>{" "}
              <button onClick={() => setTeamId(null)} className="text-royal underline">
                change
              </button>
            </p>
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
