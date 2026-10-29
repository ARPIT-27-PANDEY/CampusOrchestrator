import type {
  AgentResult,
  AgentTrace,
  ApiErrorBody,
  EvalReport,
  EvalRunInfo,
  HealthResponse,
  RetrievalReport,
  SessionInfo,
  SourcesResponse,
  TraceListItem,
} from "./types";

/**
 * Empty by default: the browser calls this site's own /api/*, which the Next.js route handler
 * proxies to the backend (first-party session cookie, no CORS). Set NEXT_PUBLIC_API_BASE_URL only
 * to bypass the proxy in development (access control then needs ACCESS_MODE=open).
 */
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly retryAfterS: number | null = null,
  ) {
    super(message);
  }
}

async function readError(resp: Response): Promise<ApiError> {
  const retry = Number(resp.headers.get("retry-after"));
  const retryAfter = Number.isFinite(retry) && retry > 0 ? retry : null;
  try {
    const body = (await resp.json()) as ApiErrorBody;
    return new ApiError(resp.status, body.error.code, body.error.message, retryAfter);
  } catch {
    return new ApiError(resp.status, "http_error", `Request failed with HTTP ${resp.status}.`, retryAfter);
  }
}

const UNREACHABLE = "Can't reach the CampusOrchestrator backend. It may be starting up; try again in a minute.";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store", credentials: "same-origin", ...init });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "backend_unreachable", UNREACHABLE);
  }
  if (!resp.ok) throw await readError(resp);
  return (await resp.json()) as T;
}

const getJson = <T,>(path: string, signal?: AbortSignal) => request<T>(path, { signal });
const postJson = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  health: (signal?: AbortSignal) => getJson<HealthResponse>("/api/health", signal),
  session: (signal?: AbortSignal) => getJson<SessionInfo>("/api/auth/session", signal),
  login: (password: string) => postJson<SessionInfo>("/api/auth/login", { password }),
  logout: () => postJson<SessionInfo>("/api/auth/logout", {}),
  sources: (refresh = false, signal?: AbortSignal) =>
    getJson<SourcesResponse>(`/api/sources${refresh ? "?refresh=true" : ""}`, signal),
  traces: (signal?: AbortSignal) => getJson<TraceListItem[]>("/api/traces?limit=50", signal),
  trace: (id: string, signal?: AbortSignal) => getJson<AgentTrace>(`/api/traces/${encodeURIComponent(id)}`, signal),
  evals: (signal?: AbortSignal) => getJson<EvalReport>("/api/evals/latest", signal),
  evalRuns: (signal?: AbortSignal) => getJson<EvalRunInfo[]>("/api/evals/runs", signal),
  evalRun: <T = EvalReport | RetrievalReport,>(id: string, signal?: AbortSignal) =>
    getJson<T>(`/api/evals/runs/${encodeURIComponent(id)}`, signal),
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
      credentials: "same-origin",
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "backend_unreachable", UNREACHABLE);
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
