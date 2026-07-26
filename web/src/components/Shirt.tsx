"use client";

/** A club shirt, drawn: body + sleeves with the kit's real pattern (stripes,
 * halves, contrast sleeves, hoops). This is how the board says which team a
 * player plays for — before any text does. */

import { useId } from "react";
import { kitFor } from "@/lib/teamColors";

const BODY = "M13 4.5 L17.5 2.5 C18.3 4 21.7 4 22.5 2.5 L27 4.5 L26.4 30.5 C22.2 32.2 17.8 32.2 13.6 30.5 Z";
const SLEEVE_L = "M13.4 4.7 L4.5 8.8 L7.4 15.6 L13.2 13 Z";
const SLEEVE_R = "M26.6 4.7 L35.5 8.8 L32.6 15.6 L26.8 13 Z";
const OUTLINE = "rgba(25, 18, 39, 0.3)";

export function Shirt({ team, className }: { team: string; className?: string }) {
  const kit = kitFor(team);
  const clip = useId().replace(/[^a-zA-Z0-9-]/g, "");
  const sleeveFill = kit.pattern === "sleeves" ? kit.secondary : kit.primary;

  return (
    <svg viewBox="0 0 40 34" className={className} aria-hidden focusable="false">
      <defs>
        <clipPath id={`b-${clip}`}>
          <path d={BODY} />
        </clipPath>
      </defs>

      <path d={SLEEVE_L} fill={sleeveFill} stroke={OUTLINE} strokeWidth="0.8" />
      <path
        d={SLEEVE_R}
        fill={kit.pattern === "halves" ? kit.secondary : sleeveFill}
        stroke={OUTLINE}
        strokeWidth="0.8"
      />
      <path d={BODY} fill={kit.primary} />

      <g clipPath={`url(#b-${clip})`}>
        {kit.pattern === "stripes" &&
          [14.6, 18, 21.4, 24.8].map((x) => (
            <rect key={x} x={x} y="2" width="1.9" height="31" fill={kit.secondary} />
          ))}
        {kit.pattern === "halves" && <rect x="20" y="2" width="8" height="31" fill={kit.secondary} />}
        {kit.pattern === "hoops" &&
          [7.5, 13.5, 19.5, 25.5].map((y) => (
            <rect key={y} x="12" y={y} width="16" height="2.6" fill={kit.secondary} />
          ))}
      </g>

      {/* collar */}
      <path
        d="M17.5 2.5 C18.3 4 21.7 4 22.5 2.5"
        fill="none"
        stroke={kit.trim ?? kit.secondary}
        strokeWidth="1.1"
      />
      <path d={BODY} fill="none" stroke={OUTLINE} strokeWidth="0.8" />
    </svg>
  );
}
