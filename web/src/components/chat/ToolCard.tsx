"use client";

/** Typed tool-result cards (UI_PLAN §6): the numbers on screen come from the
 * engine payload directly — the prose merely narrates them. Hovering a card
 * highlights its players on the board. Unknown shapes fall back to a generic
 * table, never raw JSON. */

import { useMemo } from "react";
import { PitchView, type ChipData, type Slot } from "@/components/PitchView";
import { DecompositionChart, RatingDial, SubScoreBars } from "@/components/viz";
import { diffBand, diffBg, diffFg, pts, teamAbbrev } from "@/lib/format";
import { useExplorer } from "@/lib/hooks";
import { useApp } from "@/lib/store";
import type { ChatPart, GwProjection, Position, Provenance } from "@/lib/types";
import { collectPlayers } from "./useChat";

export const TOOL_LABELS: Record<string, string> = {
  get_player: "Player profile",
  project_points: "Points projection",
  compare_players: "Comparison",
  rank_players: "Ranking",
  get_fixtures: "Fixture difficulty",
  explain_rating: "Rating breakdown",
  build_squad: "Optimal squad",
  rate_my_draft: "Draft verdict",
  import_team: "Team import",
  plan_transfers: "Transfer plan",
  chip_advice: "Chip advisor",
};

export const TOOL_RUNNING: Record<string, string> = {
  get_player: "looking up the player",
  project_points: "projecting points",
  compare_players: "comparing players",
  rank_players: "ranking the pool",
  get_fixtures: "checking fixtures",
  explain_rating: "breaking down the rating",
  build_squad: "solving the squad (MILP)",
  rate_my_draft: "rating your draft",
  import_team: "importing the team from FPL",
  plan_transfers: "solving the transfer plan (MILP)",
  chip_advice: "pricing chip weeks",
};

type ToolPart = Extract<ChatPart, { type: "tool" }>;
type Obj = Record<string, unknown>;

export function ToolCard({ part }: { part: ToolPart }) {
  const { setHighlight } = useApp();
  const result = part.result as Obj | undefined;

  const players = useMemo(
    () => (result ? [...collectPlayers(result)] : []),
    [result],
  );

  if (result === undefined)
    return (
      <div className="border-line bg-paper-2 text-slate rounded-md border px-3 py-2 text-xs">
        <Spinner /> {TOOL_RUNNING[part.name] ?? `running ${part.name}`}…
      </div>
    );

  return (
    <details
      id={`toolcard-${part.id}`}
      open
      className="border-line bg-chalk rounded-md border transition-shadow"
      onMouseEnter={() => players.length && setHighlight(players)}
      onMouseLeave={() => setHighlight([])}
    >
      <summary className="text-slate cursor-pointer select-none px-3 py-2 text-xs font-semibold">
        ▦ {TOOL_LABELS[part.name] ?? part.name}
        <InputSummary name={part.name} input={part.input} />
      </summary>
      <div className="border-line border-t px-3 py-2.5">
        <CardBody name={part.name} result={result} />
        <ProvenanceLine p={result.provenance as Provenance | undefined} />
      </div>
    </details>
  );
}

function InputSummary({ name, input }: { name: string; input: Obj }) {
  const bits: string[] = [];
  if (typeof input.query === "string") bits.push(input.query);
  if (Array.isArray(input.players)) bits.push((input.players as string[]).slice(0, 3).join(", ") + ((input.players as string[]).length > 3 ? "…" : ""));
  if (typeof input.team === "string") bits.push(input.team);
  if (typeof input.position === "string") bits.push(input.position as string);
  if (input.max_price != null) bits.push(`≤£${input.max_price}m`);
  if (name === "build_squad" && input.budget != null) bits.push(`£${input.budget}m`);
  return bits.length ? <span className="font-normal"> — {bits.join(" · ")}</span> : null;
}

