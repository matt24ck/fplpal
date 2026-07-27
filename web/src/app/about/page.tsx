import { HydrationBoundary } from "@tanstack/react-query";
import { prefetchEngine } from "@/lib/engine-server";
import { pageMetadata } from "@/lib/seo";
import AboutClient from "./AboutClient";

/** Re-render at most hourly — the cadence of the engine's snapshot job. */
export const revalidate = 3600;

export const metadata = pageMetadata({
  title: "How It Works",
  description:
    "The modeling stack behind FPL Pal, layer by layer — how expected points are built, how the AI is kept honest, and how it is tested against history.",
  path: "/about",
});

export default async function AboutPage() {
  return (
    <HydrationBoundary state={await prefetchEngine("explorer", "meta")}>
      <AboutClient />
    </HydrationBoundary>
  );
}
