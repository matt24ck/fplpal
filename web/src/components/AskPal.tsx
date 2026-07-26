"use client";

/** One way to talk to Pal from anywhere: queue the prompt for the rail on
 * desktop, carry it to the chat screen on mobile. */

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useApp } from "@/lib/store";
import { SparkIcon } from "./Shell";

export function useAskPal() {
  const { sendPrompt } = useApp();
  const router = useRouter();
  return (prompt: string) => {
    sendPrompt(prompt);
    if (!window.matchMedia("(min-width: 1024px)").matches) router.push("/chat");
  };
}

export function AskPalBar({
  className = "",
  placeholder = "Ask Pal — who's the best £8m midfielder?",
}: {
  className?: string;
  placeholder?: string;
}) {
  const ask = useAskPal();
  const [text, setText] = useState("");

  return (
    <form
      role="search"
      className={`bg-chalk flex items-center gap-2 rounded-full p-1.5 pl-4 shadow-lg ${className}`}
      onSubmit={(e) => {
        e.preventDefault();
        const t = text.trim();
        if (!t) return;
        setText("");
        ask(t);
      }}
    >
      <SparkIcon className="text-royal h-4 w-4 shrink-0" />
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        aria-label="Ask Pal"
        className="text-ink placeholder:text-slate min-w-0 flex-1 bg-transparent text-sm outline-none"
      />
      <button className="btn-primary shrink-0 rounded-full px-4 py-2 text-sm">Ask Pal</button>
    </form>
  );
}
