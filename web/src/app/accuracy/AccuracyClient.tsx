"use client";

/** Accuracy — the credibility surface (TODO §2: live accuracy monitoring).
 * Projections are frozen at each GW deadline (engine/accuracy.py) and scored
 * once the gameweek is finished and data-checked: the model vs FPL's own
 * expected points vs what actually happened. Pre-season the ledger is honest
 * about being empty — it shows what's already locked and when the first
 * report lands. */

import { useState } from "react";
import { PageShell, Segmented } from "@/components/PageShell";
import { chipName, pts, teamAbbrev } from "@/lib/format";
import { useAccuracy, useAccuracyGw } from "@/lib/hooks";
import type { AccuracyGwEntry, AccuracyPlayerRow, Position } from "@/lib/types";

/** Two-series palette, validated (dataviz six checks) on the chalk surface:
 * the model is always royal, FPL's ep_next always this blue — color follows
 * the entity everywhere on this page. */
const MODEL_COLOR = "var(--color-royal)";
const EP_COLOR = "var(--color-viz-cs)";

/** Deadline in UK time with a pinned locale — this renders during SSR, so it
 * must be deterministic (lib/format's locale-dependent formatDeadline would
 * hydrate-mismatch for any non-en-US visitor). */
const lockTime = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
  }) + " UK";

export default function AccuracyPage() {
  const acc = useAccuracy();
  const data = acc.data;
  const scored = data?.gws ?? [];
  const [gwSel, setGwSel] = useState<number | null>(null);
  const activeGw = gwSel ?? (scored.length ? scored[scored.length - 1].gw : null);

  return (
    <PageShell title="Accuracy">
      <p className="text-slate -mt-3 mb-6 max-w-2xl text-sm leading-relaxed">
        Every gameweek&apos;s projections are frozen at the deadline and scored against what
        actually happened — next to FPL&apos;s own expected points, frozen at the same moment.
        No retro-fitting: once a deadline passes, the frozen file can&apos;t be touched.
      </p>

      {acc.isLoading && <p className="text-slate text-sm">Pulling the ledger…</p>}
      {acc.isError && (
        <p className="text-slate border-line bg-paper-2 rounded-md border p-3 text-sm">
          The engine is offline right now — which is the point: this page would rather show
          you nothing than a made-up track record.
        </p>
      )}

      {data && scored.length === 0 && <PendingLedger data={data} />}

      {data && scored.length > 0 && data.aggregate && (
        <>
          <SeasonTiles agg={data.aggregate} />
          <RankCorrChart gws={scored} />
          <GwTable gws={scored} />
        </>
      )}

      {data && scored.length > 0 && activeGw !== null && (
        <GwDetail
          gws={scored}
          activeGw={activeGw}
          onSelect={setGwSel}
        />
      )}

      {data && <Methodology />}

      {data && (data.scored_at || data.pending.length > 0) && (
        <p className="text-slate border-line mt-8 border-t pt-2 font-mono text-[10px]">
          season {data.season}
          {data.scored_at && ` · scored ${data.scored_at.slice(0, 16).replace("T", " ")}`}
          {data.pending.length > 0 &&
            ` · latest freeze ${data.pending[0].frozen_at.slice(0, 16).replace("T", " ")}`}
        </p>
      )}
    </PageShell>
  );
}

/* ---------------------------------------------------------------- pending */

