"use client";

/** About / How it works — the pitch for grounded AI. Explains the modeling
 * stack layer by layer and draws the line between "ask a chatbot" and "ask
 * an engine". The example decomposition is LIVE engine output with its
 * provenance — the marketing page holds itself to the product's standard. */

import Link from "next/link";
import { useMemo } from "react";
import { DecompositionChart } from "@/components/viz";
import { pts } from "@/lib/format";
import { useExplorer, usePlayerProjection } from "@/lib/hooks";

export default function AboutPage() {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6">
      <p className="font-chip text-pitch-deep text-xs font-semibold tracking-wide">
        How it works
      </p>
      <h1 className="font-hero mt-2 text-3xl leading-tight sm:text-4xl">
        The assistant never invents a number.
      </h1>
      <p className="text-slate mt-4 max-w-xl leading-relaxed">
        Every projection, rating, and squad on this site is computed by a
        statistical engine and carries a timestamp saying which data it was
        computed from. The AI&apos;s only job is to understand your question,
        run the engine&apos;s tools, and explain the results. If the engine
        can&apos;t compute an answer, the assistant says so — it is not allowed
        to guess.
      </p>

      <ChatbotContrast />
      <Layers />
      <LiveProof />
      <KeptHonest />
      <Tested />

      <div className="border-line mt-12 flex flex-wrap items-center gap-3 border-t pt-6">
        <Link
          href="/builder"
          className="bg-pitch-deep text-chalk rounded-md px-4 py-2 text-sm font-medium"
        >
          Draft your squad
        </Link>
        <Link href="/players" className="text-pitch-deep text-sm font-medium hover:underline">
          Or browse the projections →
        </Link>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="font-hero text-xl">{title}</h2>
      <div className="mt-3 space-y-3 text-sm leading-relaxed">{children}</div>
    </section>
  );
}

function ChatbotContrast() {
  const rows: [string, string][] = [
    [
      "Its knowledge froze months ago. It may not know who got transferred, promoted, or injured this week.",
      "Data is pulled from the official FPL API every hour, and every answer names the snapshot it was computed from.",
    ],
    [
      "It generates plausible-sounding numbers. Ask for a projection and it will produce one — from nothing.",
      "Projections are computed by statistical models, decomposed into goals, assists, clean sheets, and bonus, so you can see why.",
    ],
    [
      "A £100m squad is a hard math problem. A chatbot eyeballs it and often breaks the budget or club limits.",
      "Squads are solved by an optimizer that guarantees budget, formation, and club-limit rules — optimally, in under a second.",
    ],
    [
      "You can't check where its numbers came from.",
      "Every number in a reply is tappable, straight back to the engine output it came from.",
    ],
  ];
  return (
    <Section title="Why not just ask ChatGPT?">
      <p className="text-slate">
        Because a language model on its own is a plausibility machine, not a
        calculator. The honest comparison, line by line:
      </p>
      <div className="space-y-2.5">
        {rows.map(([chatbot, board], i) => (
          <div key={i} className="grid gap-2.5 sm:grid-cols-2">
            <div className="border-line bg-paper-2 rounded-md border p-3">
              <p className="font-chip text-slate text-[10px] font-semibold tracking-wide">
                A chatbot alone
              </p>
              <p className="text-slate mt-1">{chatbot}</p>
            </div>
            <div className="border-line bg-chalk rounded-md border p-3">
              <p className="font-chip text-pitch-deep text-[10px] font-semibold tracking-wide">
                This site
              </p>
              <p className="mt-1">{board}</p>
            </div>
          </div>
        ))}
      </div>
      <p className="text-slate">
        We still use a language model — Claude — but only as the interpreter
        between you and the engine. It reads your question, calls the right
        tools, and narrates what they return. The thinking about football is
        done in statistics; the AI does the talking.
      </p>
    </Section>
  );
}

