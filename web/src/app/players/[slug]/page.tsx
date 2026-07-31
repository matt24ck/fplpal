import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { BasisBadge } from "@/components/BasisBadge";
import { Shirt } from "@/components/Shirt";
import {
  DecompositionChart,
  FixtureTickerStrip,
  RatingDial,
  SubScoreBars,
} from "@/components/viz";
import { getExplorer, getProjections, getRating } from "@/lib/engine-server";
import { SUBSCORES, SUBSCORE_LABELS, chipName, price, pts, teamAbbrev } from "@/lib/format";
import { SITE_URL, pageMetadata } from "@/lib/seo";
import { assignSlugs } from "@/lib/slug";
import type { ExplorerData, ExplorerPlayer } from "@/lib/types";

/** One public, crawlable page per player: the projection decomposed, with
 * its provenance — the engine doing its own selling. Server-rendered from
 * the engine and revalidated hourly like the rest of the data pages. */

export const revalidate = 3600;
// generateStaticParams comes back empty when the engine is unreachable at
// build time (local build, first Railway seed) — profiles then generate on
// first request instead of failing the build.
export const dynamicParams = true;

async function resolve(
  slug: string,
): Promise<{ explorer: ExplorerData; player: ExplorerPlayer } | null> {
  const explorer = await getExplorer();
  const slugs = assignSlugs(explorer.players);
  for (const p of explorer.players) {
    if (slugs.get(p.code) === slug) return { explorer, player: p };
  }
  return null;
}

