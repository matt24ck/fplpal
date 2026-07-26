"use client";

/** Slot picker: position-filtered pool sorted by rating, with search.
 * Constraint troubles (club limit, budget) are explained on the row, never
 * silently blocked. */

import { useEffect, useMemo, useRef, useState } from "react";
import { price, pts, teamAbbrev } from "@/lib/format";
import { useExplorer } from "@/lib/hooks";
import type { ExplorerPlayer, Position } from "@/lib/types";

export function PlayerPicker({
  position,
  onClose,
  onPick,
  squad,
  maxPerClub,
  remaining,
}: {
  position: Position | null;
  onClose: () => void;
  onPick: (p: ExplorerPlayer) => void;
  squad: ExplorerPlayer[];
  maxPerClub: number;
  remaining: number; // tenths
}) {
  const { data } = useExplorer();
  const [q, setQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (position) {
      setQ("");
      inputRef.current?.focus();
    }
  }, [position]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const inSquad = useMemo(() => new Set(squad.map((p) => p.code)), [squad]);
  const clubCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of squad) m.set(p.team, (m.get(p.team) ?? 0) + 1);
    return m;
  }, [squad]);

  const pool = useMemo(() => {
    if (!data || !position) return [];
    const needle = q.trim().toLowerCase();
    return data.players
      .filter((p) => p.position === position)
      .filter(
        (p) =>
          !needle ||
          p.player.toLowerCase().includes(needle) ||
          p.team.toLowerCase().includes(needle),
      )
      .sort((a, b) => (b.rating ?? -1) - (a.rating ?? -1))
      .slice(0, 60);
  }, [data, position, q]);

  if (!position) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true" aria-label={`Pick a ${position}`}>
      <button aria-label="Close" className="absolute inset-0 bg-ink/30" onClick={onClose} />
      <div className="bg-paper relative flex max-h-[85dvh] w-full max-w-lg flex-col rounded-t-xl shadow-2xl sm:rounded-xl">
        <div className="border-line flex items-center gap-3 border-b p-3">
          <h2 className="font-chip text-sm font-semibold tracking-wide">Pick a {position}</h2>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search name or club"
            aria-label="Search players"
            className="border-line bg-chalk min-w-0 flex-1 rounded-md border px-3 py-1.5 text-sm"
          />
          <button onClick={onClose} className="text-slate px-1 text-xl leading-none" aria-label="Close picker">
            ×
          </button>
        </div>
        <ul className="overflow-y-auto p-1.5">
          {pool.map((p) => {
            const dup = inSquad.has(p.code);
            const clubFull = (clubCounts.get(p.team) ?? 0) >= maxPerClub;
            const busts = p.price > remaining;
            return (
              <li key={p.code}>
                <button
                  disabled={dup}
                  onClick={() => {
                    onPick(p);
                    onClose();
                  }}
                  className="hover:bg-paper-2 flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left text-sm disabled:opacity-40"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{p.player}</span>
                    <span className="text-slate block text-xs">
                      {teamAbbrev(p.team)}
                      {dup
                        ? " · already in your squad"
                        : clubFull
                          ? ` · would be ${(clubCounts.get(p.team) ?? 0) + 1}× ${p.team} (limit ${maxPerClub})`
                          : busts
                            ? ` · busts the budget by ${price(p.price - Math.max(0, remaining))}`
                            : ""}
                    </span>
                  </span>
                  <span className="font-mono text-xs">{price(p.price)}</span>
                  <span className="w-12 text-right font-mono text-xs">{pts(p.xpts)} pts</span>
                  <span
                    className="bg-paper-2 w-9 rounded py-0.5 text-center font-mono text-xs font-semibold"
                    title="Engine rating 0–100"
                  >
                    {p.rating ?? "—"}
                  </span>
                </button>
              </li>
            );
          })}
          {pool.length === 0 && (
            <li className="text-slate p-4 text-center text-sm">
              No {position} matches “{q}”.
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