function CardBody({ name, result }: { name: string; result: Obj }) {
  // honest non-answers first: errors, ambiguity, not-yet-available
  if (typeof result.error === "string")
    return (
      <p className="text-sm">
        {result.error}
        {typeof result.hint === "string" && (
          <span className="text-slate block text-xs">{result.hint}</span>
        )}
      </p>
    );
  if (typeof result.ambiguous === "string")
    return (
      <div className="text-sm">
        <p>{result.ambiguous}:</p>
        <ul className="text-slate mt-1 list-disc pl-5 text-xs">
          {(result.candidates as string[] | undefined)?.map((c) => <li key={c}>{c}</li>)}
        </ul>
      </div>
    );
  if (typeof result.not_available === "string")
    return <p className="text-slate text-sm">{result.not_available}</p>;
  if (Array.isArray(result.errors) && result.errors.length > 0 && !result.projections)
    return <Generic value={result.errors} />;

  switch (name) {
    case "get_player":
      return <PlayerCard r={result} />;
    case "project_points":
      return <ProjectionCard r={result} />;
    case "compare_players":
      return <ComparisonCard r={result} />;
    case "rank_players":
      return <RankCard r={result} />;
    case "get_fixtures":
      return <FixturesCard r={result} />;
    case "explain_rating":
      return <RatingCard r={result} />;
    case "build_squad":
    case "rate_my_draft":
      return <SolutionCard r={result} />;
    case "import_team":
      return <TeamImportCard r={result} />;
    case "plan_transfers":
      return <TransferPlanCard r={result} />;
    case "chip_advice":
      return <ChipAdviceCard r={result} />;
    default:
      return <Generic value={result} />;
  }
}

function TeamImportCard({ r }: { r: Obj }) {
  if (r.status === "pending")
    return (
      <p className="text-slate text-sm">
        {typeof r.note === "string" ? r.note : "picks aren't public yet"}
      </p>
    );
  const squad = (r.squad as Obj[] | undefined) ?? [];
  return (
    <div className="text-sm">
      <p>
        <strong>{String(r.team_name ?? "")}</strong>
        {r.overall_rank != null && (
          <span className="text-slate font-mono text-xs">
            {" "}
            · rank {Number(r.overall_rank).toLocaleString()}
          </span>
        )}
        <span className="text-slate font-mono text-xs">
          {" "}
          · bank {String(r.bank)} · {String(r.free_transfers)} FT
        </span>
      </p>
      <p className="mt-1 leading-relaxed">
        {squad.map((p, i) => (
          <span key={i}>
            {i > 0 && ", "}
            {String(p.web_name ?? p.player)}
            {p.captain ? " (C)" : p.vice_captain ? " (V)" : ""}
          </span>
        ))}
      </p>
      {Array.isArray(r.chips_available) && (
        <p className="text-slate mt-1 text-xs">
          chips in hand: {(r.chips_available as string[]).join(", ") || "none"}
        </p>
      )}
    </div>
  );
}

function ChipAdviceCard({ r }: { r: Obj }) {
  const chips = (r.chips as Record<string, Obj> | undefined) ?? {};
  return (
    <div className="text-sm">
      <ul className="space-y-1">
        {Object.entries(chips).map(([key, c]) => (
          <li key={key} className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-medium">{String(c.label)}</span>
            <span className="font-mono text-xs">
              best GW{String(c.best_gw)} +{pts(c.expected_gain as number)}
            </span>
            <span className="text-slate text-xs">{String(c.assessment)}</span>
          </li>
        ))}
      </ul>
      {typeof r.note === "string" && (
        <p className="text-slate mt-1.5 text-[11px] leading-snug">{r.note}</p>
      )}
    </div>
  );
}

