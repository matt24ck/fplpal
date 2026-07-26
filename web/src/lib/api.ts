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

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    const msg =
      (detail?.detail && (detail.detail.error ?? JSON.stringify(detail.detail))) ??
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
  optimizeSquad: (body: { budget?: number; locked?: string[]; excluded?: string[] }) =>
    post<SquadSolution>("/squad/optimize", body),
  rateDraft: (players: string[]) => post<SquadSolution>("/squad/rate", { players }),
};

/** POST /chat and parse the SSE stream into typed events. */
export async function* streamChat(
  messages: { role: string; content: string }[],
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages }),
    signal,
  });
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
