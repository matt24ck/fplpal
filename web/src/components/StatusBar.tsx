"use client";

import { useEffect, useState } from "react";
import { useMeta } from "@/lib/hooks";

/** Global provenance: every screen answers "how fresh is this?" without being asked.
 * The meta hook runs post-mount only — subscribing during SSR would block
 * ["meta"] hydration on prefetched pages (see Shell). Pre-mount shows the
 * same "connecting…" line the no-data state always showed. */
export function StatusBar() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return (
    <footer className="border-line bg-paper text-slate fixed inset-x-0 bottom-14 z-30 hidden border-t px-4 py-1 font-mono text-[11px] lg:static lg:bottom-0 lg:block">
      {mounted ? <StatusLine /> : <span>connecting to engine…</span>}
    </footer>
  );
}

function StatusLine() {
  const { data, isError } = useMeta();
  return (
    <>
      {isError ? (
        <span className="text-hot">
          engine unavailable — refreshing data or briefly offline; numbers return shortly
        </span>
      ) : data ? (
        <span>
          season {data.provenance.season} · GW{data.provenance.gw_window[0]}–
          {data.provenance.gw_window[1]} · computed{" "}
          {data.provenance.computed_at.slice(0, 16).replace("T", " ")} · snapshot{" "}
          {data.provenance.data_snapshot}
        </span>
      ) : (
        <span>connecting to engine…</span>
      )}
    </>
  );
}
