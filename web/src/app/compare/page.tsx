import { HydrationBoundary } from "@tanstack/react-query";
import { prefetchEngine } from "@/lib/engine-server";
import { pageMetadata } from "@/lib/seo";
import CompareClient from "./CompareClient";

export const revalidate = 3600;

export const metadata = pageMetadata({
  title: "Compare Teams",
  description:
    "Upload screenshots of FPL squads and let the engine rate and compare them — best XI, captain, and the gap to optimal for each.",
  path: "/compare",
});

export default async function ComparePage() {
  return (
    <HydrationBoundary state={await prefetchEngine("explorer", "meta")}>
      <CompareClient />
    </HydrationBoundary>
  );
}
