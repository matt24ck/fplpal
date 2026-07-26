"use client";

/** The Board (UI_PLAN §4): the pitch is the primary analytical instrument.
 * SVG surface (stripes + chalk + floodlight vignette), chips as real
 * positioned buttons so focus order and touch targets come free. Every chip
 * wears its club's shirt — the team reads before any text does. GK row at
 * the top, bench strip below. */

import { useId } from "react";
import { useApp } from "@/lib/store";
import { chipName, diffBand, diffBg, diffFg, price as fmtPrice, teamAbbrev } from "@/lib/format";
import type { FixtureCell, Position } from "@/lib/types";
import { Shirt } from "./Shirt";

export interface ChipData {
  code?: number;
  player: string;
  team: string;
  position: Position;
  price?: number; // tenths
  primary?: string; // formatted stat for the active overlay
  fixtures?: FixtureCell[]; // fixtures overlay: next-3 difficulty strip
  captain?: boolean;
  vice?: boolean;
  flag?: "doubt" | "out" | null;
}

export interface Slot {
  chip: ChipData | null;
  position: Position;
}

interface PitchViewProps {
  rows: Slot[][]; // GKP row first, then DEF / MID / FWD
  bench?: ChipData[];
  edit?: boolean;
  small?: boolean;
  onSlotClick?: (slot: Slot) => void;
  onRemove?: (chip: ChipData) => void;
}

const ROW_Y = [11, 37, 63, 87]; // % of pitch height per position row

