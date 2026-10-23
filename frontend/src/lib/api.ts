import type {
  AgentResult,
  AgentTrace,
  ApiErrorBody,
  EvalReport,
  HealthResponse,
  SourcesResponse,
  TraceListItem,
} from "./types";

export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function readError(resp: Response): Promise<ApiError> {
  try {
    const body = (await resp.json()) as ApiErrorBody;
    return new ApiError(resp.status, body.error.code, body.error.message);
  } catch {
    return new ApiError(resp.status, "http_error", `Request failed with HTTP ${resp.status}.`);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE_URL}${path}`, { signal, cache: "no-store" });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "backend_unreachable", `Can't reach the CampusOS backend at ${API_BASE_URL}.`);
  }
  if (!resp.ok) throw await readError(resp);
  return (await resp.json()) as T;
}

export const api = {
  health: (signal?: AbortSignal) => getJson<HealthResponse>("/api/health", signal),
  sources: (refresh = false, signal?: AbortSignal) =>
    getJson<SourcesResponse>(`/api/sources${refresh ? "?refresh=true" : ""}`, signal),
  traces: (signal?: AbortSignal) => getJson<TraceListItem[]>("/api/traces?limit=50", signal),
  trace: (id: string, signal?: AbortSignal) => getJson<AgentTrace>(`/api/traces/${encodeURIComponent(id)}`, signal),
  evals: (signal?: AbortSignal) => getJson<EvalReport>("/api/evals/latest", signal),
};

export interface StreamOptions {
  simulateFailures?: Record<string, "down" | "timeout">;
  signal?: AbortSignal;
}

/** POST /api/chat/stream and yield parsed SSE events. */
export async function* streamChat(
  message: string,
  opts: StreamOptions = {},
): AsyncGenerator<{ event: string; data: unknown }> {
  const { parseSSEChunk } = await import("./sse");
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE_URL}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ message, simulate_failures: opts.simulateFailures }),
      signal: opts.signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "backend_unreachable", `Can't reach the CampusOS backend at ${API_BASE_URL}.`);
  }
  if (!resp.ok || !resp.body) throw await readError(resp);
  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    const parsed = parseSSEChunk(buffer + value);
    buffer = parsed.rest;
    for (const ev of parsed.events) yield ev;
  }
}

export type { AgentResult };