function TransferPlanCard({ r }: { r: Obj }) {
  const steps = (r.steps as Obj[] | undefined) ?? [];
  const week = r.this_week as Obj | undefined;
  const weekMoves = (week?.moves as Obj[] | undefined) ?? [];
  const gws = r.horizon_gws as [number, number] | undefined;
  return (
    <div className="text-sm">
      <p>
        {week?.action === "hold" ? (
          <>
            <strong>Hold</strong> — bank the free transfer.
          </>
        ) : (
          <>
            <strong>This week:</strong>{" "}
            {weekMoves.map((m, i) => (
              <span key={i}>
                {i > 0 && "; "}
                <span className="text-slate">{String(m.out)}</span> →{" "}
                <strong>{String(m.in)}</strong>
              </span>
            ))}
            {week?.hit_cost ? (
              <span className="text-card-red ml-1 font-mono text-xs">
                {String(week.hit_cost)} hit
              </span>
            ) : null}
          </>
        )}
      </p>
      <p className="text-slate mt-1 font-mono text-xs">
        {gws ? `GW${gws[0]}–${gws[1]}: ` : ""}
        {pts(r.expected_pts_with_plan as number)} with the plan vs{" "}
        {pts(r.expected_pts_holding as number)} holding (+
        {pts(r.expected_gain as number)})
      </p>
      <ul className="mt-1.5 space-y-0.5 text-xs">
        {steps.map((s) => {
          const moves = (s.moves as Obj[] | undefined) ?? [];
          return (
            <li key={String(s.gw)} className="flex gap-2">
              <span className="text-slate w-10 shrink-0 font-mono">GW{String(s.gw)}</span>
              <span className="min-w-0">
                {s.action === "hold"
                  ? "hold"
                  : moves
                      .map((m) => `${String(m.out)} → ${String(m.in)}`)
                      .join("; ")}
                {s.hit_cost ? (
                  <span className="text-card-red ml-1 font-mono">{String(s.hit_cost)}</span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
      {typeof r.note === "string" && (
        <p className="text-slate mt-1.5 text-[11px] leading-snug">{r.note}</p>
      )}
    </div>
  );
}

function PlayerCard({ r }: { r: Obj }) {
  const fx = (r.fixtures as Obj[] | undefined) ?? [];
  return (
    <div className="text-sm">
      <p className="font-medium">
        {String(r.player)}{" "}
        <span className="text-slate font-normal">
          {String(r.team)} · {String(r.position)} · <span className="font-mono">{String(r.price)}</span>
        </span>
      </p>
      <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs">
        <span>xPts (window): <strong>{pts(r.xpts_next_gws as number)}</strong></span>
        {r.rating != null && <span>rating: <strong>{String(r.rating)}</strong></span>}
        {r.p_start_avg != null && <span>start: {Math.round((r.p_start_avg as number) * 100)}%</span>}
      </div>
      {fx.length > 0 && (
        <div className="mt-2 flex gap-1">
          {fx.slice(0, 6).map((f, i) => (
            <span key={i} className="bg-paper-2 flex w-10 flex-col items-center rounded py-0.5 text-[9px]" title={`GW${f.gw} ${f.home ? "vs" : "@"} ${f.opponent}`}>
              <span className="font-chip">{teamAbbrev(String(f.opponent))}{f.home ? "" : "*"}</span>
              <span className="font-mono font-semibold">{pts(f.xpts as number)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function ProjectionCard({ r }: { r: Obj }) {
  const projections = (r.projections as Obj[] | undefined) ?? [];
  return (
    <div className="space-y-3">
      {projections.map((p) => (
        <div key={String(p.player)}>
          <p className="text-sm font-medium">
            {String(p.player)}{" "}
            <span className="text-slate font-normal">
              · total <span className="font-mono font-semibold">{pts(p.total_xpts as number)}</span> xPts
            </span>
          </p>
          <div className="mt-1.5">
            <DecompositionChart perGw={(p.per_gw ?? []) as GwProjection[]} />
          </div>
        </div>
      ))}
    </div>
  );
}

function ComparisonCard({ r }: { r: Obj }) {
  const rows = (r.comparison as Obj[] | undefined) ?? [];
  if (!rows.length) return <Generic value={r} />;
  const subKeys = [...new Set(rows.flatMap((p) => Object.keys((p.sub_scores as Obj) ?? {})))];
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate text-left">
            <th className="py-1 pr-2 font-medium">&nbsp;</th>
            {rows.map((p) => (
              <th key={String(p.player)} className="py-1 pr-2 font-semibold">{String(p.player)}</th>
            ))}
          </tr>
        </thead>
        <tbody className="font-mono">
          <CmpRow label="Team" cells={rows.map((p) => teamAbbrev(String(p.team)))} />
          <CmpRow label="Price" cells={rows.map((p) => String(p.price))} />
          <CmpRow label="xPts" cells={rows.map((p) => pts(p.xpts_next_gws as number))} strong />
          <CmpRow label="Rating" cells={rows.map((p) => String(p.rating ?? "—"))} />
          {subKeys.map((k) => (
            <CmpRow
              key={k}
              label={k.replace(/_/g, " ")}
              cells={rows.map((p) => String(((p.sub_scores as Obj) ?? {})[k] ?? "—"))}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CmpRow({ label, cells, strong }: { label: string; cells: string[]; strong?: boolean }) {
  return (
    <tr className="border-line border-t">
      <td className="text-slate py-1 pr-2 font-sans">{label}</td>
      {cells.map((c, i) => (
        <td key={i} className={`py-1 pr-2 ${strong ? "font-semibold" : ""}`}>{c}</td>
      ))}
    </tr>
  );
}

function RankCard({ r }: { r: Obj }) {
  const rows = (r.players as Obj[] | undefined) ?? [];
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate text-left">
            <th className="py-1 pr-2 font-medium">Player</th>
            <th className="py-1 pr-2 text-right font-medium">£</th>
            <th className="py-1 pr-2 text-right font-medium">xPts</th>
            <th className="py-1 pr-2 text-right font-medium">Rating</th>
            <th className="py-1 text-right font-medium">/£m</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {rows.map((p) => (
            <tr key={String(p.player)} className="border-line border-t">
              <td className="py-1 pr-2 font-sans">
                {String(p.player)} <span className="text-slate">{teamAbbrev(String(p.team))}</span>
              </td>
              <td className="py-1 pr-2 text-right">{String(p.price).replace(/[£m]/g, "")}</td>
              <td className="py-1 pr-2 text-right font-semibold">{pts(p.xpts_next_gws as number)}</td>
              <td className="py-1 pr-2 text-right">{String(p.rating ?? "—")}</td>
              <td className="py-1 text-right">{pts(p.xpts_per_million as number, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FixturesCard({ r }: { r: Obj }) {
  const fx = (r.fixtures as Obj[] | undefined) ?? [];
  return (
    <div className="text-xs">
      <p className="mb-1.5 text-sm font-medium">{String(r.team)}</p>
      <div className="space-y-1">
        {fx.map((f, i) => {
          const d = (f.expected_goals_against as number) - (f.expected_goals_for as number);
          return (
            <div key={i} className="flex items-center gap-2">
              <span className="text-slate w-9 font-mono">GW{String(f.gw)}</span>
              <span
                className="w-7 rounded-[3px] py-0.5 text-center font-mono font-semibold"
                style={{ background: diffBg(d), color: diffFg(d) }}
              >
                {diffBand(d)}
              </span>
              <span className="flex-1">
                {f.home ? "vs" : "@"} {String(f.opponent)}
              </span>
              <span className="text-slate font-mono">
                xG {pts(f.expected_goals_for as number, 1)}–{pts(f.expected_goals_against as number, 1)} · CS{" "}
                {Math.round((f.clean_sheet_probability as number) * 100)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function RatingCard({ r }: { r: Obj }) {
  const subs = (r.sub_scores as Record<string, number | null>) ?? {};
  return (
    <div className="text-sm">
      <div className="flex items-center gap-4">
        <RatingDial rating={(r.rating as number) ?? null} size={60} />
        <p className="text-xs">
          <span className="font-medium">{String(r.player)}</span>{" "}
          <span className="text-slate">({String(r.position)})</span>
          <br />
          <span className="text-slate">
            strongest: {String(r.strongest).replace(/_/g, " ")} · weakest:{" "}
            {String(r.weakest).replace(/_/g, " ")}
          </span>
        </p>
      </div>
      <div className="mt-2.5">
        <SubScoreBars subScores={subs} order={Object.keys(subs)} />
      </div>
    </div>
  );
}

function SolutionCard({ r }: { r: Obj }) {
  const { setDraft } = useApp();
  const { data: explorer } = useExplorer();
  const xi = (r.starting_xi as Obj[] | undefined) ?? [];
  const bench = (r.bench_in_order as Obj[] | undefined) ?? [];
  if (!xi.length) return <Generic value={r} />;

  const toChip = (p: Obj): ChipData => ({
    player: String(p.player),
    webName: typeof p.web_name === "string" ? p.web_name : undefined,
    team: String(p.team),
    position: p.position as Position,
    primary: pts(p.xpts as number),
    captain: p.captain === true,
    vice: p.vice_captain === true,
  });
  const rows: Slot[][] = (["GKP", "DEF", "MID", "FWD"] as Position[]).map((pos) =>
    xi.filter((p) => p.position === pos).map((p) => ({ chip: toChip(p), position: pos })),
  );

  const byName = new Map((explorer?.players ?? []).map((p) => [p.player, p.code]));
  const codes = [...xi, ...bench].map((p) => byName.get(String(p.player)));
  const canApply = codes.every((c): c is number => c != null) && codes.length === 15;

  return (
    <div className="text-sm">
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs">
        <span>{String(r.formation)}</span>
        <span>{String(r.draft_cost ?? r.cost)}</span>
        <span>
          XI+C: <strong>{pts(r.xi_plus_captain_xpts as number)}</strong> xPts
        </span>
        {r.gap_to_optimal != null && (
          <span>
            gap to optimal: <strong>{pts(r.gap_to_optimal as number)}</strong>
          </span>
        )}
      </div>
      <PitchView rows={rows} bench={bench.map(toChip)} small />
      {canApply && (
        <button
          onClick={() => setDraft(codes as number[])}
          className="border-line hover:border-royal hover:text-royal mt-2 rounded-full border px-3 py-1.5 text-xs font-medium"
        >
          Use as my draft
        </button>
      )}
    </div>
  );
}

/** Last-resort renderer: key-value list / table — never raw JSON. */
function Generic({ value }: { value: unknown }) {
  if (Array.isArray(value))
    return (
      <ul className="list-disc space-y-1 pl-5 text-xs">
        {value.slice(0, 20).map((v, i) => (
          <li key={i}>
            <Generic value={v} />
          </li>
        ))}
      </ul>
    );
  if (value && typeof value === "object")
    return (
      <dl className="space-y-0.5 text-xs">
        {Object.entries(value as Obj)
          .filter(([k]) => k !== "provenance")
          .slice(0, 24)
          .map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="text-slate min-w-24 shrink-0">{k.replace(/_/g, " ")}</dt>
              <dd className="min-w-0">
                {typeof v === "object" ? <Generic value={v} /> : <span className="font-mono">{String(v)}</span>}
              </dd>
            </div>
          ))}
      </dl>
    );
  return <span className="font-mono text-xs">{String(value)}</span>;
}

function ProvenanceLine({ p }: { p?: Provenance }) {
  if (!p) return null;
  return (
    <p className="text-slate border-line mt-2 border-t pt-1.5 font-mono text-[10px]">
      {p.season} GW{p.gw_window[0]}–{p.gw_window[1]} · computed{" "}
      {p.computed_at.slice(0, 16).replace("T", " ")}
    </p>
  );
}

function Spinner() {
  return (
    <span
      className="border-slate mr-1 inline-block h-3 w-3 animate-spin rounded-full border-[1.5px] border-t-transparent align-[-2px]"
      aria-hidden
    />
  );
}