export function PitchView({ rows, bench, edit, small, onSlotClick, onRemove }: PitchViewProps) {
  return (
    <div className={small ? "w-full max-w-[300px]" : "w-full max-w-[520px]"}>
      <div className="relative w-full overflow-hidden rounded-xl" style={{ aspectRatio: "10 / 12" }}>
        <PitchSurface />
        {rows.map((row, ri) =>
          row.map((slot, si) => {
            const x = ((si + 1) / (row.length + 1)) * 100;
            const y = ROW_Y[ri] ?? 50;
            // cap width by row density so 5-across chips never overlap (badges sit outside the chip edge)
            const w = Math.min(small ? 27 : 20, 100 / (row.length + 1) - 1.2);
            return (
              <div
                key={`${ri}-${si}-${slot.chip?.code ?? "empty"}`}
                className="absolute -translate-x-1/2 -translate-y-1/2"
                style={{ left: `${x}%`, top: `${y}%`, width: `${w}%` }}
              >
                {slot.chip ? (
                  <PlayerChip
                    chip={slot.chip}
                    small={small}
                    edit={edit}
                    onClick={onSlotClick ? () => onSlotClick(slot) : undefined}
                    onRemove={onRemove}
                  />
                ) : (
                  <button
                    onClick={onSlotClick ? () => onSlotClick(slot) : undefined}
                    className="border-chalk/60 text-chalk/85 hover:border-chalk hover:text-chalk w-full rounded-lg border-2 border-dashed bg-pitch-deep/20 py-3 text-center backdrop-blur-[1px]"
                    aria-label={`Add a ${slot.position}`}
                  >
                    <span className="font-chip block text-base leading-none">+</span>
                    <span className="font-chip block text-[9px] font-semibold">{slot.position}</span>
                  </button>
                )}
              </div>
            );
          }),
        )}
      </div>

      {bench && bench.length > 0 && (
        <div className="border-line bg-paper-2 mt-2 rounded-lg border px-2 pt-1.5 pb-2">
          <div className="text-slate mb-1 font-chip text-[10px] font-semibold tracking-wide">
            Bench · autosub order
          </div>
          <div className="flex gap-2">
            {bench.map((chip) => (
              <div key={chip.code ?? chip.player} className="w-1/4 min-w-0">
                <PlayerChip
                  chip={chip}
                  bench
                  small={small}
                  edit={edit}
                  onClick={
                    onSlotClick
                      ? () => onSlotClick({ chip, position: chip.position })
                      : undefined
                  }
                  onRemove={onRemove}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function PlayerChip({
  chip,
  bench,
  small,
  edit,
  onClick,
  onRemove,
}: {
  chip: ChipData;
  bench?: boolean;
  small?: boolean;
  edit?: boolean;
  onClick?: () => void;
  onRemove?: (chip: ChipData) => void;
}) {
  const { highlight } = useApp();
  const highlighted = highlight.has(chip.player.toLowerCase());
  const dimmed = highlight.size > 0 && !highlighted;

  return (
    <div className={`relative ${dimmed ? "opacity-40" : ""}`}>
      <button
        onClick={onClick}
        className={`group block w-full ${onClick ? "" : "cursor-default"}`}
        aria-label={`${chip.player}, ${chip.team}, ${chip.position}`}
        title={chip.team}
      >
        <span className={`relative mx-auto block ${small ? "w-[58%]" : "w-[62%]"}`}>
          <Shirt team={chip.team} className="block w-full drop-shadow-sm" />
          {chip.captain && <Badge label="Captain">C</Badge>}
          {chip.vice && !chip.captain && (
            <Badge label="Vice-captain" muted>
              V
            </Badge>
          )}
          {chip.flag && (
            <span
              className={`absolute -top-0.5 -left-1 block h-2.5 w-2.5 rounded-full ring-1 ring-white/70 ${
                chip.flag === "out" ? "bg-card-red" : "bg-card-yellow"
              }`}
              role="img"
              aria-label={chip.flag === "out" ? "unavailable" : "doubt"}
              title={chip.flag === "out" ? "Out / suspended" : "Minutes doubt"}
            />
          )}
        </span>

        <span
          className={`mt-0.5 block overflow-hidden shadow-sm transition-shadow ${
            small ? "rounded-[4px]" : "rounded-[6px]"
          } ${highlighted ? "chip-highlight relative z-10" : ""} ${
            onClick ? "group-hover:shadow-md" : ""
          } ${bench ? "ring-line ring-1" : ""}`}
        >
          <span
            className={`bg-chalk text-ink block truncate px-0.5 font-chip font-semibold ${
              small ? "text-[8.5px] leading-[13px]" : "text-[10.5px] leading-4"
            }`}
          >
            {chipName(chip.player)}
          </span>

          {chip.fixtures ? (
            <span
              className="bg-deep flex justify-center gap-px px-px py-[2px]"
              aria-label="next fixtures difficulty"
            >
              {chip.fixtures.slice(0, 3).map((f, i) => (
                <span
                  key={i}
                  className="min-w-0 flex-1 rounded-[2px] font-mono text-[8px] leading-3"
                  style={{ background: diffBg(f.difficulty), color: diffFg(f.difficulty) }}
                  title={`GW${f.gw} ${f.home ? "vs" : "@"} ${f.opponent}`}
                >
                  {diffBand(f.difficulty)}
                </span>
              ))}
            </span>
          ) : chip.primary != null ? (
            <span
              className={`bg-deep text-chalk block font-mono font-semibold ${
                small ? "text-[8.5px] leading-[13px]" : "text-[10px] leading-4"
              }`}
            >
              {chip.primary}
            </span>
          ) : null}

          {!small && chip.price != null && (
            <span className="bg-paper-2 text-slate block truncate text-[8px] leading-[13px]">
              {teamAbbrev(chip.team)} · {fmtPrice(chip.price)}
            </span>
          )}
        </span>
      </button>

      {edit && onRemove && (
        <button
          onClick={() => onRemove(chip)}
          className="bg-ink text-chalk absolute -top-1.5 -right-1.5 flex h-5 w-5 items-center justify-center rounded-full text-[10px] leading-none shadow"
          aria-label={`Remove ${chip.player}`}
        >
          ×
        </button>
      )}
    </div>
  );
}

function Badge({
  children,
  label,
  muted,
}: {
  children: React.ReactNode;
  label: string;
  muted?: boolean;
}) {
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={`font-chip absolute -top-1 -right-1.5 flex h-4.5 w-4.5 items-center justify-center rounded-full text-[9px] font-bold shadow ${
        muted ? "bg-chalk text-ink ring-ink/30 ring-1" : "bg-ink text-neon"
      }`}
    >
      {children}
    </span>
  );
}

/** Two-tone mow stripes, chalk lines, and a floodlight vignette. GK end at
 * the top like the tactics wall. */
function PitchSurface() {
  const id = useId().replace(/[^a-zA-Z0-9-]/g, "");
  return (
    <svg
      className="absolute inset-0 h-full w-full"
      viewBox="0 0 100 120"
      preserveAspectRatio="none"
      aria-hidden
    >
      <defs>
        <radialGradient id={`glow-${id}`} cx="50%" cy="42%" r="65%">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.09" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`vig-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#03140a" stopOpacity="0.28" />
          <stop offset="22%" stopColor="#03140a" stopOpacity="0" />
          <stop offset="78%" stopColor="#03140a" stopOpacity="0" />
          <stop offset="100%" stopColor="#03140a" stopOpacity="0.3" />
        </linearGradient>
      </defs>
      {[...Array(8)].map((_, i) => (
        <rect
          key={i}
          x="0"
          y={i * 15}
          width="100"
          height="15"
          fill={i % 2 === 0 ? "var(--color-pitch)" : "var(--color-pitch-light)"}
        />
      ))}
      <rect x="0" y="0" width="100" height="120" fill={`url(#glow-${id})`} />
      <rect x="0" y="0" width="100" height="120" fill={`url(#vig-${id})`} />
      <g stroke="var(--color-chalk)" strokeOpacity="0.45" strokeWidth="0.5" fill="none">
        <rect x="2" y="2" width="96" height="116" />
        <line x1="2" y1="60" x2="98" y2="60" />
        <circle cx="50" cy="60" r="10" />
        <rect x="26" y="2" width="48" height="14" />
        <rect x="38" y="2" width="24" height="5.5" />
        <rect x="26" y="104" width="48" height="14" />
        <rect x="38" y="112.5" width="24" height="5.5" />
      </g>
    </svg>
  );
}
