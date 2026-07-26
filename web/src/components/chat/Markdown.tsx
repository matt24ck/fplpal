"use client";

/** Minimal markdown for assistant prose (paragraphs, bold, code, lists) with
 * the grounding twist: numbers that came from a tool payload render as
 * tappable data chips linked to their source card. */

import React from "react";

export function jumpToCard(toolId: string) {
  const el = document.getElementById(`toolcard-${toolId}`);
  if (!el) return;
  if (el instanceof HTMLDetailsElement) el.open = true;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("ring-2", "ring-pitch-deep");
  setTimeout(() => el.classList.remove("ring-2", "ring-pitch-deep"), 1400);
}

export function MiniMarkdown({
  text,
  chips,
}: {
  text: string;
  chips: Map<string, string>;
}) {
  const blocks = text.split(/\n\n+/).filter((b) => b.trim());
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {blocks.map((block, i) => {
        const lines = block.split("\n").filter((l) => l.trim());
        // a |---| separator row marks a table; leading lines (e.g. a bold
        // heading the model attached with a single newline) stay prose
        const sep = lines.findIndex(
          (l, j) => j > 0 && /^\s*\|?[\s|:-]+\|?\s*$/.test(l) && lines[j - 1].includes("|"),
        );
        if (sep > 0)
          return (
            <div key={i} className="space-y-2">
              {sep > 1 && <p>{inline(lines.slice(0, sep - 1).join(" "), chips)}</p>}
              <Table header={lines[sep - 1]} body={lines.slice(sep + 1)} chips={chips} />
            </div>
          );
        if (lines.every((l) => /^\s*[-*•]\s+/.test(l)))
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {lines.map((l, j) => (
                <li key={j}>{inline(l.replace(/^\s*[-*•]\s+/, ""), chips)}</li>
              ))}
            </ul>
          );
        if (lines.every((l) => /^\s*\d+[.)]\s+/.test(l)))
          return (
            <ol key={i} className="list-decimal space-y-1 pl-5">
              {lines.map((l, j) => (
                <li key={j}>{inline(l.replace(/^\s*\d+[.)]\s+/, ""), chips)}</li>
              ))}
            </ol>
          );
        if (/^#{1,4}\s+/.test(lines[0]))
          return (
            <p key={i} className="font-semibold">
              {inline(block.replace(/^#{1,4}\s+/, ""), chips)}
            </p>
          );
        return <p key={i}>{inline(block, chips)}</p>;
      })}
    </div>
  );
}

/** Markdown tables — the model reaches for them for squads and comparisons. */
function cells(line: string): string[] {
  return line
    .replace(/^\s*\|/, "")
    .replace(/\|\s*$/, "")
    .split("|")
    .map((c) => c.trim());
}

function Table({
  header: headerLine,
  body,
  chips,
}: {
  header: string;
  body: string[];
  chips: Map<string, string>;
}) {
  const header = cells(headerLine);
  const rows = body.filter((l) => l.includes("|")).map(cells);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate text-left">
            {header.map((h, i) => (
              <th key={i} className="py-1 pr-2 font-medium whitespace-nowrap">
                {inline(h, chips)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-line border-t align-top">
              {r.map((c, j) => (
                <td key={j} className="py-1 pr-2">
                  {inline(c, chips)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** `code` and **bold** spans, then data-chip wrapping in plain runs. */
function inline(text: string, chips: Map<string, string>): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  parts.forEach((part, i) => {
    if (part.startsWith("**") && part.endsWith("**"))
      out.push(<strong key={i}>{chipify(part.slice(2, -2), chips, i)}</strong>);
    else if (part.startsWith("`") && part.endsWith("`"))
      out.push(
        <code key={i} className="bg-paper-2 rounded px-1 font-mono text-[0.9em]">
          {part.slice(1, -1)}
        </code>,
      );
    else out.push(...chipify(part, chips, i));
  });
  return out;
}

/** Wrap decimal / £ / % tokens that exist in a tool payload. Integers stay
 * plain — too ambiguous to attribute. */
function chipify(text: string, chips: Map<string, string>, keyBase: number): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /(£\d+(?:\.\d+)?m?|\d+\.\d+%?)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    const token = m[0];
    const bare = token.replace(/[£%m]/g, "");
    const id = chips.get(token) ?? chips.get(bare);
    if (id) {
      if (m.index > last) out.push(text.slice(last, m.index));
      out.push(
        <button
          key={`${keyBase}-${k++}`}
          className="data-chip"
          onClick={() => jumpToCard(id)}
          title="From the engine — tap to see the source"
        >
          {token}
        </button>,
      );
      last = m.index + token.length;
    }
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
