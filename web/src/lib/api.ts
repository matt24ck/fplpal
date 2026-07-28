import type {
  AccuracyData,
  AccuracyGwDetail,
  ChatEvent,
  ChipAdviceResponse,
  ExplorerData,
  MatrixData,
  Meta,
  ProjectionsResponse,
  RatingExplain,
  SquadSolution,
  TeamState,
  TransferPlan,
} from "./types";

/** Proxied to the FastAPI engine via next.config.ts rewrites. */
const BASE = "/api/engine";

/** Chat goes direct to the engine in production (Vercel's rewrite proxy
 * times out on long SSE streams). Falls back to the same-origin proxy in
 * dev. Build-time inlined — set in the Vercel project env. */
const CHAT_BASE = process.env.NEXT_PUBLIC_CHAT_API_URL || BASE;

async function get<T>(path: string, token?: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    const msg =
      (detail?.detail &&
        (typeof detail.detail === "string"
          ? detail.detail
          : (detail.detail.error ?? JSON.stringify(detail.detail)))) ??
      `${path} → ${res.status}`;
    throw new Error(msg);
  }
  return res.json();
}

async function post<T>(
  path: string,
  body: unknown,
  token?: string,
  method: "POST" | "PUT" = "POST",
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    const msg =
      (detail?.detail &&
        (typeof detail.detail === "string"
          ? detail.detail
          : (detail.detail.error ?? JSON.stringify(detail.detail)))) ??
      `${path} → ${res.status}`;
    throw new Error(msg);
  }
  return res.json();
}

export const api = {
  meta: () => get<Meta>("/meta"),
  explorer: () => get<ExplorerData>("/explorer"),
  fixturesMatrix: () => get<MatrixData>("/fixtures-matrix"),
  accuracy: () => get<AccuracyData>("/accuracy"),
  accuracyGw: (gw: number) => get<AccuracyGwDetail>(`/accuracy/${gw}`),
  projections: (players: string[]) =>
    post<ProjectionsResponse>("/projections", { players }),
  rating: (query: string) =>
    get<RatingExplain>(`/players/${encodeURIComponent(query)}/rating`),
  optimizeSquad: (
    body: { budget?: number; locked?: string[]; excluded?: string[] },
    token?: string,
  ) => post<SquadSolution>("/squad/optimize", body, token),
  rateDraft: (players: string[]) => post<SquadSolution>("/squad/rate", { players }),
  planTransfers: (
    body: {
      players?: string[];
      team_id?: number;
      bank?: number;
      free_transfers?: number;
      horizon?: number;
      alternatives?: number;
    },
    token?: string,
  ) => post<TransferPlan>("/transfers/plan", body, token),
  adviseChips: (
    body: {
      players?: string[];
      team_id?: number;
      bank?: number;
      free_transfers?: number;
      chips?: string[];
    },
    token?: string,
  ) => post<ChipAdviceResponse>("/chips/advise", body, token),
  // public FPL entry state (opens once the manager's first deadline passes)
  team: (id: string) => get<TeamState>(`/team/${encodeURIComponent(id)}`),
  // signed-in only: server-side copy of the draft + team ID (cross-device sync)
  myState: (token: string) => get<UserState>("/me/state", token),
  saveMyState: (state: UserState, token: string) =>
    post<{ ok: boolean }>("/me/state", state, token, "PUT"),
};

export interface UserState {
  draft: number[];
  team_id: string | null;
}

/** POST /chat and parse the SSE stream into typed events. */
export async function* streamChat(
  messages: { role: string; content: string }[],
  opts: { signal?: AbortSignal; token?: string } = {},
): AsyncGenerator<ChatEvent> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`;
  const res = await fetch(`${CHAT_BASE}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({ messages }),
    signal: opts.signal,
  });
  if (res.status === 401) throw new Error("sign in to chat with Pal");
  if (res.status === 429) throw new Error("chat rate limit reached — try again in a little while");
  if (!res.ok || !res.body) throw new Error(`chat → ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "message";
      let data = "";
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) {
        try {
          yield { event, data: JSON.parse(data) } as ChatEvent;
        } catch {
          // partial/garbled frame — skip
        }
      }
    }
  }
}
