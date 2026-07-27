"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback } from "react";
import { streamChat } from "@/lib/api";
import { useApp } from "@/lib/store";
import type { ChatMessage, ChatPart } from "@/lib/types";

/** Player names found anywhere in a tool payload (objects with a `player` field). */
export function collectPlayers(x: unknown, out: Set<string> = new Set()): Set<string> {
  if (Array.isArray(x)) for (const v of x) collectPlayers(v, out);
  else if (x && typeof x === "object") {
    const o = x as Record<string, unknown>;
    if (typeof o.player === "string") out.add(o.player);
    for (const v of Object.values(o)) collectPlayers(v, out);
  }
  return out;
}

/** Number tokens present in tool results → the tool_use id they came from.
 * Used to render matching numbers in prose as tappable data chips. */
export function collectNumbers(parts: ChatPart[]): Map<string, string> {
  const map = new Map<string, string>();
  const add = (s: string, id: string) => {
    if (!map.has(s)) map.set(s, id);
  };
  const walk = (x: unknown, id: string) => {
    if (Array.isArray(x)) for (const v of x) walk(v, id);
    else if (x && typeof x === "object")
      for (const v of Object.values(x as Record<string, unknown>)) walk(v, id);
    else if (typeof x === "number" && Number.isFinite(x)) {
      if (!Number.isInteger(x)) {
        add(x.toFixed(1), id);
        add(x.toFixed(2), id);
        add(String(x), id);
      }
    } else if (typeof x === "string" && /£\d/.test(x)) add(x.replace(/[^£\d.m]/g, ""), id);
  };
  for (const p of parts) if (p.type === "tool" && p.result !== undefined) walk(p.result, p.id);
  return map;
}

function serialize(messages: ChatMessage[]): { role: string; content: string }[] {
  return messages
    .map((m) => ({
      role: m.role,
      content: m.parts
        .filter((p): p is Extract<ChatPart, { type: "text" }> => p.type === "text")
        .map((p) => p.text)
        .join("")
        .trim(),
    }))
    .filter((m) => m.content.length > 0)
    .slice(-12);
}

export function useChat() {
  const { messages, setMessages, chatBusy, setChatBusy, setHighlight } = useApp();
  const { getToken } = useAuth();

  const send = useCallback(
    async (text: string) => {
      if (chatBusy || !text.trim()) return;
      const userMsg: ChatMessage = { role: "user", parts: [{ type: "text", text: text.trim() }] };
      const history = [...messages, userMsg];
      const assistant: ChatMessage = { role: "assistant", parts: [] };
      setMessages([...history, assistant]);
      setChatBusy(true);

      const push = () => setMessages([...history, { ...assistant, parts: [...assistant.parts] }]);

      try {
        const token = (await getToken()) ?? undefined;
        for await (const ev of streamChat(serialize(history), { token })) {
          if (ev.event === "text") {
            const last = assistant.parts[assistant.parts.length - 1];
            if (last?.type === "text") last.text += ev.data.delta;
            else assistant.parts.push({ type: "text", text: ev.data.delta });
          } else if (ev.event === "tool_use") {
            assistant.parts.push({
              type: "tool",
              id: ev.data.id,
              name: ev.data.name,
              input: ev.data.input,
            });
          } else if (ev.event === "tool_result") {
            const part = assistant.parts.find(
              (p) => p.type === "tool" && p.id === ev.data.tool_use_id,
            );
            if (part?.type === "tool") part.result = ev.data.result;
          } else if (ev.event === "error") {
            assistant.error = ev.data.message;
          }
          push();
        }

        // the assistant points at the board: highlight players its answer cites
        const names = new Set<string>();
        for (const p of assistant.parts)
          if (p.type === "tool" && p.result !== undefined) collectPlayers(p.result, names);
        const prose = assistant.parts
          .filter((p) => p.type === "text")
          .map((p) => (p as { text: string }).text)
          .join(" ")
          .toLowerCase();
        const mentioned = [...names].filter((n) => {
          const lower = n.toLowerCase();
          const last = lower.split(" ").pop() ?? lower;
          return prose.includes(lower) || prose.includes(last);
        });
        if (mentioned.length > 0) setHighlight(mentioned.slice(0, 6));
      } catch (e) {
        assistant.error = e instanceof Error ? e.message : "stream failed";
        push();
      } finally {
        setChatBusy(false);
      }
    },
    [chatBusy, getToken, messages, setChatBusy, setHighlight, setMessages],
  );

  return { messages, send, busy: chatBusy };
}
