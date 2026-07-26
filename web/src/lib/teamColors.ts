import { teamAbbrev } from "./format";

/** Home-kit spec per club, keyed by abbreviation so every name form the API
 * uses ("Man City" / "Manchester City") resolves to the same kit. Colors are
 * each club's traditional home identity, not a licensed asset. */

export type KitPattern = "plain" | "sleeves" | "stripes" | "halves" | "hoops";

export interface Kit {
  primary: string;
  secondary: string;
  pattern: KitPattern;
  /** collar/outline accent when body and sleeves are both light */
  trim?: string;
}

const KITS: Record<string, Kit> = {
  ARS: { primary: "#ef0107", secondary: "#ffffff", pattern: "sleeves" },
  AVL: { primary: "#670e36", secondary: "#94bee5", pattern: "sleeves" },
  BOU: { primary: "#da020e", secondary: "#000000", pattern: "stripes" },
  BRE: { primary: "#e30613", secondary: "#ffffff", pattern: "stripes" },
  BHA: { primary: "#0054a6", secondary: "#ffffff", pattern: "stripes" },
  BUR: { primary: "#6c1d45", secondary: "#99d6ea", pattern: "sleeves" },
  CHE: { primary: "#0a4595", secondary: "#ffffff", pattern: "plain" },
  COV: { primary: "#59cbe8", secondary: "#ffffff", pattern: "plain" },
  CRY: { primary: "#1b458f", secondary: "#c4122e", pattern: "halves" },
  EVE: { primary: "#003399", secondary: "#ffffff", pattern: "plain" },
  FUL: { primary: "#ffffff", secondary: "#000000", pattern: "plain", trim: "#000000" },
  HUL: { primary: "#f5a12d", secondary: "#000000", pattern: "stripes" },
  IPS: { primary: "#3a64a3", secondary: "#ffffff", pattern: "plain" },
  LEE: { primary: "#ffffff", secondary: "#1d428a", pattern: "plain", trim: "#1d428a" },
  LEI: { primary: "#003090", secondary: "#ffffff", pattern: "plain" },
  LIV: { primary: "#c8102e", secondary: "#ffffff", pattern: "plain" },
  MCI: { primary: "#6cabdd", secondary: "#ffffff", pattern: "plain" },
  MUN: { primary: "#da291c", secondary: "#000000", pattern: "plain", trim: "#000000" },
  NEW: { primary: "#241f20", secondary: "#ffffff", pattern: "stripes" },
  NFO: { primary: "#e53233", secondary: "#ffffff", pattern: "plain" },
  SOU: { primary: "#d71920", secondary: "#ffffff", pattern: "stripes" },
  SUN: { primary: "#eb172b", secondary: "#ffffff", pattern: "stripes" },
  TOT: { primary: "#ffffff", secondary: "#132257", pattern: "plain", trim: "#132257" },
  WHU: { primary: "#7a263a", secondary: "#1bb1e7", pattern: "sleeves" },
  WOL: { primary: "#fdb913", secondary: "#231f20", pattern: "plain", trim: "#231f20" },
};

const FALLBACK: Kit = { primary: "#9aa0ab", secondary: "#ffffff", pattern: "plain" };

export const kitFor = (team: string): Kit => KITS[teamAbbrev(team)] ?? FALLBACK;
