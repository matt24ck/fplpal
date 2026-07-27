import type {
  ChatEvent,
  ExplorerData,
  MatrixData,
  Meta,
  ProjectionsResponse,
  RatingExplain,
  SquadSolution,
} from "./types";

/** Proxied to the FastAPI engine via next.config.ts rewrites. */
const BASE = "/api/engine";

/** Chat goes direct to the engine in production (Vercel's rewrite proxy
 * times out on long SSE streams). Falls back to the same-origin proxy in
 * dev. Build-time inlined — set in the Vercel project env. */
const CHAT_BASE = process.env.NEXT_PUBLIC_CHAT_API_URL || BASE;

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body: unknown, token?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
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
  projections: (players: string[]) =>
    post<ProjectionsResponse>("/projections", { players }),
  rating: (query: string) =>
    get<RatingExplain>(`/players/${encodeURIComponent(query)}/rating`),
  optimizeSquad: (
    body: { budget?: number; locked?: string[]; excluded?: string[] },
    token?: string,
  ) => post<SquadSolution>("/squad/optimize", body, token),
  rateDraft: (players: string[]) => post<SquadSolution>("/squad/rate", { players }),
};

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
