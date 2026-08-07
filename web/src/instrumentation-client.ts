import * as Sentry from "@sentry/nextjs";

/** Browser-side error tracking — errors only (no tracing, no replay, no PII),
 * and a no-op unless NEXT_PUBLIC_SENTRY_DSN is set. Client errors are the
 * invisible class this exists for: hydration mismatches, render crashes, and
 * fetch handling bugs that never show up in any server log. */
Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  enabled: !!process.env.NEXT_PUBLIC_SENTRY_DSN,
  tracesSampleRate: 0,
  sendDefaultPii: false,
});

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