function PendingLedger({
  data,
}: {
  data: NonNullable<ReturnType<typeof useAccuracy>["data"]>;
}) {
  if (data.pending.length === 0) {
    return (
      <p className="text-slate border-line bg-paper-2 rounded-md border p-3 text-sm">
        Nothing frozen yet — the ledger starts with the next nightly refresh.
      </p>
    );
  }
  const first = data.pending[0];
  return (
    <div className="border-line bg-chalk rounded-xl border p-4">
      <h3 className="font-chip text-slate mb-2 text-xs font-semibold tracking-wide">
        The ledger opens after GW{first.gw}
      </h3>
      <p className="text-sm leading-relaxed">
        GW{first.gw} projections are already being frozen — {first.players} players across{" "}
        {first.fixtures} fixtures, refreshed nightly until the deadline locks them for good.
        Once the gameweek finishes and FPL confirms the points, the first scorecard appears
        here automatically.
      </p>
      <ul className="text-slate mt-3 space-y-1 font-mono text-xs">
        {data.pending.map((p) => (
          <li key={p.gw}>
            GW{p.gw} — locks {lockTime(p.deadline_time)} · {p.players} players ·{" "}
            {p.fixtures} fixtures
          </li>
        ))}
      </ul>
      <p className="text-slate mt-3 text-xs">
        Until then, the <a href="/about" className="text-royal underline">About page</a> carries
        the historical backtest — how this engine scored on three full past seasons.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------ stat tiles */

function Tile({ label, hero, sub }: { label: string; hero: string; sub: string }) {
  return (
    <div className="border-line bg-chalk rounded-xl border p-4">
      <div className="text-slate text-[10px] uppercase tracking-wide">{label}</div>
      <div className="font-hero mt-1 text-2xl">{hero}</div>
      <div className="text-slate mt-1 font-mono text-xs">{sub}</div>
    </div>
  );
}

function SeasonTiles({
  agg,
}: {
  agg: NonNullable<NonNullable<ReturnType<typeof useAccuracy>["data"]>["aggregate"]>;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Tile
        label="Rank quality (Spearman)"
        hero={pts(agg.model.rank_corr, 2)}
        sub={`FPL ep_next ${pts(agg.ep_next.rank_corr, 2)}`}
      />
      <Tile
        label="Beat FPL's projection"
        hero={`${agg.beat_ep_next_rank_corr.gws} of ${agg.beat_ep_next_rank_corr.of}`}
        sub="gameweeks, by rank quality"
      />
      <Tile
        label="Captain call, pts/GW"
        hero={pts(agg.captain_pts_per_gw.model, 1)}
        sub={`hindsight best ${pts(agg.captain_pts_per_gw.hindsight, 1)} · FPL ${pts(
          agg.captain_pts_per_gw.ep_next,
          1,
        )}`}
      />
      <Tile
        label="Points error (RMSE)"
        hero={pts(agg.model.rmse, 2)}
        sub={`FPL ${pts(agg.ep_next.rmse, 2)} · lower is better`}
      />
    </div>
  );
}

/* ------------------------------------------------- per-GW rank-corr bars */

function RankCorrChart({ gws }: { gws: AccuracyGwEntry[] }) {
  const values = gws.flatMap((g) => [g.model.rank_corr ?? 0, g.ep_next.rank_corr ?? 0]);
  const hasNeg = values.some((v) => v < 0);
  const scale = Math.max(0.5, ...values.map(Math.abs));
  const zero = hasNeg ? 30 : 0; // % offset of the zero line when bars go left

  const Bar = ({ v, color }: { v: number | null; color: string }) => {
    const w = v == null ? 0 : (Math.abs(v) / scale) * (100 - zero - 12);
    return (
      <div className="relative h-2.5">
        {hasNeg && (
          <div className="bg-line absolute inset-y-0 w-px" style={{ left: `${zero}%` }} />
        )}
        <div
          className="absolute inset-y-0 rounded-[2px]"
          style={{
            background: color,
            width: `${w}%`,
            left: v != null && v < 0 ? undefined : `${zero}%`,
            right: v != null && v < 0 ? `${100 - zero}%` : undefined,
          }}
        />
        <span
          className="absolute top-1/2 -translate-y-1/2 font-mono text-[10px]"
          style={{ left: `calc(${zero + w}% + 6px)` }}
        >
          {pts(v, 2)}
        </span>
      </div>
    );
  };

  return (
    <div className="border-line bg-chalk mt-4 rounded-xl border p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-chip text-slate text-xs font-semibold tracking-wide">
          Rank quality per gameweek
        </h3>
        <div className="text-slate flex items-center gap-3 text-xs">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: MODEL_COLOR }} />
            FPL Pal
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: EP_COLOR }} />
            FPL ep_next
          </span>
        </div>
      </div>
      <div className="space-y-2.5">
        {gws.map((g) => (
          <div key={g.gw} className="flex items-center gap-3">
            <span className="font-chip w-10 text-xs font-bold">GW{g.gw}</span>
            <div className="flex flex-1 flex-col gap-[3px]">
              <Bar v={g.model.rank_corr} color={MODEL_COLOR} />
              <Bar v={g.ep_next.rank_corr} color={EP_COLOR} />
            </div>
          </div>
        ))}
      </div>
      <p className="text-slate mt-3 text-xs">
        Spearman correlation between projected and realized points among players who played,
        within each position. 1 would be a perfect ordering; typical good weeks live around
        0.3–0.4.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------ per-GW table */

