import { HydrationBoundary } from "@tanstack/react-query";
import { prefetchEngine } from "@/lib/engine-server";
import { pageMetadata } from "@/lib/seo";
import PlayersClient from "./PlayersClient";

/** Re-render at most hourly — the cadence of the engine's snapshot job. */
export const revalidate = 3600;

export const metadata = pageMetadata({
  title: "Player Ratings & Projections",
  description:
    "Every Premier League player rated and projected for the 2026/27 FPL season — sortable position-specific sub-scores, a fixture ticker and full point breakdowns.",
  path: "/players",
});

export default async function PlayersPage() {
  return (
    <HydrationBoundary state={await prefetchEngine("explorer", "meta")}>
      <PlayersClient />
    </HydrationBoundary>
  );
}
