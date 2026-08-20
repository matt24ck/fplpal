import { withSentryConfig } from "@sentry/nextjs";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // The FastAPI engine. Same-origin in dev so the browser never deals with CORS,
    // and the API base is one env var in prod.
    const api = process.env.ENGINE_API_URL ?? "http://127.0.0.1:8000";
    return [{ source: "/api/engine/:path*", destination: `${api}/:path*` }];
  },
};

// Sentry build plumbing. Runtime capture is env-gated on NEXT_PUBLIC_SENTRY_DSN
// (see instrumentation-client.ts / sentry.*.config.ts); source-map upload only
// happens when SENTRY_AUTH_TOKEN is present (Vercel), so local and CI builds
// stay quiet and identical.
export default withSentryConfig(nextConfig, {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  sourcemaps: { disable: !process.env.SENTRY_AUTH_TOKEN },
  silent: true,
  telemetry: false,
  disableLogger: true,
  // errors-only: strip the tracing/replay code paths from the client bundle
  bundleSizeOptimizations: {
    excludeDebugStatements: true,
    excludeTracing: true,
    excludeReplayIframe: true,
    excludeReplayShadowDom: true,
    excludeReplayWorker: true,
  },
});
