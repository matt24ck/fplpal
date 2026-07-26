"use client";

/** Fixtures matrix (UI_PLAN §3.5): team × GW colored by model difficulty —
 * every cell carries its number; DGW cells stack; blanks are hatched.
 * Click a team → its players in the explorer. */

import Link from "next/link";
import { PageShell } from "@/components/PageShell";
import { Shirt } from "@/components/Shirt";
import { diffBand, diffBg, diffFg, teamAbbrev } from "@/lib/format";
import { useFixturesMatrix } from "@/lib/hooks";

export default function FixturesPage() {
  const { data, isLoading } = useFixturesMatrix();

  return (
    <PageShell title="Fixtures">
      <p className="text-slate mb-3 text-sm">
        Model difficulty — the engine&apos;s net expected goals against, not FPL&apos;s FDR.
        1 easiest – 5 hardest; the number in each cell is the band.
      </p>

      {isLoading && <p className="text-slate text-sm">Computing the matrix…</p>}

      {data && (
        <div className="border-line overflow-x-auto rounded-lg border">
          <table className="bg-chalk w-full min-w-[640px] border-collapse text-sm">
            <thead>
              <tr className="border-line text-slate border-b text-xs">
                <th className="bg-chalk sticky left-0 px-3 py-2 text-left font-medium">Team</th>
                {data.gws.map((gw) => (
                  <th key={gw} className="px-1 py-2 text-center font-medium">
                    GW{gw}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.teams.map(({ team, cells }) => (
                <tr key={team} className="border-line border-b last:border-0">
                  <th className="bg-chalk sticky left-0 px-3 py-1 text-left font-normal">
                    <Link
                      href={`/players?team=${encodeURIComponent(team)}`}
                      className="hover:text-royal flex items-center gap-1.5 font-medium"
                      title={`See ${team} players`}
                    >
                      <Shirt team={team} className="w-5 shrink-0" />
                      {team}
                    </Link>
                  </th>
                  {cells.map((cell, i) => (
                    <td key={i} className="px-0.5 py-0.5 text-center align-middle">
                      {cell.length === 0 ? (
                        <div
                          className="hatched text-slate rounded-[3px] py-2 text-[9px]"
                          title={`GW${data.gws[i]}: blank — no fixture`}
                        >
                          —
                        </div>
                      ) : (
                        <div className="flex flex-col gap-0.5">
                          {cell.map((f, j) => (
                            <div
                              key={j}
                              className="rounded-[3px] px-1 py-1 leading-tight"
                              style={{
                                background: diffBg(f.difficulty),
                                color: diffFg(f.difficulty),
                              }}
                              title={`${f.home ? "Home vs" : "Away at"} ${f.opponent} · xG for ${f.expected_goals_for} · against ${f.expected_goals_against} · CS ${(f.clean_sheet_probability * 100).toFixed(0)}%`}
                            >
                              <span className="font-chip block text-[9px]">
                                {teamAbbrev(f.opponent)}
                                {f.home ? "" : "*"}
                              </span>
                              <span className="block font-mono text-[10px] font-semibold">
                                {diffBand(f.difficulty)}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="text-slate mt-3 flex flex-wrap items-center gap-2 text-xs">
        <span>easier</span>
        {[1, 2, 3, 4, 5].map((b) => (
          <span
            key={b}
            className="w-7 rounded-[3px] py-0.5 text-center font-mono font-semibold"
            style={{
              background: `var(--color-diff-${b})`,
              color: b <= 1 ? "var(--color-ink)" : "var(--color-chalk)",
            }}
          >
            {b}
          </span>
        ))}
        <span>harder</span>
        <span className="ml-3">* = away</span>
      </div>
    </PageShell>
  );
}
