"use client";

/** Compare: upload screenshots of candidate squads from the official FPL app,
 * confirm the extracted 15s, and let the engine rate and diff them. The vision
 * model only reads shirt labels — every number on this page comes from the
 * engine, and nothing is rated until the user has confirmed each squad. */

import { useMemo, useRef, useState } from "react";
import { useAuth, useClerk } from "@clerk/nextjs";
import { useMutation } from "@tanstack/react-query";
import { PageShell } from "@/components/PageShell";
import { PitchView, type ChipData, type Slot } from "@/components/PitchView";
import { PlayerPicker } from "@/components/PlayerPicker";
import { KV, RateCard } from "@/components/RateCard";
import { api } from "@/lib/api";
import { fileToSquadImage } from "@/lib/image";
import { POSITIONS, pts, teamAbbrev } from "@/lib/format";
import { useExplorer, useMeta } from "@/lib/hooks";
import type {
  ComparedSquad,
  ExplorerPlayer,
  ExtractedPlayer,
  Position,
  SolutionPlayer,
  SquadComparison,
  SquadExtraction,
} from "@/lib/types";

const SHAPE: Record<Position, number> = { GKP: 2, DEF: 5, MID: 5, FWD: 3 };
const MAX_SQUADS = 4;

type UploadSlot = {
  id: number;
  label: string;
  preview: string | null;
  status: "extracting" | "ready" | "error";
  error?: string;
  extraction?: SquadExtraction;
  /** index into extraction.players → user-chosen replacement */
  fixes: Record<number, ExplorerPlayer>;
};

/** One confirmed player: either the resolver's unique match or the user's fix. */
type Confirmed = {
  code: number;
  player: string;
  web_name?: string | null;
  team: string;
  position: Position;
};

function confirmedEntry(slot: UploadSlot, i: number): Confirmed | null {
  const fix = slot.fixes[i];
  if (fix) {
    return {
      code: fix.code,
      player: fix.player,
      web_name: fix.web_name,
      team: fix.team,
      position: fix.position,
    };
  }
  const p = slot.extraction?.players[i];
  return p && p.status === "ok" && p.match ? p.match : null;
}

function slotProblems(slot: UploadSlot): string[] {
  if (slot.status !== "ready" || !slot.extraction) return [];
  const entries = slot.extraction.players.map((_, i) => confirmedEntry(slot, i));
  const problems: string[] = [];
  if (slot.extraction.players.length !== 15)
    problems.push(`only ${slot.extraction.players.length} players read — retake the screenshot with the full squad in shot`);
  const unresolved = entries.filter((e) => e === null).length;
  if (unresolved) problems.push(`${unresolved} player${unresolved > 1 ? "s" : ""} to confirm`);
  const codes = entries.filter((e): e is Confirmed => !!e).map((e) => e.code);
  if (new Set(codes).size !== codes.length) problems.push("the same player appears twice");
  const counts: Record<Position, number> = { GKP: 0, DEF: 0, MID: 0, FWD: 0 };
  for (const e of entries) if (e) counts[e.position]++;
  if (
    !unresolved &&
    slot.extraction.players.length === 15 &&
    POSITIONS.some((pos) => counts[pos] !== SHAPE[pos])
  )
    problems.push(
      `squad shape is ${POSITIONS.map((p) => `${counts[p]} ${p}`).join(", ")} — needs 2 GKP / 5 DEF / 5 MID / 3 FWD`,
    );
  return problems;
}

const slotValid = (slot: UploadSlot) =>
  slot.status === "ready" && !!slot.extraction && slotProblems(slot).length === 0;

const slotCodes = (slot: UploadSlot): number[] =>
  (slot.extraction?.players ?? [])
    .map((_, i) => confirmedEntry(slot, i))
    .filter((e): e is Confirmed => !!e)
    .map((e) => e.code);

