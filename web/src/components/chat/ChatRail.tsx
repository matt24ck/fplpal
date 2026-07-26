"use client";

import { PalMark } from "../Shell";
import { ChatThread } from "./ChatThread";

/** Desktop Pal rail — always beside the canvas; that's what "AI-first"
 * means spatially. The header says who's talking and that it's live. */
export function ChatRail({ onCollapse }: { onCollapse: () => void }) {
  return (
    <div className="bg-paper flex h-full min-h-0 flex-col">
      <div className="masthead text-chalk flex items-center gap-2 px-3 py-2.5">
        <PalMark className="h-4.5 w-4.5" />
        <h2 className="font-hero text-sm leading-none">PAL</h2>
        <span className="pal-dot bg-neon h-1.5 w-1.5 rounded-full" aria-hidden />
        <span className="text-chalk/55 ml-1 text-[10px]">every number from the engine</span>
        <button
          onClick={onCollapse}
          className="text-chalk/70 hover:text-chalk ml-auto px-1 text-sm"
          aria-label="Collapse Pal"
          title="Collapse"
        >
          →
        </button>
      </div>
      <ChatThread />
    </div>
  );
}
