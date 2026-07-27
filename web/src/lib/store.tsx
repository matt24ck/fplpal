"use client";

/** App-wide client state: the user's draft squad (localStorage-persisted),
 * chat thread, and the cross-highlight set the assistant "points" with. */

import { useAuth } from "@clerk/nextjs";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { api } from "./api";
import type { ChatMessage } from "./types";

const DRAFT_KEY = "fpl-ai:draft";
const TEAM_ID_KEY = "fpl-ai:team-id";
// sessionStorage: a prompt queued while signed out must survive the OAuth
// round-trip (full page navigation) and send itself on return
const PENDING_KEY = "fpl-ai:pending-prompt";

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
      const p = sessionStorage.getItem(PENDING_KEY);
      if (p) {
        pendingRef.current = p;
        setPendingPrompt(p);
      }
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

  /* Cross-device sync (signed-in only): pull the server copy of draft/team-id
   * once per sign-in, then debounce-push local edits. localStorage stays the
   * source of truth for signed-out use and the offline fallback. */
  const { isLoaded: authLoaded, isSignedIn, userId, getToken } = useAuth();
  const [syncReady, setSyncReady] = useState(false);
  const lastSynced = useRef<string | null>(null); // JSON of state the server has
  const pushTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!hydrated || !authLoaded) return;
    if (!isSignedIn) {
      setSyncReady(false);
      lastSynced.current = null;
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const token = await getToken();
        if (!token) return;
        const server = await api.myState(token);
        if (cancelled) return;
        lastSynced.current = JSON.stringify({ draft: server.draft, teamId: server.team_id });
        // merge: a non-empty server copy wins (it's the cross-device truth);
        // anything only-local survives and the push effect uploads it
        if (server.draft.length > 0) setDraft(server.draft);
        if (server.team_id) setTeamId(server.team_id);
        setSyncReady(true);
      } catch {
        // persistence offline (DATABASE_URL unset / network) — stay local-only
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [hydrated, authLoaded, isSignedIn, userId, getToken, setDraft, setTeamId]);

  useEffect(() => {
    if (!syncReady || !isSignedIn) return;
    const snapshot = JSON.stringify({ draft, teamId });
    if (snapshot === lastSynced.current) return;
    if (pushTimer.current) clearTimeout(pushTimer.current);
    pushTimer.current = setTimeout(async () => {
      try {
        const token = await getToken();
        if (!token) return;
        await api.saveMyState({ draft, team_id: teamId }, token);
        lastSynced.current = snapshot;
      } catch {
        // transient — localStorage still has it; the next edit retries
      }
    }, 800);
    return () => {
      if (pushTimer.current) clearTimeout(pushTimer.current);
    };
  }, [draft, teamId, syncReady, isSignedIn, getToken]);

  const sendPrompt = useCallback((text: string) => {
    pendingRef.current = text;
    setPendingPrompt(text);
    setChatOpen(true);
    sessionStorage.setItem(PENDING_KEY, text);
  }, []);

  const consumePrompt = useCallback(() => {
    const p = pendingRef.current;
    pendingRef.current = null;
    setPendingPrompt(null);
    sessionStorage.removeItem(PENDING_KEY);
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
