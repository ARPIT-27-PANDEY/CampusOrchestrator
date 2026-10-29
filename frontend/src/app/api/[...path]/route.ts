import type { NextRequest } from "next/server";

/**
 * Same-origin proxy to the FastAPI backend.
 *
 * The browser talks only to this Next.js origin, so the backend's session cookie is first-party
 * (HttpOnly, SameSite=Strict) and no CORS is needed. BACKEND_URL is a server-side setting read at
 * request time; it is never exposed to the browser bundle. Streaming responses (SSE) are passed
 * through unbuffered, and the browser's abort signal is forwarded so a closed tab cancels the run.
 */
const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
const FORWARD_REQUEST_HEADERS = [
  "accept",
  "content-type",
  "cookie",
  "origin",
  "sec-fetch-site",
  "user-agent",
  "x-request-id",
  "x-forwarded-for",
];
const FORWARD_RESPONSE_HEADERS = ["content-type", "cache-control", "retry-after", "x-request-id", "x-accel-buffering"];
const ALLOWED_PREFIXES = ["auth", "chat", "sources", "tools", "traces", "evals", "health", "metrics"];

async function proxy(request: NextRequest, ctx: RouteContext<"/api/[...path]">): Promise<Response> {
  const { path } = await ctx.params;
  if (!path.length || !ALLOWED_PREFIXES.includes(path[0]) || path.some((p) => p === ".." || p.includes("/"))) {
    return Response.json({ error: { code: "not_found", message: "Unknown API path." } }, { status: 404 });
  }
  const target = `${BACKEND_URL}/api/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer(),
      signal: request.signal,
      cache: "no-store",
      redirect: "manual",
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") return new Response(null, { status: 499 });
    return Response.json(
      { error: { code: "backend_unreachable", message: "The CampusOrchestrator backend is not reachable." } },
      { status: 502 },
    );
  }
  const out = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export const GET = proxy;
export const POST = proxy;
