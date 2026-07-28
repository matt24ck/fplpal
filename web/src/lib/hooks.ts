"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { useApp } from "./store";
import type { ExplorerPlayer, Position, TeamState } from "./types";
import { POSITIONS } from "./format";

export const useMeta = () => useQuery({ queryKey: ["meta"], queryFn: api.meta });

export const useExplorer = () =>
  useQuery({ queryKey: ["explorer"], queryFn: api.explorer });

export const useFixturesMatrix = () =>
  useQuery({ queryKey: ["fixtures-matrix"], queryFn: api.fixturesMatrix });

export const usePlayerProjection = (player: string | null) =>
  useQuery({
    queryKey: ["projection", player],
    queryFn: () => api.projections([player!]),
    enabled: player !== null,
  });

/** The draft joined to player rows, grouped by position (slot order stable). */
export function useDraftSquad(): {
  byPos: Record<Position, ExplorerPlayer[]>;
  players: ExplorerPlayer[];
  names: string[];
  complete: boolean;
  ready: boolean;
} {
  const { draft, hydrated } = useApp();
  const { data } = useExplorer();
  const byCode = new Map<number, ExplorerPlayer>(
    (data?.players ?? []).map((p) => [p.code, p]),
  );
  const players = draft.map((c) => byCode.get(c)).filter((p): p is ExplorerPlayer => !!p);
  const byPos: Record<Position, ExplorerPlayer[]> = { GKP: [], DEF: [], MID: [], FWD: [] };
  for (const p of players) byPos[p.position].push(p);
  return {
    byPos,
    players,
    names: players.map((p) => p.player),
    complete:
      players.length === 15 &&
      POSITIONS.every(
        (pos) => byPos[pos].length === { GKP: 2, DEF: 5, MID: 5, FWD: 3 }[pos],
      ),
    ready: hydrated && !!data,
  };
}

/** The user's real FPL team, imported from their saved team ID. Returns the
 * honest `pending` state until FPL makes picks public (first deadline). */
export function useTeamState(teamId: string | null) {
  return useQuery<TeamState>({
    queryKey: ["team", teamId],
    queryFn: () => api.team(teamId!),
    enabled: !!teamId,
    staleTime: 5 * 60_000,
    retry: false, // a bad ID 404s — don't hammer the FPL API
  });
}

/** Rate the current 15 — powers My Team's XI/captain view. */
export function useDraftLineup(names: string[], complete: boolean) {
  return useQuery({
    queryKey: ["rate", ...names.slice().sort()],
    queryFn: () => api.rateDraft(names),
    enabled: complete,
    staleTime: 5 * 60_000,
  });
}
