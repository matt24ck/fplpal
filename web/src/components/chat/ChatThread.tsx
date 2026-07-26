"use client";

/** The conversation surface: streaming prose with data chips, tool cards
 * inline in call order, contextual suggested prompts, honest error states. */

import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useDraftSquad } from "@/lib/hooks";
import { useApp } from "@/lib/store";
import type { ChatMessage } from "@/lib/types";
import { MiniMarkdown } from "./Markdown";
import { ToolCard } from "./ToolCard";
import { collectNumbers, useChat } from "./useChat";

export function ChatThread() {
  const { messages, send, busy } = useChat();
  const { consumePrompt, pendingPrompt } = useApp();
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const { names, complete } = useDraftSquad();

  // prompts queued from elsewhere in the UI ("ask the assistant…")
  useEffect(() => {
    if (pendingPrompt && !busy) {
      const p = consumePrompt();
      if (p) void send(p);
    }
  }, [pendingPrompt, busy, consumePrompt, send]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const suggestions = useMemo(() => {
    const s: { label: string; prompt: string }[] = [];
    if (complete)
      s.push({
        label: "Rate my draft",
        prompt: `Rate my draft: ${names.join(", ")}`,
      });
    else if (pathname === "/builder" || pathname === "/")
      s.push({ label: "Build me a £100m squad", prompt: "Build me the best £100m squad." });
    if (complete) s.push({ label: "Who should I captain?", prompt: `Who should I captain from this squad: ${names.join(", ")}?` });
    s.push(
      { label: "Best value midfielders", prompt: "Who are the best value midfielders right now?" },
      { label: "Easiest opening fixtures", prompt: "Which teams have the easiest opening fixtures?" },
      { label: "Best DEF under £5.5m", prompt: "Who are the best defenders under £5.5m?" },
    );
    return s.slice(0, 4);
  }, [complete, names, pathname]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-4" aria-live="polite">
        {messages.length === 0 && (
          <div className="text-slate px-1 pt-2 text-sm">
            <p className="text-ink font-medium">Ask the engine anything.</p>
            <p className="mt-1 leading-relaxed">
              Every number in a reply is computed by the statistical engine and shown
              with its source — the assistant narrates, it never guesses.{" "}
              <a href="/about" className="text-pitch-deep font-medium hover:underline">
                How it works →
              </a>
            </p>
          </div>
        )}
        {messages.map((m, i) => (
          <Message key={i} message={m} streaming={busy && i === messages.length - 1} />
        ))}
      </div>

      {messages.length === 0 && (
        <div className="flex flex-wrap gap-1.5 px-3 pb-2">
          {suggestions.map((s) => (
            <button
              key={s.label}
              onClick={() => void send(s.prompt)}
              className="border-line bg-chalk hover:border-pitch-deep rounded-full border px-3 py-1.5 text-xs"
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      <form
        className="border-line flex gap-2 border-t p-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (input.trim() && !busy) {
            void send(input);
            setInput("");
          }
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={busy ? "Thinking…" : "Sell Saka for Palmer, or save?"}
          aria-label="Ask the assistant"
          disabled={busy}
          className="border-line bg-chalk min-w-0 flex-1 rounded-md border px-3 py-2 text-sm disabled:opacity-60"
        />
        <button
          disabled={busy || !input.trim()}
          className="bg-pitch-deep text-chalk rounded-md px-3.5 py-2 text-sm font-medium disabled:opacity-50"
        >
          Ask
        </button>
      </form>
    </div>
  );
}

function Message({ message, streaming }: { message: ChatMessage; streaming: boolean }) {
  const chips = useMemo(
    () => (message.role === "assistant" ? collectNumbers(message.parts) : new Map<string, string>()),
    [message.parts, message.role],
  );

  if (message.role === "user")
    return (
      <div className="flex justify-end">
        <div className="bg-paper-2 max-w-[85%] rounded-lg rounded-br-sm px-3 py-2 text-sm">
          {message.parts.map((p, i) => (p.type === "text" ? <span key={i}>{p.text}</span> : null))}
        </div>
      </div>
    );

  return (
    <div className="space-y-2">
      {message.parts.map((part, i) =>
        part.type === "text" ? (
          <MiniMarkdown key={i} text={part.text} chips={chips} />
        ) : (
          <ToolCard key={part.id} part={part} />
        ),
      )}
      {streaming && message.parts.length === 0 && (
        <p className="text-slate text-sm">
          <span className="animate-pulse">thinking…</span>
        </p>
      )}
      {message.error && (
        <p className="border-card-red/40 bg-card-red/5 rounded-md border px-3 py-2 text-sm">
          The assistant hit a snag: <span className="font-mono text-xs">{message.error}</span>
          {message.error.includes("chat → 5") || message.error.toLowerCase().includes("api")
            ? " — is the engine running with an ANTHROPIC_API_KEY?"
            : ""}
        </p>
      )}
    </div>
  );
}
