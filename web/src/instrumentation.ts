import * as Sentry from "@sentry/nextjs";

/** Server-side Sentry bootstrap (Next instrumentation hook). A no-op unless
 * NEXT_PUBLIC_SENTRY_DSN is set. */
export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("../sentry.server.config");
  }
  if (process.env.NEXT_RUNTIME === "edge") {
    await import("../sentry.edge.config");
  }
}

export const onRequestError = Sentry.captureRequestError;