function Layers() {
  const layers = [
    {
      n: 1,
      title: "Team strength",
      body: "A Dixon-Coles match model — the standard for football scorelines — fitted over ten seasons of results with recent games weighted heaviest, blended with team xG. It turns every fixture into expected goals for both sides, clean-sheet probabilities, and a continuous difficulty rating that replaces FPL's crude 1–5.",
    },
    {
      n: 2,
      title: "Minutes",
      body: "The biggest source of error in any FPL projection is whether a player is on the pitch at all. A machine-learned model predicts start probability, expected minutes, and the chance of playing 60+, from each player's usage patterns, rest days, and price signals — with live injury flags overlaid.",
    },
    {
      n: 3,
      title: "Player event rates",
      body: "Per-90 rates for goals (from xG), assists, defensive contributions, saves, cards, and bonus tendency — each shrunk toward what players of that position and price typically produce, so a two-week hot streak doesn't hijack a projection and brand-new signings get sensible starting points.",
    },
    {
      n: 4,
      title: "Points assembly",
      body: "Multiply it all out against the official scoring rules: every event's probability times its point value for that position, summed per fixture — double gameweeks included — plus a ceiling estimate for captaincy calls.",
    },
  ];
  return (
    <Section title="How expected points are built">
      <p className="text-slate">
        No single opaque prediction. Points are assembled bottom-up through
        four layers, each testable on its own:
      </p>
      <ol className="space-y-2.5">
        {layers.map((l) => (
          <li key={l.n} className="border-line bg-chalk flex gap-3 rounded-md border p-3">
            <span className="font-hero text-pitch-deep text-lg leading-none">{l.n}</span>
            <span>
              <span className="block font-semibold">{l.title}</span>
              <span className="text-slate">{l.body}</span>
            </span>
          </li>
        ))}
      </ol>
      <div className="border-line bg-paper-2 overflow-x-auto rounded-md border p-3 font-mono text-xs leading-relaxed">
        E[points] = P(plays) × appearance
        <br />
        &nbsp;&nbsp;+ E[goals] × value(position) + E[assists] × 3
        <br />
        &nbsp;&nbsp;+ P(60+ min) × P(clean sheet) × value(position)
        <br />
        &nbsp;&nbsp;+ P(defensive contribution) × 2 + E[bonus] − cards − conceded
      </div>
      <p className="text-slate">
        On top of that sit position-specific 0–100 ratings — separate systems
        for keepers, defenders, midfielders and forwards, with weights fitted
        against what actually scored points, not hand-tuned — and a squad
        optimizer that solves budget, formation, captaincy, and bench order as
        one problem.
      </p>
    </Section>
  );
}

function LiveProof() {
  const { data } = useExplorer();
  const top = useMemo(
    () =>
      data
        ? [...data.players].sort((a, b) => b.xpts - a.xpts)[0]
        : undefined,
    [data],
  );
  const proj = usePlayerProjection(top ? top.player : null);
  const p = proj.data?.projections[0];
  const prov = proj.data?.provenance;

  return (
    <Section title="See it computing, right now">
      <p className="text-slate">
        This isn&apos;t a mock-up — it&apos;s the engine&apos;s current
        highest-projected player, decomposed by scoring source, fetched live
        as you opened this page:
      </p>
      {p ? (
        <div className="border-line bg-chalk rounded-md border p-4">
          <p className="text-sm font-medium">
            {p.player}{" "}
            <span className="text-slate font-normal">
              · {p.team} · next {p.per_gw.length} GWs ·{" "}
              <span className="font-mono font-semibold">{pts(p.total_xpts)}</span> xPts
            </span>
          </p>
          <div className="mt-2">
            <DecompositionChart perGw={p.per_gw} />
          </div>
          {prov && (
            <p className="text-slate border-line mt-3 border-t pt-2 font-mono text-[10px]">
              season {prov.season} · computed{" "}
              {prov.computed_at.slice(0, 16).replace("T", " ")} · snapshot{" "}
              {prov.data_snapshot}
            </p>
          )}
        </div>
      ) : (
        <p className="text-slate border-line bg-paper-2 rounded-md border p-3 text-sm">
          {proj.isLoading || !data
            ? "Computing…"
            : "The engine is offline right now — which is the point: this page would rather show you nothing than a made-up chart."}
        </p>
      )}
    </Section>
  );
}

function KeptHonest() {
  return (
    <Section title="How the AI is kept honest">
      <ul className="list-disc space-y-2 pl-5">
        <li>
          <strong>A hard contract:</strong> every statistic, ranking, or
          recommendation the assistant states must come from an engine result
          in that conversation. Football knowledge is allowed for context and
          phrasing — never for numbers.
        </li>
        <li>
          <strong>Receipts on screen:</strong> tool results render as cards
          next to the prose, numbers in the reply link to their source, and
          each card carries the data snapshot it was computed from.
        </li>
        <li>
          <strong>Adversarially tested:</strong> an automated suite tries to
          bait the assistant into guessing — invented players, departed
          players, &quot;just give me a rough estimate&quot; — and fails the build if it
          ever does.
        </li>
        <li>
          <strong>Refusal is a feature:</strong> ask about a player who left
          the league and you&apos;ll be told he&apos;s gone, not given a confident
          projection of a ghost.
        </li>
      </ul>
    </Section>
  );
}

function Tested() {
  return (
    <Section title="Tested against history, not vibes">
      <p>
        Before the season, the whole stack is replayed against past seasons as
        if live — models trained only on data available at the time, then
        scored on what actually happened. In the 2025/26 replay, the
        engine&apos;s pre-season draft scored{" "}
        <strong className="font-mono">432 points</strong> over the opening six
        gameweeks; a &quot;pick last season&apos;s top scorers&quot; draft managed{" "}
        <span className="font-mono">217</span>, and the perfect-hindsight squad{" "}
        <span className="font-mono">528</span> — the engine captured 82% of a
        ceiling nobody can reach without a crystal ball. Its projections also
        beat form and points-per-game baselines on accuracy and player
        ranking across the season.
      </p>
      <p className="text-slate">
        Honesty requires saying what backtests can&apos;t promise: they measure
        the process, not next week. Football stays random — the engine&apos;s job
        is to put the probabilities on your side and show its working.
      </p>
    </Section>
  );
}