export default function ComparePage() {
  const { data: explorer } = useExplorer();
  const { data: meta } = useMeta();
  const { isLoaded: authLoaded, isSignedIn, getToken } = useAuth();
  const clerk = useClerk();

  const [slots, setSlots] = useState<UploadSlot[]>([]);
  const [fixing, setFixing] = useState<{ slotId: number; index: number; position: Position } | null>(null);
  const nextId = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);

  const byCode = useMemo(
    () => new Map((explorer?.players ?? []).map((p) => [p.code, p])),
    [explorer],
  );

  const compare = useMutation({
    mutationFn: async () =>
      api.compareSquads(
        {
          squads: slots
            .filter(slotValid)
            .map((s) => ({ label: s.label, codes: slotCodes(s) })),
        },
        (await getToken()) ?? undefined,
      ),
  });
  const rateOne = useMutation({
    mutationFn: (codes: number[]) => api.rateCodes(codes),
  });

  const invalidateResults = () => {
    compare.reset();
    rateOne.reset();
  };

  function updateSlot(id: number, patch: Partial<UploadSlot>) {
    setSlots((prev) => prev.map((s) => (s.id === id ? { ...s, ...patch } : s)));
  }

  async function addFiles(files: File[]) {
    if (!isSignedIn) return clerk.openSignIn();
    invalidateResults();
    const room = MAX_SQUADS - slots.length;
    const token = (await getToken()) ?? undefined;
    for (const file of files.slice(0, room)) {
      const id = nextId.current++;
      const label = `Team ${String.fromCharCode(65 + (id % 26))}`;
      setSlots((prev) => [
        ...prev,
        { id, label, preview: null, status: "extracting", fixes: {} },
      ]);
      // fire per-file so one bad image doesn't sink the batch
      (async () => {
        try {
          const { image, preview } = await fileToSquadImage(file);
          updateSlot(id, { preview });
          const extraction = await api.extractSquad({ image, media_type: "image/jpeg" }, token);
          updateSlot(id, { status: "ready", extraction });
        } catch (e) {
          updateSlot(id, { status: "error", error: (e as Error).message });
        }
      })();
    }
  }

  const validSlots = slots.filter(slotValid);
  const extracting = slots.some((s) => s.status === "extracting");
  const activeSlot = fixing ? slots.find((s) => s.id === fixing.slotId) : undefined;

  return (
    <PageShell title="Compare Teams">
      {/* upload zone + slot cards */}
      <div className="grid gap-4 md:grid-cols-2">
        {slots.map((slot) => (
          <SlotCard
            key={slot.id}
            slot={slot}
            byCode={byCode}
            onLabel={(label) => {
              updateSlot(slot.id, { label });
              invalidateResults();
            }}
            onFix={(index, position) => setFixing({ slotId: slot.id, index, position })}
            onQuickFix={(index, code) => {
              const p = byCode.get(code);
              if (!p) return;
              updateSlot(slot.id, { fixes: { ...slot.fixes, [index]: p } });
              invalidateResults();
            }}
            onRemove={() => {
              setSlots((prev) => prev.filter((s) => s.id !== slot.id));
              invalidateResults();
            }}
          />
        ))}

        {slots.length < MAX_SQUADS && (
          <button
            onClick={() => {
              if (!isSignedIn) return clerk.openSignIn();
              fileInput.current?.click();
            }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              addFiles([...e.dataTransfer.files]);
            }}
            disabled={!authLoaded}
            title={isSignedIn ? undefined : "Sign in to upload screenshots (free)"}
            className="border-line hover:border-royal text-slate hover:text-royal flex min-h-40 flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed p-6 text-center text-sm"
          >
            <span className="text-2xl leading-none">+</span>
            <span className="font-medium">
              {slots.length === 0
                ? "Drop squad screenshots here, or tap to choose"
                : "Add another team"}
            </span>
            <span className="text-xs">
              Official FPL app or site — Pick Team or Transfers view, all 15 in shot.
              Up to {MAX_SQUADS} teams, one per image.
              {isSignedIn ? "" : " Sign in to start (free)."}
            </span>
          </button>
        )}
      </div>
      <input
        ref={fileInput}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        multiple
        className="hidden"
        onChange={(e) => {
          addFiles([...(e.target.files ?? [])]);
          e.target.value = "";
        }}
      />

      {/* action bar */}
      {slots.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          {slots.length >= 2 && (
            <button
              onClick={() => compare.mutate()}
              disabled={validSlots.length < 2 || extracting || compare.isPending}
              title={
                validSlots.length < 2
                  ? "Confirm at least two full squads first"
                  : undefined
              }
              className="btn-primary rounded-full px-4 py-2 text-sm disabled:opacity-50"
            >
              {compare.isPending
                ? "Comparing…"
                : `Compare ${validSlots.length >= 2 ? validSlots.length : ""} teams`}
            </button>
          )}
          {slots.length === 1 && (
            <button
              onClick={() => rateOne.mutate(slotCodes(slots[0]))}
              disabled={validSlots.length !== 1 || extracting || rateOne.isPending}
              title={validSlots.length === 1 ? undefined : "Confirm the full 15 first"}
              className="btn-primary rounded-full px-4 py-2 text-sm disabled:opacity-50"
            >
              {rateOne.isPending ? "Rating…" : "Rate this team"}
            </button>
          )}
          {(compare.error || rateOne.error) && (
            <p className="text-card-red text-sm">
              {String(((compare.error ?? rateOne.error) as Error).message)}
            </p>
          )}
        </div>
      )}

      {/* results */}
      {rateOne.data && (
        <div className="mt-5 max-w-sm">
          <RateCard result={rateOne.data} title={`${slots[0]?.label ?? "Team"} verdict`} onDismiss={() => rateOne.reset()} />
        </div>
      )}
      {compare.data && <CompareResults result={compare.data} />}

      {/* fix a mis-read player — same picker as the builder, position-scoped */}
      <PlayerPicker
        position={fixing?.position ?? null}
        onClose={() => setFixing(null)}
        onPick={(p) => {
          if (!fixing) return;
          setSlots((prev) =>
            prev.map((s) =>
              s.id === fixing.slotId ? { ...s, fixes: { ...s.fixes, [fixing.index]: p } } : s,
            ),
          );
          invalidateResults();
        }}
        squad={
          activeSlot
            ? slotCodes(activeSlot)
                .map((c) => byCode.get(c))
                .filter((p): p is ExplorerPlayer => !!p)
            : []
        }
        maxPerClub={meta?.squad_rules.max_per_club ?? 3}
        remaining={99999} // budget is not this page's concern — the squads are what they are
      />
    </PageShell>
  );
}

