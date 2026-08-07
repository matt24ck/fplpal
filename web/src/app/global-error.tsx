"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

/** Root-level React render crash: report it and show an honest minimal
 * shell. This replaces the entire root layout when it fires, so no global
 * CSS or fonts are available — inline styles only. */
export default function GlobalError({ error }: { error: Error & { digest?: string } }) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          fontFamily: "system-ui, sans-serif",
          padding: "4rem 1.5rem",
          textAlign: "center",
          color: "#191227",
          background: "#f6f6fa",
        }}
      >
        <h1 style={{ fontSize: "1.5rem" }}>Something broke.</h1>
        <p style={{ color: "#5d5972" }}>
          The error has been reported — a reload usually carries on fine.
        </p>
        <button
          onClick={() => window.location.reload()}
          style={{
            marginTop: "1rem",
            padding: "0.5rem 1.25rem",
            borderRadius: "999px",
            border: "1px solid #e2e0ec",
            background: "#ffffff",
            cursor: "pointer",
          }}
        >
          Reload
        </button>
      </body>
    </html>
  );
}
