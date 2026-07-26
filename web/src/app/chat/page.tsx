"use client";

/** Mobile chat tab: the full-screen thread. On desktop the rail covers this;
 * the page still works if opened directly. */

import { ChatThread } from "@/components/chat/ChatThread";

export default function ChatPage() {
  return (
    <div className="mx-auto flex h-[calc(100dvh-3.5rem)] max-w-2xl flex-col lg:h-[calc(100dvh-1.75rem)]">
      <ChatThread />
    </div>
  );
}
