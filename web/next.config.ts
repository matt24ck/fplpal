import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // The FastAPI engine. Same-origin in dev so the browser never deals with CORS,
    // and the API base is one env var in prod.
    const api = process.env.ENGINE_API_URL ?? "http://127.0.0.1:8000";
    return [{ source: "/api/engine/:path*", destination: `${api}/:path*` }];
  },
};

export default nextConfig;
