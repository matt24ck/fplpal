"use client";

/** Player drawer: rating dial + sub-score bars, per-GW xPts decomposition,
 * fixture run. Opens over any view; Esc or backdrop closes. */

import { useEffect, useMemo, useRef } from "react";
import Link from "next/link";
import { usePlayerProjection, useExplorer } from "@/lib/hooks";
import { SUBSCORES, price, pts } from "@/lib/format";
import { assignSlugs } from "@/lib/slug";
import type { ExplorerPlayer } from "@/lib/types";
import { BasisBadge } from "./BasisBadge";
import { Shirt } from "./Shirt";
import { DecompositionChart, FixtureTickerStrip, RatingDial, SubScoreBars } from "./viz";

export function PlayerDrawer({
  player,
  onClose,
}: {
  player: ExplorerPlayer | null;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const proj = usePlayerProjection(player ? player.player : null);
  const { data: explorer } = useExplorer();

  useEffect(() => {
    if (!player) return;
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [player, onClose]);

  const profileHref = useMemo(() => {
    if (!player || !explorer) return null;
    const slug = assignSlugs(explorer.players).get(player.code);
    return slug ? `/players/${slug}` : null;
  }, [explorer, player]);

  if (!player) return null;
  const fixtures = explorer?.fixtures[player.team] ?? [];
  const perGw = proj.data?.projections[0]?.per_gw;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={player.player}>
      <button aria-label="Close" className="absolute inset-0 bg-ink/30" onClick={onClose} />
      <div
        ref={panelRef}
        tabIndex={-1}
        className="bg-paper relative flex h-full w-full max-w-md flex-col overflow-y-auto p-5 shadow-2xl outline-none"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <Shirt team={player.team} className="w-12 shrink-0" />
            <div>
              <h2 className="font-hero text-2xl leading-tight">{player.player}</h2>
              <p className="text-slate text-sm">
                {player.team} · {player.position} ·{" "}
                <span className="font-mono">{price(player.price)}</span>
              </p>
              <BasisBadge basis={player.data_basis} className="mt-1.5" />
              {profileHref && (
                <Link href={profileHref} className="text-royal mt-1 inline-block text-xs font-medium">
                  Full profile page →
                </Link>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate hover:text-ink -mt-1 p-2 text-xl leading-none"
            aria-label="Close player details"
          >
            ×
          </button>
        </div>

        <div className="mt-4 flex items-center gap-5">
          <RatingDial rating={player.rating} />
          <div className="grid grid-cols-2 gap-x-5 gap-y-1 text-sm">
            <Stat label="xPts, window" value={pts(player.xpts)} />
            <Stat label="Start likelihood" value={`${Math.round(player.p_play * 100)}%`} />
          </div>
        </div>

        <Section title="Why this rating">
          <SubScoreBars subScores={player.sub_scores} order={SUBSCORES[player.position]} />
        </Section>

        <Section title="Expected points by source">
          {proj.isLoading ? (
            <p className="text-slate text-sm">computing…</p>
          ) : perGw ? (
            <DecompositionChart perGw={perGw} />
          ) : (
            <p className="text-slate text-sm">no projection available</p>
          )}
        </Section>

        <Section title="Fixture run · model difficulty">
          <FixtureTickerStrip fixtures={fixtures} n={6} />
          <p className="text-slate mt-1.5 text-[10px]">
            1 easiest – 5 hardest · * = away
          </p>
        </Section>

        {proj.data && (
          <p className="text-slate border-line mt-auto border-t pt-3 font-mono text-[10px]">
            computed {proj.data.provenance.computed_at.slice(0, 16).replace("T", " ")} · snapshot{" "}
            {proj.data.provenance.data_snapshot}
          </p>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <h3 className="font-chip text-slate mb-2 text-xs font-semibold tracking-wide">{title}</h3>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-slate text-[10px] uppercase tracking-wide">{label}</div>
      <div className="font-mono text-base font-semibold">{value}</div>
    </div>
  );
}
