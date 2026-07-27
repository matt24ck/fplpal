import { pageMetadata } from "@/lib/seo";
import BuilderClient from "./BuilderClient";

export const metadata = pageMetadata({
  title: "Squad Builder",
  description:
    "Build a legal FPL squad with live budget and rule checks, let the optimizer fill or repair your draft, and rate it against the best possible fifteen.",
  path: "/builder",
});

export default function BuilderPage() {
  return <BuilderClient />;
}
