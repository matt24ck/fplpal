"use client";

/** Planner — in-season home of the transfer plan and chip timeline. Before
 * GW1 it explains why there's nothing to plan yet (honest state, not an
 * error), and points at the Squad Builder. */

import Link from "next/link";
import { PageShell } from "@/components/PageShell";
import { ChipsCard } from "@/components/ChipsCard";
import { useMeta } from "@/lib/hooks";

export default function PlannerPage() {
  const { data } = useMeta();
  return (
    <PageShell title="Planner">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="border-line bg-chalk rounded-lg border p-5">
          <h3 className="font-chip text-sm font-semibold tracking-wide">
            Planning unlocks after GW1
          </h3>
          <p className="text-slate mt-2 text-sm leading-relaxed">
            Transfers are unlimited before the season starts, so there is nothing to
            optimize yet — reshape your squad freely in the Squad Builder. The
            multi-gameweek transfer planner ships by GW2, and chip timing advice
            around GW4, each computed by the engine when they first become relevant.
          </p>
          <Link
            href="/builder"
            className="bg-pitch-deep text-chalk mt-4 inline-block rounded-md px-4 py-2 text-sm font-medium"
          >
            Open the Squad Builder
          </Link>
          {data?.next_deadline && (
            <p className="text-slate mt-3 font-mono text-xs">
              GW{data.next_deadline.gw} deadline:{" "}
              {new Date(data.next_deadline.deadline_time).toLocaleString()}
            </p>
          )}
        </div>
        <ChipsCard />
      </div>
    </PageShell>
  );
}
