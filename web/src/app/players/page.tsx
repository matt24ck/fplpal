"use client";

/** Players explorer (UI_PLAN §3.4): the analyst's spreadsheet. Position tabs
 * each show their own sub-score columns; sortable; fixture mini-ticker per
 * row; row click opens the drawer. */

import { Suspense, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { PageShell } from "@/components/PageShell";
import { PlayerDrawer } from "@/components/PlayerDrawer";
import { Shirt } from "@/components/Shirt";
import { FixtureTickerStrip } from "@/components/viz";
import { POSITIONS, SUBSCORES, SUBSCORE_LABELS, price, pts, teamAbbrev } from "@/lib/format";
import { useExplorer } from "@/lib/hooks";
import type { ExplorerPlayer, Position } from "@/lib/types";

export default function PlayersPage() {
  return (
    <Suspense>
      <Explorer />
    </Suspense>
  );
}

const MOBILE_SORTS = [
  { value: "xpts", label: "xPts" },
  { value: "price", label: "Price" },
  { value: "rating", label: "Rating" },
  { value: "value", label: "xPts/£m" },
];

/** The one number the mobile card leads with — whatever it's sorted by. */
function mobileStat(p: ExplorerPlayer, sortKey: string): { value: string; label: string } {
  switch (sortKey) {
    case "price":
      return { value: price(p.price), label: "price" };
    case "rating":
      return { value: String(p.rating ?? "—"), label: "rating" };
    case "value":
      return { value: pts(p.xpts / (p.price / 10), 2), label: "xPts/£m" };
    default:
      return { value: pts(p.xpts), label: "xPts" };
  }
}

function Explorer() {
  const { data, isLoading } = useExplorer();
  const params = useSearchParams();
  const teamFilter = params.get("team");
  const [pos, setPos] = useState<Position>("MID");
  const [q, setQ] = useState("");
  const [sortKey, setSortKey] = useState<string>("xpts");
  const [sortDir, setSortDir] = useState<1 | -1>(-1);
  const [selected, setSelected] = useState<ExplorerPlayer | null>(null);

  const subs = SUBSCORES[pos];

  const rows = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    const val = (p: ExplorerPlayer): number | string => {
      switch (sortKey) {
        case "player": return p.player;
        case "price": return p.price;
        case "xpts": return p.xpts;
        case "rating": return p.rating ?? -1;
        case "value": return p.xpts / (p.price / 10);
        case "p_play": return p.p_play;
        default: return p.sub_scores[sortKey] ?? -1;
      }
    };
    return data.players
      .filter((p) => p.position === pos)
      .filter((p) => !teamFilter || p.team === teamFilter)
      .filter(
        (p) =>
          !needle ||
          p.player.toLowerCase().includes(needle) ||
          p.team.toLowerCase().includes(needle),
      )
      .sort((a, b) => {
        const va = val(a);
        const vb = val(b);
        const c = typeof va === "string" ? va.localeCompare(vb as string) : (va as number) - (vb as number);
        return c * sortDir;
      })
      .slice(0, 120);
  }, [data, pos, q, sortKey, sortDir, teamFilter]);

  const sort = (key: string) => {
    if (sortKey === key) setSortDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(key);
      setSortDir(key === "player" ? 1 : -1);
    }
  };

  const arrow = (key: string) => (sortKey === key ? (sortDir === -1 ? " ↓" : " ↑") : "");

  return (
    <PageShell title="Players">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Position" className="border-line bg-paper-2 flex rounded-full border p-0.5">
          {POSITIONS.map((p) => (
            <button
              key={p}
              role="tab"
              aria-selected={pos === p}
              onClick={() => {
                setPos(p);
                if (!["player", "price", "xpts", "rating", "value", "p_play"].includes(sortKey))
                  setSortKey("xpts");
              }}
              className={`rounded-full px-3.5 py-1.5 text-sm font-semibold ${
                pos === p ? "bg-deep text-chalk shadow-sm" : "text-slate hover:text-ink"
              }`}
            >
              {p}
            </button>
          ))}
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search name or club"
          aria-label="Search players"
          className="border-line bg-chalk focus:border-royal min-w-0 flex-1 rounded-full border px-3.5 py-1.5 text-sm outline-none md:w-44 md:flex-none"
        />
        {/* one sort on mobile — the columns do this on desktop */}
        <label className="text-slate flex items-center gap-1.5 text-xs md:hidden">
          Sort
          <select
            value={MOBILE_SORTS.some((s) => s.value === sortKey) ? sortKey : "xpts"}
            onChange={(e) => {
              setSortKey(e.target.value);
              setSortDir(-1);
            }}
            className="border-line bg-chalk text-ink rounded-full border px-2.5 py-1.5 text-sm"
          >
            {MOBILE_SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        {teamFilter && (
          <a href="/players" className="text-royal text-sm font-medium">
            {teamFilter} × clear
          </a>
        )}
      </div>

      {isLoading && <p className="text-slate text-sm">Loading the pool…</p>}

      {/* mobile: tappable cards — shirt, price, run of fixtures, one stat */}
      <div className="border-line overflow-hidden rounded-xl border md:hidden">
        {rows.map((p) => {
          const stat = mobileStat(p, sortKey);
          return (
            <button
              key={p.code}
              onClick={() => setSelected(p)}
              className="border-line bg-chalk flex w-full items-center gap-2.5 border-b px-3 py-2.5 text-left last:border-b-0"
            >
              <Shirt team={p.team} className="w-8 shrink-0" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{p.player}</span>
                <span className="text-slate block text-xs">
                  {teamAbbrev(p.team)} · {price(p.price)}
                </span>
                <span className="mt-1 block">
                  <FixtureTickerStrip fixtures={data?.fixtures[p.team] ?? []} n={3} />
                </span>
              </span>
              <span className="shrink-0 text-right">
                <span className="block font-mono text-base font-semibold">{stat.value}</span>
                <span className="text-slate block text-[10px]">{stat.label}</span>
              </span>
            </button>
          );
        })}
        {rows.length === 0 && !isLoading && (
          <p className="bg-chalk text-slate p-4 text-center text-sm">No matches.</p>
        )}
      </div>

      <div className="border-line hidden overflow-x-auto rounded-lg border md:block">
        <table className="bg-chalk w-full min-w-[760px] border-collapse text-sm">
          <thead>
            <tr className="border-line text-slate border-b text-left text-xs">
              <Th onClick={() => sort("player")} label={`Player${arrow("player")}`} sticky />
              <Th onClick={() => sort("price")} label={`£${arrow("price")}`} num />
              <Th onClick={() => sort("xpts")} label={`xPts${arrow("xpts")}`} num title="Expected points over the projection window" />
              <Th onClick={() => sort("rating")} label={`Rating${arrow("rating")}`} num />
              {subs.map((s) => (
                <Th
                  key={s}
                  onClick={() => sort(s)}
                  label={`${SUBSCORE_LABELS[s]}${arrow(s)}`}
                  num
                  title="Percentile within position"
                />
              ))}
              <Th onClick={() => sort("value")} label={`xPts/£m${arrow("value")}`} num />
              <th className="px-3 py-2 font-medium">Fixtures</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr
                key={p.code}
                onClick={() => setSelected(p)}
                className="border-line hover:bg-paper-2 group cursor-pointer border-b last:border-0"
              >
                <td className="bg-chalk group-hover:bg-paper-2 sticky left-0 px-3 py-1.5">
                  <span className="flex items-center gap-2">
                    <Shirt team={p.team} className="w-6 shrink-0" />
                    <span className="min-w-0">
                      <span className="block max-w-40 truncate font-medium">{p.player}</span>
                      <span className="text-slate text-xs">{teamAbbrev(p.team)}</span>
                    </span>
                  </span>
                </td>
                <Td>{(p.price / 10).toFixed(1)}</Td>
                <Td strong>{pts(p.xpts)}</Td>
                <Td>{p.rating ?? "—"}</Td>
                {subs.map((s) => (
                  <Td key={s} dim>
                    {p.sub_scores[s] ?? "—"}
                  </Td>
                ))}
                <Td>{pts(p.xpts / (p.price / 10), 2)}</Td>
                <td className="px-3 py-1.5">
                  <FixtureTickerStrip fixtures={data?.fixtures[p.team] ?? []} n={4} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-slate mt-2 hidden text-xs md:block">
        Top 120 shown · sub-scores are percentiles within {pos} · click a row for the full
        breakdown.
      </p>
      <p className="text-slate mt-2 text-xs md:hidden">
        Top 120 shown · tap a player for the full breakdown.
      </p>

      <PlayerDrawer player={selected} onClose={() => setSelected(null)} />
    </PageShell>
  );
}

function Th({
  label,
  onClick,
  num,
  sticky,
  title,
}: {
  label: string;
  onClick?: () => void;
  num?: boolean;
  sticky?: boolean;
  title?: string;
}) {
  return (
    <th
      className={`px-3 py-2 font-medium ${num ? "text-right" : ""} ${
        sticky ? "bg-chalk sticky left-0" : ""
      }`}
      title={title}
      aria-sort={undefined}
    >
      {onClick ? (
        <button onClick={onClick} className="hover:text-ink whitespace-nowrap">
          {label}
        </button>
      ) : (
        label
      )}
    </th>
  );
}

function Td({
  children,
  strong,
  dim,
}: {
  children: React.ReactNode;
  strong?: boolean;
  dim?: boolean;
}) {
  return (
    <td
      className={`px-3 py-1.5 text-right font-mono text-xs ${
        strong ? "font-semibold" : ""
      } ${dim ? "text-slate" : ""}`}
    >
      {children}
    </td>
  );
}
