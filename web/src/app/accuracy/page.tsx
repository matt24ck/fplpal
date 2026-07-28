import { HydrationBoundary } from "@tanstack/react-query";
import { prefetchEngine } from "@/lib/engine-server";
import { pageMetadata } from "@/lib/seo";
import AccuracyClient from "./AccuracyClient";

/** Re-render at most hourly — the cadence of the engine's snapshot job. */
export const revalidate = 3600;

export const metadata = pageMetadata({
  title: "Model Accuracy",
  description:
    "Every gameweek's projections are frozen at the deadline and scored against what actually happened — side by side with FPL's own expected points. The receipts, in public.",
  path: "/accuracy",
});

export default async function AccuracyPage() {
  return (
    <HydrationBoundary state={await prefetchEngine("accuracy", "meta")}>
      <AccuracyClient />
    </HydrationBoundary>
  );
}
