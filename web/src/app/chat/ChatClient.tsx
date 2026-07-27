"use client";

/** Mobile chat tab: the full-screen thread. On desktop the rail covers this;
 * the page still works if opened directly. */

import { ChatThread } from "@/components/chat/ChatThread";

export default function ChatPage() {
  // 100dvh minus the masthead (3.5rem) and the bottom tab bar (mobile) or
  // status bar (desktop) — the input must never hide behind either.
  return (
    <div className="mx-auto flex h-[calc(100dvh-7.25rem)] max-w-2xl flex-col lg:h-[calc(100dvh-5.25rem)]">
      <ChatThread />
    </div>
  );
}
