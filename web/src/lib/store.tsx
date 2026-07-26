"use client";

/** App-wide client state: the user's draft squad (localStorage-persisted),
 * chat thread, and the cross-highlight set the assistant "points" with. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ChatMessage } from "./types";

const DRAFT_KEY = "fpl-ai:draft";
const TEAM_ID_KEY = "fpl-ai:team-id";

interface AppState {
  hydrated: boolean;
  draft: number[]; // player codes, up to 15
  setDraft: (codes: number[]) => void;
  addToDraft: (code: number) => void;
  removeFromDraft: (code: number) => void;
  teamId: string | null;
  setTeamId: (id: string | null) => void;
  highlight: Set<string>; // casefolded player names the assistant is pointing at
  setHighlight: (names: string[]) => void;
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  chatBusy: boolean;
  setChatBusy: (b: boolean) => void;
  chatOpen: boolean;
  setChatOpen: (b: boolean) => void;
  pendingPrompt: string | null;
  sendPrompt: (text: string) => void;
  consumePrompt: () => string | null;
}

const Ctx = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [hydrated, setHydrated] = useState(false);
  const [draft, setDraftState] = useState<number[]>([]);
  const [teamId, setTeamIdState] = useState<string | null>(null);
  const [highlight, setHighlightState] = useState<Set<string>>(new Set());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatBusy, setChatBusy] = useState(false);
  const [chatOpen, setChatOpen] = useState(true);
  const pendingRef = useRef<string | null>(null);
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);

  useEffect(() => {
    try {
      const d = localStorage.getItem(DRAFT_KEY);
      if (d) setDraftState(JSON.parse(d));
      setTeamIdState(localStorage.getItem(TEAM_ID_KEY));
    } catch {
      // corrupt storage — start clean
    }
    setHydrated(true);
  }, []);

  const setDraft = useCallback((codes: number[]) => {
    const unique = [...new Set(codes)].slice(0, 15);
    setDraftState(unique);
    localStorage.setItem(DRAFT_KEY, JSON.stringify(unique));
  }, []);

  const addToDraft = useCallback(
    (code: number) => {
      setDraftState((prev) => {
        if (prev.includes(code) || prev.length >= 15) return prev;
        const next = [...prev, code];
        localStorage.setItem(DRAFT_KEY, JSON.stringify(next));
        return next;
      });
    },
    [],
  );

  const removeFromDraft = useCallback((code: number) => {
    setDraftState((prev) => {
      const next = prev.filter((c) => c !== code);
      localStorage.setItem(DRAFT_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const setTeamId = useCallback((id: string | null) => {
    setTeamIdState(id);
    if (id) localStorage.setItem(TEAM_ID_KEY, id);
    else localStorage.removeItem(TEAM_ID_KEY);
  }, []);

  const setHighlight = useCallback((names: string[]) => {
    setHighlightState(new Set(names.map((n) => n.toLowerCase())));
  }, []);

  const sendPrompt = useCallback((text: string) => {
    pendingRef.current = text;
    setPendingPrompt(text);
    setChatOpen(true);
  }, []);

  const consumePrompt = useCallback(() => {
    const p = pendingRef.current;
    pendingRef.current = null;
    setPendingPrompt(null);
    return p;
  }, []);

  const value = useMemo(
    () => ({
      hydrated,
      draft,
      setDraft,
      addToDraft,
      removeFromDraft,
      teamId,
      setTeamId,
      highlight,
      setHighlight,
      messages,
      setMessages,
      chatBusy,
      setChatBusy,
      chatOpen,
      setChatOpen,
      pendingPrompt,
      sendPrompt,
      consumePrompt,
    }),
    [
      hydrated, draft, setDraft, addToDraft, removeFromDraft, teamId, setTeamId,
      highlight, setHighlight, messages, chatBusy, chatOpen, pendingPrompt,
      sendPrompt, consumePrompt,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp outside AppProvider");
  return ctx;
}
