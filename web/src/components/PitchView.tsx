"use client";

/** The Board (UI_PLAN §4): the pitch is the primary analytical instrument.
 * SVG surface (stripes + chalk), chips as real positioned buttons so focus
 * order and touch targets come free. GK row at the top, bench strip below. */

import { useApp } from "@/lib/store";
import { chipName, diffBand, diffBg, diffFg, price as fmtPrice, teamAbbrev } from "@/lib/format";
import type { FixtureCell, Position } from "@/lib/types";

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
      <div className="relative w-full overflow-hidden rounded-lg" style={{ aspectRatio: "10 / 12" }}>
        <PitchSurface />
        {rows.map((row, ri) =>
          row.map((slot, si) => {
            const x = ((si + 1) / (row.length + 1)) * 100;
            const y = ROW_Y[ri] ?? 50;
            // cap width by row density so 5-across chips never overlap (badges sit outside the chip edge)
            const w = Math.min(small ? 26 : 19, 100 / (row.length + 1) - 1.2);
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
                    className="border-chalk/60 text-chalk/80 hover:border-chalk hover:text-chalk w-full rounded-md border-2 border-dashed bg-transparent py-2.5 text-center"
                    aria-label={`Add a ${slot.position}`}
                  >
                    <span className="font-chip block text-sm leading-none">+</span>
                    <span className="font-chip block text-[9px]">{slot.position}</span>
                  </button>
                )}
              </div>
            );
          }),
        )}
      </div>

      {bench && bench.length > 0 && (
        <div className="mt-2">
          <div className="text-slate mb-1 font-mono text-[10px] uppercase tracking-wide">
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
        className={`bg-chalk text-ink w-full rounded-md border text-center shadow-sm transition-shadow ${
          bench ? "border-line" : "border-transparent"
        } ${highlighted ? "chip-highlight relative z-10" : ""} ${
          onClick ? "hover:shadow-md" : "cursor-default"
        } ${small ? "px-0.5 py-1" : "px-1 py-1.5"}`}
        aria-label={`${chip.player}, ${chip.team}, ${chip.position}`}
      >
        <span
          className={`font-chip block truncate font-semibold leading-tight ${
            small ? "text-[9px]" : "text-[11px]"
          }`}
        >
          {chipName(chip.player)}
        </span>

        {chip.fixtures ? (
          <span className="my-0.5 flex justify-center gap-px" aria-label="next fixtures difficulty">
            {chip.fixtures.slice(0, 3).map((f, i) => (
              <span
                key={i}
                className="rounded-[2px] px-0.5 font-mono text-[8px] leading-3"
                style={{ background: diffBg(f.difficulty), color: diffFg(f.difficulty) }}
                title={`GW${f.gw} ${f.home ? "vs" : "@"} ${f.opponent}`}
              >
                {diffBand(f.difficulty)}
              </span>
            ))}
          </span>
        ) : chip.primary != null ? (
          <span className={`block font-mono font-semibold leading-tight ${small ? "text-[10px]" : "text-sm"}`}>
            {chip.primary}
          </span>
        ) : null}

        {!small && (
          <span className="text-slate block truncate text-[8.5px] leading-tight">
            {teamAbbrev(chip.team)}
            {chip.price != null ? ` · ${fmtPrice(chip.price)}` : ""}
          </span>
        )}
      </button>

      {chip.captain && <Badge label="Captain">C</Badge>}
      {chip.vice && !chip.captain && (
        <Badge label="Vice-captain" muted>
          V
        </Badge>
      )}
      {chip.flag && (
        <span
          className={`absolute -top-1 -left-1 block h-2.5 w-2.5 rounded-full ${
            chip.flag === "out" ? "bg-card-red" : "bg-card-yellow"
          }`}
          role="img"
          aria-label={chip.flag === "out" ? "unavailable" : "doubt"}
          title={chip.flag === "out" ? "Out / suspended" : "Minutes doubt"}
        />
      )}

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
      className={`absolute -top-1.5 -right-1.5 flex h-4.5 w-4.5 items-center justify-center rounded-full font-chip text-[9px] font-bold shadow ${
        muted ? "bg-chalk text-ink border-slate border" : "bg-armband text-ink"
      }`}
    >
      {children}
    </span>
  );
}

/** Two-tone mow stripes + chalk lines. GK end at the top like the tactics wall. */
function PitchSurface() {
  return (
    <svg
      className="absolute inset-0 h-full w-full"
      viewBox="0 0 100 120"
      preserveAspectRatio="none"
      aria-hidden
    >
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
      <g stroke="var(--color-chalk)" strokeOpacity="0.4" strokeWidth="0.5" fill="none">
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