export async function generateStaticParams() {
  try {
    const explorer = await getExplorer();
    return [...assignSlugs(explorer.players).values()].map((slug) => ({ slug }));
  } catch {
    return [];
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  let hit: Awaited<ReturnType<typeof resolve>> = null;
  try {
    hit = await resolve(slug);
  } catch {
    // engine unreachable — the page render will surface the error
  }
  if (!hit) return { title: "Player not found" };
  const { explorer, player: p } = hit;
  const [a, b] = explorer.provenance.gw_window;
  return pageMetadata({
    title: `${p.player} FPL Projection & Rating`,
    description: `${p.player} (${p.team}, ${p.position}, ${price(p.price)}) projects ${pts(p.xpts)} FPL points over GW${a}–${b}${p.rating != null ? ` with a ${p.rating}/100 rating` : ""}. Expected points decomposed by source — recomputed hourly by the FPL Pal engine.`,
    path: `/players/${slug}`,
  });
}

export default async function PlayerPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const hit = await resolve(slug);
  if (!hit) notFound();
  const { explorer, player: p } = hit;

  // Rating prose and the per-GW decomposition are enrichments — the page
  // still stands (and caches) without them if either endpoint hiccups.
  const [ratingRes, projRes] = await Promise.allSettled([
    getRating(p.player),
    getProjections([p.player]),
  ]);
  const rating = ratingRes.status === "fulfilled" ? ratingRes.value : null;
  const perGw =
    projRes.status === "fulfilled"
      ? (projRes.value.projections[0]?.per_gw ?? null)
      : null;

  const fixtures = explorer.fixtures[p.team] ?? [];
  const [a, b] = explorer.provenance.gw_window;
  const url = `${SITE_URL}/players/${slug}`;

  const gwRows = perGw
    ? perGw.map((g) => ({
        gw: g.gw,
        fixture: `${g.home ? "" : "@"}${teamAbbrev(g.opponent)}`,
        xpts: g.xpts,
        ceiling: g.ceiling as number | null,
      }))
    : Object.entries(p.gw_xpts)
        .map(([gw, x]) => {
          const fx = fixtures.filter((f) => f.gw === Number(gw));
          return {
            gw: Number(gw),
            fixture: fx.length
              ? fx.map((f) => `${f.home ? "" : "@"}${teamAbbrev(f.opponent)}`).join(" + ")
              : "—",
            xpts: x,
            ceiling: null,
          };
        })
        .sort((r1, r2) => r1.gw - r2.gw);

  const jsonLd = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Person",
        name: p.player,
        url,
        jobTitle: "Professional footballer",
        memberOf: { "@type": "SportsTeam", name: p.team, sport: "Association football" },
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Players", item: `${SITE_URL}/players` },
          { "@type": "ListItem", position: 2, name: p.player, item: url },
        ],
      },
    ],
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <nav className="mb-4 text-sm">
        <Link href="/players" className="text-royal font-medium">
          ← All players
        </Link>
      </nav>

      <header className="flex items-start gap-4">
        <Shirt team={p.team} className="w-14 shrink-0" />
        <div>
          <h1 className="font-hero text-3xl leading-tight tracking-tight">{p.player}</h1>
          <p className="text-slate mt-0.5 text-sm">
            <Link
              href={`/players?team=${encodeURIComponent(p.team)}`}
              className="hover:text-ink underline-offset-2 hover:underline"
            >
              {p.team}
            </Link>
            {" · "}
            {p.position}
            {" · "}
            <span className="font-mono">{price(p.price)}</span>
          </p>
          <BasisBadge basis={p.data_basis} className="mt-2" />
        </div>
      </header>

      <section className="mt-5 flex items-center gap-6">
        <RatingDial rating={p.rating} size={84} />
        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-3">
          <Stat label={`xPts GW${a}–${b}`} value={pts(p.xpts)} />
          <Stat label="Start likelihood" value={`${Math.round(p.p_play * 100)}%`} />
          <Stat label="xPts / £m" value={pts(p.xpts / (p.price / 10), 2)} />
        </div>
      </section>

      <Section title="Why this rating">
        {rating && <p className="mb-3 max-w-prose text-sm">{rating.note}</p>}
        {rating && (
          <p className="text-slate mb-3 text-xs">
            Strongest: {SUBSCORE_LABELS[rating.strongest] ?? rating.strongest} · Weakest:{" "}
            {SUBSCORE_LABELS[rating.weakest] ?? rating.weakest}
          </p>
        )}
        <SubScoreBars subScores={p.sub_scores} order={SUBSCORES[p.position]} />
      </Section>

      <Section title="Expected points by source">
        {perGw ? (
          <DecompositionChart perGw={perGw} />
        ) : (
          <p className="text-slate text-sm">decomposition temporarily unavailable</p>
        )}
        <div className="border-line mt-4 overflow-hidden rounded-lg border">
          <table className="bg-chalk w-full border-collapse text-sm">
            <thead>
              <tr className="border-line text-slate border-b text-left text-xs">
                <th className="px-3 py-2 font-medium">GW</th>
                <th className="px-3 py-2 font-medium">Fixture</th>
                <th className="px-3 py-2 text-right font-medium">xPts</th>
                {perGw && <th className="px-3 py-2 text-right font-medium">Ceiling</th>}
              </tr>
            </thead>
            <tbody>
              {gwRows.map((r, i) => (
                <tr key={i} className="border-line border-b last:border-0">
                  <td className="px-3 py-1.5 font-mono text-xs">{r.gw}</td>
                  <td className="px-3 py-1.5 text-xs">{r.fixture}</td>
                  <td className="px-3 py-1.5 text-right font-mono text-xs font-semibold">
                    {pts(r.xpts)}
                  </td>
                  {perGw && (
                    <td className="text-slate px-3 py-1.5 text-right font-mono text-xs">
                      {pts(r.ceiling)}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Fixture run · model difficulty">
        <FixtureTickerStrip fixtures={fixtures} n={6} />
        <p className="text-slate mt-1.5 text-[10px]">1 easiest – 5 hardest · * = away</p>
      </Section>

      <section className="mt-7">
        <Link
          href="/chat"
          className="btn-primary inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm"
        >
          Ask Pal about {chipName(p.player)}
        </Link>
      </section>

      <p className="text-slate border-line mt-8 border-t pt-3 font-mono text-[10px]">
        season {explorer.provenance.season} · computed{" "}
        {explorer.provenance.computed_at.slice(0, 16).replace("T", " ")} · snapshot{" "}
        {explorer.provenance.data_snapshot} · recomputed hourly
      </p>

      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-7">
      <h2 className="font-chip text-slate mb-2 text-xs font-semibold tracking-wide">{title}</h2>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-slate text-[10px] uppercase tracking-wide">{label}</div>
      <div className="font-mono text-base font-semibold">{value}</div>
    </div>
  );
}
