import type { MetadataRoute } from "next";
import { getExplorer } from "@/lib/engine-server";
import { SITE_URL } from "@/lib/seo";
import { assignSlugs } from "@/lib/slug";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const route = (
    path: string,
    changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"],
    priority: number,
  ) => ({ url: `${SITE_URL}${path}`, changeFrequency, priority });

  const base = [
    route("/", "hourly", 1),
    route("/players", "hourly", 0.9),
    route("/fixtures", "daily", 0.8),
    route("/builder", "weekly", 0.7),
    route("/accuracy", "daily", 0.7),
    route("/planner", "weekly", 0.6),
    route("/about", "monthly", 0.5),
    route("/chat", "monthly", 0.3),
  ];

  try {
    const explorer = await getExplorer();
    const profiles = [...assignSlugs(explorer.players).values()].map((slug) =>
      route(`/players/${slug}`, "daily", 0.6),
    );
    return [...base, ...profiles];
  } catch {
    // engine unreachable (local build, first seed) — ship the static routes
    return base;
  }
}