function SlotCard({
  slot,
  byCode,
  onLabel,
  onFix,
  onQuickFix,
  onRemove,
}: {
  slot: UploadSlot;
  byCode: Map<number, ExplorerPlayer>;
  onLabel: (label: string) => void;
  onFix: (index: number, position: Position) => void;
  onQuickFix: (index: number, code: number) => void;
  onRemove: () => void;
}) {
  const problems = slotProblems(slot);
  const entries = (slot.extraction?.players ?? []).map((p, i) => ({
    p,
    i,
    eff: confirmedEntry(slot, i),
  }));
  const bands = POSITIONS.map((pos) => ({
    pos,
    rows: entries.filter(({ p, eff }) => (eff?.position ?? p.row ?? "MID") === pos),
  }));

  return (
    <div className="border-line bg-chalk rounded-xl border p-4 text-sm">
      <div className="flex items-center gap-3">
        {slot.preview && (
          /* eslint-disable-next-line @next/next/no-img-element -- local data URL preview */
          <img
            src={slot.preview}
            alt={`${slot.label} screenshot`}
            className="border-line h-14 w-10 shrink-0 rounded border object-cover object-top"
          />
        )}
        <input
          value={slot.label}
          onChange={(e) => onLabel(e.target.value)}
          aria-label="Team label"
          className="border-line bg-paper-2 focus:border-royal min-w-0 flex-1 rounded-full border px-3 py-1 text-sm font-medium outline-none"
        />
        <button
          onClick={onRemove}
          className="text-slate hover:text-card-red px-1 text-xl leading-none"
          aria-label={`Remove ${slot.label}`}
        >
          ×
        </button>
      </div>

      {slot.status === "extracting" && (
        <p className="text-slate mt-3 animate-pulse">Reading the screenshot…</p>
      )}
      {slot.status === "error" && (
        <p className="text-card-red mt-3">{slot.error}</p>
      )}

      {slot.status === "ready" && slot.extraction && (
        <>
          {problems.length > 0 ? (
            problems.map((p) => (
              <p key={p} className="text-card-yellow mt-2 text-xs">
                {p}
              </p>
            ))
          ) : (
            <p className="text-neon-deep mt-2 text-xs">All 15 confirmed ✓</p>
          )}
          <div className="mt-2 space-y-2">
            {bands.map(({ pos, rows }) =>
              rows.length === 0 ? null : (
                <div key={pos}>
                  <div className="font-chip text-slate text-[10px] font-semibold tracking-wide">
                    {pos}
                  </div>
                  <ul>
                    {rows.map(({ p, i, eff }) => (
                      <EntryRow
                        key={i}
                        entry={p}
                        eff={eff}
                        fixed={!!slot.fixes[i]}
                        onFix={() => onFix(i, eff?.position ?? p.row ?? pos)}
                        onQuickFix={(code) => onQuickFix(i, code)}
                        byCode={byCode}
                      />
                    ))}
                  </ul>
                </div>
              ),
            )}
          </div>
        </>
      )}
    </div>
  );
}

