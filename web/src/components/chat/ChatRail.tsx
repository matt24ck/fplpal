"use client";

import { ChatThread } from "./ChatThread";

/** Desktop chat rail — always beside the canvas; that's what "AI-focused"
 * means spatially. */
export function ChatRail({ onCollapse }: { onCollapse: () => void }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-line flex items-center justify-between border-b px-3 py-2">
        <h2 className="font-chip text-xs font-semibold tracking-wide">Assistant</h2>
        <button
          onClick={onCollapse}
          className="text-slate hover:text-ink px-1 text-sm"
          aria-label="Collapse assistant"
          title="Collapse"
        >
          →
        </button>
      </div>
      <ChatThread />
    </div>
  );
}
