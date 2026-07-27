import { HydrationBoundary } from "@tanstack/react-query";
import { prefetchEngine } from "@/lib/engine-server";
import { pageMetadata } from "@/lib/seo";
import HomeClient from "./HomeClient";

/** Re-render at most hourly — the cadence of the engine's snapshot job. */
export const revalidate = 3600;

export const metadata = pageMetadata({
  title: "FPL Pal — your pal who does the maths",
  description:
    "FPL projections, ratings and optimal squads computed by a statistical engine — explained by Pal, an AI assistant that never invents a number.",
  path: "/",
  absoluteTitle: true,
});

export default async function MyTeamPage() {
  return (
    <HydrationBoundary state={await prefetchEngine("explorer", "meta")}>
      <HomeClient />
    </HydrationBoundary>
  );
}
