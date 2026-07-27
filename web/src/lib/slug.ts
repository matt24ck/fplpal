/** URL slugs for player profile pages, shared by the server routes and the
 * client links so both sides always agree. Deterministic: players are
 * processed in FPL-code order, so the lower (older) code keeps the bare name
 * and a later namesake gets a "-<code>" suffix — existing URLs never change
 * when new players arrive. */

const FOLD: Record<string, string> = {
  "ø": "o", // ø
  "æ": "ae", // æ
  "œ": "oe", // œ
  "ß": "ss", // ß
  "đ": "d", // đ
  "ð": "d", // ð
  "ł": "l", // ł
  "þ": "th", // þ
};

/** "Martin Ødegaard" → "martin-odegaard". Empty result (fully non-Latin
 * name) falls back to the code at the call site. */
export function slugify(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "") // strip combining accents
    .toLowerCase()
    .replace(/[øæœßđðłþ]/g, (c) => FOLD[c] ?? c)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function assignSlugs(
  players: { player: string; code: number }[],
): Map<number, string> {
  const taken = new Set<string>();
  const slugs = new Map<number, string>();
  for (const p of [...players].sort((a, b) => a.code - b.code)) {
    const base = slugify(p.player) || String(p.code);
    const slug = taken.has(base) ? `${base}-${p.code}` : base;
    taken.add(slug);
    slugs.set(p.code, slug);
  }
  return slugs;
}
