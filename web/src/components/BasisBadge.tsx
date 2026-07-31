import type { DataBasis } from "@/lib/types";

/** Prior-vs-observed provenance badge (grounding surface, TODO §3): shown
 * only when a projection is prior-heavy — new signings and promoted-club
 * players whose numbers are mostly the position × price-tier prior, not
 * observed PL form. Quiet for everyone else, so the badge means something. */

const heavy = (basis?: DataBasis) =>
  basis?.level === "pure_prior" || basis?.level === "mostly_prior";

function copy(basis: DataBasis): { label: string; title: string } {
  if (basis.level === "pure_prior") {
    return {
      label: "Price-tier prior",
      title:
        "No Premier League data in the archive — this projection is built entirely from the position × price-tier prior. Treat it as a sensible default, not observed form.",
    };
  }
  return {
    label: `Mostly prior · ${basis.effective_90s} obs 90s`,
    title: `Thin Premier League sample (${basis.effective_90s} time-decayed 90s) — the projection still leans mostly on the position × price-tier prior.`,
  };
}

export function BasisBadge({
  basis,
  className,
}: {
  basis?: DataBasis;
  className?: string;
}) {
  if (!basis || !heavy(basis)) return null;
  const { label, title } = copy(basis);
  return (
    <span
      title={title}
      className={`border-line bg-paper-2 text-ink inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium ${className ?? ""}`}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: "var(--color-armband)" }}
        aria-hidden
      />
      {label}
    </span>
  );
}

/** Table-density variant: a small marked dot with the same explanation in
 * the tooltip and accessible name. Pure-prior only — pre-season more than
 * half the pool is legitimately "mostly prior" (a full season decays to
 * ~20 effective 90s under the 180-day half-life), and a dot on half the
 * table marks nothing. */
export function BasisDot({ basis }: { basis?: DataBasis }) {
  if (basis?.level !== "pure_prior") return null;
  const { label, title } = copy(basis);
  return (
    <span
      role="img"
      aria-label={label}
      title={title}
      className="ml-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full align-middle"
      style={{ background: "var(--color-armband)" }}
    />
  );
}
