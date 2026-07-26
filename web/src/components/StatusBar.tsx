"use client";

import { useMeta } from "@/lib/hooks";

/** Global provenance: every screen answers "how fresh is this?" without being asked. */
export function StatusBar() {
  const { data, isError } = useMeta();
  return (
    <footer className="border-line bg-paper text-slate fixed inset-x-0 bottom-14 z-30 hidden border-t px-4 py-1 font-mono text-[11px] lg:static lg:bottom-0 lg:block">
      {isError ? (
        <span className="text-card-red">
          engine offline — start it with: uvicorn api.app:app
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
    </footer>
  );
}
