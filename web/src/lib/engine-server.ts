import { QueryClient, dehydrate, type DehydratedState } from "@tanstack/react-query";
import type { ExplorerData, ProjectionsResponse, RatingExplain } from "./types";

/** Server-side data access for the FastAPI engine.
 *
 * The browser reaches the engine through the `/api/engine` rewrite; on the
 * server we hit it directly via the same env var the rewrite is built from.
 * Pages prefetch here and hand the dehydrated cache to their client
 * component, so the first-paint HTML (and what crawlers index) carries real
 * engine data instead of a loading shell. */

const ENGINE = process.env.ENGINE_API_URL ?? "http://127.0.0.1:8000";

/** GETs sit in Next's Data Cache for an hour (the engine's snapshot
 * cadence), so the ~600 player-profile revalidations share one /explorer
 * fetch instead of each hitting the engine. */
async function engineGet<T>(path: string): Promise<T> {
  const res = await fetch(`${ENGINE}${path}`, { next: { revalidate: 3600 } });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const getExplorer = () => engineGet<ExplorerData>("/explorer");

export const getRating = (name: string) =>
  engineGet<RatingExplain>(`/players/${encodeURIComponent(name)}/rating`);

/** POSTs are never data-cached — this runs once per page revalidation. */
export async function getProjections(names: string[]): Promise<ProjectionsResponse> {
  const res = await fetch(`${ENGINE}/projections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ players: names }),
  });
  if (!res.ok) throw new Error(`/projections → ${res.status}`);
  return res.json() as Promise<ProjectionsResponse>;
}

/** The cacheable GETs, keyed exactly as lib/hooks.ts queries them — the
 * dehydrated entries only hydrate client-side if these keys match. */
const ENGINE_QUERIES = {
  meta: { queryKey: ["meta"], path: "/meta" },
  explorer: { queryKey: ["explorer"], path: "/explorer" },
  fixturesMatrix: { queryKey: ["fixtures-matrix"], path: "/fixtures-matrix" },
  accuracy: { queryKey: ["accuracy"], path: "/accuracy" },
} as const;

/** Fetch the named queries and return a dehydrated cache for
 * `<HydrationBoundary>`. Failure handling follows the deploy story:
 * - `next build` with the engine down (local build, first Railway seed):
 *   warn and ship the loading shell — never fail the build.
 * - dev server: same — the client fetch takes over exactly as before.
 * - production ISR revalidation: rethrow, so a seeding/down engine keeps
 *   the last good page instead of caching an hour of empty shell. */
export async function prefetchEngine(
  ...names: (keyof typeof ENGINE_QUERIES)[]
): Promise<DehydratedState> {
  const swallowErrors =
    process.env.NODE_ENV !== "production" ||
    process.env.NEXT_PHASE === "phase-production-build";
  const qc = new QueryClient();
  await Promise.all(
    names.map(async (name) => {
      const { queryKey, path } = ENGINE_QUERIES[name];
      try {
        await qc.fetchQuery({ queryKey, queryFn: () => engineGet(path) });
      } catch (err) {
        if (!swallowErrors) throw err;
        console.warn(`[engine prefetch] ${path} unavailable — rendering without data (${err})`);
      }
    }),
  );
  return dehydrate(qc);
}