const signedPct = (ratio: number | null) =>
  ratio == null ? "—" : `${ratio >= 1 ? "+" : ""}${((ratio - 1) * 100).toFixed(0)}%`;

function GwTable({ gws }: { gws: AccuracyGwEntry[] }) {
  return (
    <div className="border-line mt-4 overflow-x-auto rounded-lg border">
      <table className="bg-chalk w-full border-collapse text-sm">
        <thead>
          <tr className="border-line text-slate border-b text-left text-xs">
            <th className="px-3 py-2 font-medium">GW</th>
            <th className="px-3 py-2 text-right font-medium">Fixtures</th>
            <th className="px-3 py-2 text-right font-medium">Rank corr</th>
            <th className="px-3 py-2 text-right font-medium">FPL</th>
            <th className="px-3 py-2 text-right font-medium">RMSE</th>
            <th className="px-3 py-2 text-right font-medium">FPL</th>
            <th className="px-3 py-2 font-medium">Captain call</th>
            <th className="px-3 py-2 text-right font-medium">xPts vs actual</th>
          </tr>
        </thead>
        <tbody>
          {gws.map((g) => (
            <tr key={g.gw} className="border-line border-b last:border-0">
              <td className="font-chip px-3 py-1.5 text-xs font-bold">GW{g.gw}</td>
              <td className="px-3 py-1.5 text-right font-mono text-xs">
                {g.fixtures_scored}
                {g.fixtures_scored < g.fixtures_frozen && (
                  <span className="text-hot" title="fixtures postponed out of this GW are excluded">
                    {" "}
                    / {g.fixtures_frozen}
                  </span>
                )}
              </td>
              <td className="px-3 py-1.5 text-right font-mono text-xs font-semibold">
                {pts(g.model.rank_corr, 2)}
              </td>
              <td className="text-slate px-3 py-1.5 text-right font-mono text-xs">
                {pts(g.ep_next.rank_corr, 2)}
              </td>
              <td className="px-3 py-1.5 text-right font-mono text-xs font-semibold">
                {pts(g.model.rmse, 2)}
              </td>
              <td className="text-slate px-3 py-1.5 text-right font-mono text-xs">
                {pts(g.ep_next.rmse, 2)}
              </td>
              <td className="px-3 py-1.5 text-xs">
                {g.captain.model ? (
                  <>
                    {chipName(g.captain.model.player)}{" "}
                    <span className="font-mono font-semibold">{g.captain.model.points}</span>
                    {g.captain.hindsight && (
                      <span className="text-slate font-mono">
                        {" "}
                        · best {g.captain.hindsight.points}
                      </span>
                    )}
                  </>
                ) : (
                  "—"
                )}
              </td>
              <td className="px-3 py-1.5 text-right font-mono text-xs">
                {signedPct(g.xpts_total_ratio)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------- GW detail */

function GwDetail({
  gws,
  activeGw,
  onSelect,
}: {
  gws: AccuracyGwEntry[];
  activeGw: number;
  onSelect: (gw: number) => void;
}) {
  const detail = useAccuracyGw(activeGw);
  const [posFilter, setPosFilter] = useState<string>("ALL");
  const [scope, setScope] = useState<string>("played");

  const all = detail.data?.players ?? [];
  const rows = all.filter(
    (p) =>
      (posFilter === "ALL" || p.position === (posFilter as Position)) &&
      (scope === "everyone" || p.minutes > 0),
  );

  return (
    <section className="mt-7">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-chip text-slate text-xs font-semibold tracking-wide">
          Under the hood, one gameweek at a time
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <div
            role="group"
            aria-label="Gameweek"
            className="border-line bg-paper-2 flex flex-wrap rounded-full border p-0.5"
          >
            {gws.map((g) => (
              <button
                key={g.gw}
                onClick={() => onSelect(g.gw)}
                aria-pressed={g.gw === activeGw}
                className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
                  g.gw === activeGw ? "bg-deep text-chalk shadow-sm" : "text-slate hover:text-ink"
                }`}
              >
                {g.gw}
              </button>
            ))}
          </div>
          <Segmented
            value={posFilter}
            onChange={setPosFilter}
            label="Position filter"
            options={["ALL", "GKP", "DEF", "MID", "FWD"].map((v) => ({
              value: v,
              label: v === "ALL" ? "All" : v,
            }))}
          />
          <Segmented
            value={scope}
            onChange={setScope}
            label="Player scope"
            options={[
              { value: "played", label: "Played" },
              { value: "everyone", label: "Everyone" },
            ]}
          />
        </div>
      </div>

      {detail.isLoading && <p className="text-slate text-sm">Loading the gameweek…</p>}
      {detail.isError && (
        <p className="text-card-red text-sm">{String((detail.error as Error).message)}</p>
      )}

      {rows.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
          <Scatter rows={rows} gw={activeGw} />
          <BeatsAndMisses rows={all.filter((p) => p.minutes > 0)} />
        </div>
      )}
    </section>
  );
}

/* The projected-vs-realized scatter: one dot per player, the diagonal is a
 * perfect call. Hand-rolled SVG like the rest of the site's viz. */
function Scatter({ rows, gw }: { rows: AccuracyPlayerRow[]; gw: number }) {
  const W = 640;
  const H = 380;
  const M = { l: 40, r: 14, t: 14, b: 34 };
  const xs = rows.map((r) => r.xpts ?? 0);
  const ys = rows.map((r) => r.total_points);
  const xMax = Math.max(8, Math.ceil(Math.max(...xs) + 0.5));
  const yMin = Math.min(0, Math.floor(Math.min(...ys)));
  const yMax = Math.max(10, Math.ceil(Math.max(...ys)) + 1);
  const px = (v: number) => M.l + ((v - 0) / (xMax - 0)) * (W - M.l - M.r);
  const py = (v: number) => H - M.b - ((v - yMin) / (yMax - yMin)) * (H - M.t - M.b);
  const xTicks = Array.from({ length: 5 }, (_, i) => Math.round((xMax / 4) * i * 10) / 10);
  const yStep = Math.max(2, Math.ceil((yMax - yMin) / 5));
  const yTicks: number[] = [];
  for (let v = Math.ceil(yMin / yStep) * yStep; v <= yMax; v += yStep) yTicks.push(v);
  const diagEnd = Math.min(xMax, yMax);

  // selective direct labels: the biggest beat and the biggest miss
  const byDelta = [...rows].sort(
    (a, b) => b.total_points - (b.xpts ?? 0) - (a.total_points - (a.xpts ?? 0)),
  );
  const labeled = new Set(
    rows.length > 2 ? [byDelta[0]?.code, byDelta[byDelta.length - 1]?.code] : [],
  );

  return (
    <div className="border-line bg-chalk rounded-xl border p-4">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label={`GW${gw}: projected points vs realized points, one dot per player. Dots above the diagonal beat their projection.`}
      >
        {yTicks.map((v) => (
          <g key={`y${v}`}>
            <line x1={M.l} x2={W - M.r} y1={py(v)} y2={py(v)} stroke="var(--color-line)" />
            <text
              x={M.l - 8}
              y={py(v) + 3}
              textAnchor="end"
              fontSize="10"
              fill="var(--color-slate)"
              fontFamily="var(--font-mono)"
            >
              {v}
            </text>
          </g>
        ))}
        {xTicks.map((v) => (
          <text
            key={`x${v}`}
            x={px(v)}
            y={H - M.b + 16}
            textAnchor="middle"
            fontSize="10"
            fill="var(--color-slate)"
            fontFamily="var(--font-mono)"
          >
            {v}
          </text>
        ))}
        <line
          x1={px(0)}
          y1={py(0)}
          x2={px(diagEnd)}
          y2={py(diagEnd)}
          stroke="var(--color-slate)"
          strokeOpacity="0.45"
          strokeDasharray="4 4"
        />
        <text
          x={W - M.r}
          y={H - M.b - 6}
          textAnchor="end"
          fontSize="10"
          fill="var(--color-slate)"
        >
          projected xPts →
        </text>
        <text
          x={M.l + 6}
          y={M.t + 4}
          fontSize="10"
          fill="var(--color-slate)"
        >
          ↑ realized points
        </text>
        {rows.map((r) => (
          <circle
            key={r.code}
            cx={px(r.xpts ?? 0)}
            cy={py(r.total_points)}
            r="4"
            fill={MODEL_COLOR}
            fillOpacity="0.65"
            stroke="var(--color-chalk)"
            strokeWidth="1"
          >
            <title>
              {`${r.player} (${teamAbbrev(r.team)}) — projected ${pts(r.xpts, 1)}, scored ${r.total_points}`}
            </title>
          </circle>
        ))}
        {rows
          .filter((r) => labeled.has(r.code))
          .map((r) => (
            <text
              key={`l${r.code}`}
              x={px(r.xpts ?? 0) + 7}
              y={py(r.total_points) + 3}
              fontSize="10"
              fill="var(--color-ink)"
            >
              {chipName(r.player)}
            </text>
          ))}
      </svg>
      <p className="text-slate mt-2 text-xs">
        One dot per player who {rows.some((r) => r.minutes === 0) ? "was projected" : "played"} in
        GW{gw}. The dashed diagonal is a perfect call — above it, the player beat the
        projection; below it, fell short. Hover a dot for the numbers.
      </p>
    </div>
  );
}

function BeatsAndMisses({ rows }: { rows: AccuracyPlayerRow[] }) {
  const byDelta = [...rows].sort(
    (a, b) => b.total_points - (b.xpts ?? 0) - (a.total_points - (a.xpts ?? 0)),
  );
  const beats = byDelta.slice(0, 3);
  const misses = byDelta.slice(-3).reverse();
  const Row = ({ p }: { p: AccuracyPlayerRow }) => (
    <li className="flex items-baseline justify-between gap-2">
      <span className="truncate">
        {chipName(p.player)} <span className="text-slate text-xs">{teamAbbrev(p.team)}</span>
      </span>
      <span className="font-mono text-xs whitespace-nowrap">
        {pts(p.xpts, 1)} → <span className="font-semibold">{p.total_points}</span>
      </span>
    </li>
  );
  return (
    <div className="flex flex-col gap-4">
      <div className="border-line bg-chalk rounded-xl border p-4">
        <h3 className="font-chip text-slate mb-2 text-xs font-semibold tracking-wide">
          Beat the projection
        </h3>
        <ul className="space-y-1.5 text-sm">
          {beats.map((p) => (
            <Row key={p.code} p={p} />
          ))}
        </ul>
      </div>
      <div className="border-line bg-chalk rounded-xl border p-4">
        <h3 className="font-chip text-slate mb-2 text-xs font-semibold tracking-wide">
          Fell short
        </h3>
        <ul className="space-y-1.5 text-sm">
          {misses.map((p) => (
            <Row key={p.code} p={p} />
          ))}
        </ul>
      </div>
      <p className="text-slate text-xs">
        Projected → realized, among players who played. A projection is an average over
        thousands of ways a match can go — single weeks are noisy by nature.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------ methodology */

function Methodology() {
  return (
    <section className="mt-10">
      <h2 className="font-chip text-slate mb-2 text-xs font-semibold tracking-wide">
        How this is measured
      </h2>
      <div className="text-slate max-w-2xl space-y-3 text-sm leading-relaxed">
        <p>
          <strong className="text-ink">Frozen at the deadline.</strong> After every nightly
          refresh, the engine writes each upcoming gameweek&apos;s projections to a frozen
          file — and refuses to touch that file once the gameweek&apos;s deadline has passed.
          What gets scored is exactly what this site was serving when the deadline hit.
        </p>
        <p>
          <strong className="text-ink">Scored when final.</strong> A gameweek is scored only
          after FPL marks it finished and data-checked (bonus confirmed). Double-gameweek
          players are compared on their full week; fixtures postponed out of a gameweek are
          excluded and disclosed in the fixtures column, never quietly dropped.
        </p>
        <p>
          <strong className="text-ink">The baselines.</strong> FPL publishes its own expected
          points (<span className="font-mono text-xs">ep_next</span>) — it&apos;s frozen at the
          same deadline and scored the same way. Rank correlation is measured within each
          position among players who actually played; RMSE counts everyone projected,
          including the ones who never left the bench.
        </p>
      </div>
    </section>
  );
}
