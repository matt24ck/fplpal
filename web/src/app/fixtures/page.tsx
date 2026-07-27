import { HydrationBoundary } from "@tanstack/react-query";
import { prefetchEngine } from "@/lib/engine-server";
import { pageMetadata } from "@/lib/seo";
import FixturesClient from "./FixturesClient";

/** Re-render at most hourly — the cadence of the engine's snapshot job. */
export const revalidate = 3600;

export const metadata = pageMetadata({
  title: "Fixture Difficulty Matrix",
  description:
    "Team-by-gameweek fixture difficulty straight from the FPL Pal model — every cell carries its number, double gameweeks stack and blanks are marked.",
  path: "/fixtures",
});

export default async function FixturesPage() {
  return (
    <HydrationBoundary state={await prefetchEngine("fixturesMatrix", "meta")}>
      <FixturesClient />
    </HydrationBoundary>
  );
}