function EntryRow({
  entry,
  eff,
  fixed,
  onFix,
  onQuickFix,
  byCode,
}: {
  entry: ExtractedPlayer;
  eff: Confirmed | null;
  fixed: boolean;
  onFix: () => void;
  onQuickFix: (code: number) => void;
  byCode: Map<number, ExplorerPlayer>;
}) {
  const name = eff ? (eff.web_name ?? eff.player) : entry.shown;
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 py-0.5">
      <span className={`font-medium ${eff ? "" : "text-card-red"}`}>
        {name}
        {entry.is_captain && <span className="text-slate ml-1 font-chip text-[10px]">C</span>}
        {entry.is_vice && <span className="text-slate ml-1 font-chip text-[10px]">V</span>}
      </span>
      {eff && <span className="text-slate text-xs">{teamAbbrev(eff.team)}</span>}
      {fixed && <span className="text-royal text-xs">fixed — read as “{entry.shown}”</span>}
      {!fixed && entry.status === "ambiguous" && (
        <span className="text-card-yellow text-xs">which one?</span>
      )}
      {!fixed && entry.status === "none" && (
        <span className="text-card-yellow text-xs">couldn’t match “{entry.shown}”</span>
      )}
      {!fixed && entry.status === "ok" && entry.row_mismatch && eff && (
        <span className="text-card-yellow text-xs">
          read as {entry.row}, engine says {eff.position}
        </span>
      )}
      <span className="ml-auto flex items-center gap-1.5">
        {!fixed &&
          entry.status === "ambiguous" &&
          entry.candidates.slice(0, 3).map(
            (c) =>
              byCode.has(c.code) && (
                <button
                  key={c.code}
                  onClick={() => onQuickFix(c.code)}
                  className="border-line hover:border-royal hover:text-royal rounded-full border px-2 py-0.5 text-xs"
                >
                  {c.web_name ?? c.player} · {teamAbbrev(c.team)}
                </button>
              ),
          )}
        <button onClick={onFix} className="text-slate hover:text-royal text-xs">
          change
        </button>
      </span>
    </li>
  );
}

