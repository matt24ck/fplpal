import { pageMetadata } from "@/lib/seo";
import PlannerClient from "./PlannerClient";

export const metadata = pageMetadata({
  title: "Transfer Planner",
  description:
    "Plan transfers and chip timing across the coming gameweeks, with engine projections behind every decision.",
  path: "/planner",
});

export default function PlannerPage() {
  return <PlannerClient />;
}