function CompareResults({ result }: { result: SquadComparison }) {
  const gw = result.provenance.gw_window[0];
  return (
    <div className="mt-5 space-y-4">
      <div className="border-line bg-chalk rounded-xl border p-4">
        <h3 className="font-chip text-xs font-semibold tracking-wide">Verdict</h3>
        <p className="mt-1 text-sm">
          <strong className="text-ink">{result.verdict.best}</strong>
          {result.verdict.margin_xpts <= 0.05 ? (
            <span className="text-slate"> — dead level with the next best over the window.</span>
          ) : (
            <>
              {" "}projects best:{" "}
              <span className="font-mono font-semibold">+{pts(result.verdict.margin_xpts)} pts</span>
              <span className="text-slate"> over the next best across the projection window.</span>
            </>
          )}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {result.squads.map((sq) => (
          <SquadResult key={sq.label} squad={sq} best={sq.label === result.verdict.best} gw={gw} />
        ))}
      </div>

      <div className="border-line bg-chalk rounded-xl border p-4 text-sm">
        <h3 className="font-chip text-xs font-semibold tracking-wide">Differentials</h3>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          {result.squads.map((sq) => (
            <div key={sq.label}>
              <div className="font-chip text-slate text-[10px] font-semibold tracking-wide">
                Only in {sq.label}
              </div>
              {(result.differentials[sq.label] ?? []).length === 0 ? (
                <p className="text-slate text-xs">nothing — fully covered elsewhere</p>
              ) : (
                <ul className="text-xs">
                  {(result.differentials[sq.label] ?? []).map((p) => (
                    <li key={p.code} className="flex items-baseline justify-between gap-2 py-0.5">
                      <span>
                        {p.web_name ?? p.player}{" "}
                        <span className="text-slate">{teamAbbrev(p.team)} · {p.position}</span>
                      </span>
                      <span className="font-mono">{pts(p.xpts)} pts</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
        <p className="text-slate border-line mt-3 border-t pt-2 text-xs">
          {result.shared.length} shared player{result.shared.length === 1 ? "" : "s"}
          {result.shared.length > 0 && (
            <>
              {": "}
              {result.shared.map((p) => p.web_name ?? p.player).join(", ")}
            </>
          )}
        </p>
      </div>
    </div>
  );
}

function SquadResult({ squad, best, gw }: { squad: ComparedSquad; best: boolean; gw: number }) {
  const toChip = (p: SolutionPlayer): ChipData => ({
    player: p.player,
    webName: p.web_name,
    team: p.team,
    position: p.position,
    captain: p.captain,
    vice: p.vice_captain,
    primary: `${pts(p.xpts_this_gw ?? p.xpts)} pts`,
  });
  const rows: Slot[][] = POSITIONS.map((pos) =>
    squad.starting_xi
      .filter((p) => p.position === pos)
      .map((p) => ({ chip: toChip(p), position: pos })),
  );
  const bench: ChipData[] = squad.bench_in_order.map(toChip);

  return (
    <div className={`rounded-xl border p-4 text-sm ${best ? "border-royal bg-chalk" : "border-line bg-chalk"}`}>
      <div className="flex items-baseline justify-between">
        <h3 className="font-chip text-xs font-semibold tracking-wide">{squad.label}</h3>
        {best && (
          <span className="bg-deep text-neon font-chip rounded-full px-2 py-0.5 text-[10px] font-bold">
            BEST PICK
          </span>
        )}
      </div>
      <div className="mt-2 space-y-1.5">
        {squad.xi_plus_captain_xpts_this_gw != null && (
          <KV k={`Best XI + captain, GW${gw}`} v={`${pts(squad.xi_plus_captain_xpts_this_gw)} pts`} strong />
        )}
        <KV k="XI + captain, whole window" v={`${pts(squad.xi_plus_captain_xpts)} pts`} />
        <KV k="Formation" v={squad.formation} />
        <KV k="Captain" v={squad.captain ? (squad.captain.web_name ?? squad.captain.player) : "—"} />
        <KV k="Squad cost" v={squad.draft_cost ?? squad.cost} />
        {squad.gap_to_optimal != null && (
          <KV
            k="Gap to optimal"
            v={
              squad.gap_to_optimal <= 0.05
                ? "none — optimal at this spend"
                : `−${pts(squad.gap_to_optimal)} pts`
            }
          />
        )}
      </div>
      <div className="mt-3 flex justify-center">
        <PitchView rows={rows} bench={bench} small />
      </div>
    </div>
  );
}
