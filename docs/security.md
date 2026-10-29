# Security, access control and trace privacy

CampusOrchestrator answers questions with a quota-limited language model, so a public deployment must not
offer an unrestricted endpoint. This page describes what is implemented and how to configure it.

## Access control

| Setting | Default | Meaning |
|---|---|---|
| `ACCESS_MODE` | `open` | `open` = no sign-in (local development). `password` = shared-password gate. |
| `ACCESS_PASSWORD` | – | The shared password (>= 8 characters). Required in `password` mode. |
| `SESSION_SECRET` | – | >= 32 random characters used to sign session cookies. Required in `password` mode. |
| `SESSION_TTL_S` | 43200 (12 h) | Session lifetime. |
| `COOKIE_SECURE` | true in production | Send the cookie only over HTTPS. Set `false` only for local HTTP tests. |
| `ALLOW_OPEN_ACCESS` | `false` | Explicit override to run production without a password (deliberate public demo). |

**Fail-closed:** with `APP_ENV=production` and `ACCESS_MODE=open`, the backend refuses to start unless
`ALLOW_OPEN_ACCESS=true` is set. `password` mode refuses to start with a missing/short password or secret.
No password or secret has a default value.

How it works (`backend/app/security.py`, `backend/app/api/routes.py`):
- `POST /api/auth/login {"password"}` compares SHA-256 digests with `hmac.compare_digest` and, on success,
  sets `campus_session` = `v1.<payload>.<HMAC-SHA256>` with `HttpOnly`, `SameSite=Strict`, `Path=/`,
  `Max-Age`, and `Secure` in production. The payload holds a random session id and an expiry.
- `POST /api/auth/logout` deletes the cookie. `GET /api/auth/session` reports the mode and whether the
  visitor is signed in. The password and secret never reach the browser bundle.
- Protected: `/api/chat`, `/api/chat/stream`, `/api/traces*`, `/api/metrics`. Public: health, sources,
  tools and evaluation reports.
- **CSRF:** cookie-authenticated unsafe requests are rejected when `Sec-Fetch-Site: cross-site` or when an
  `Origin` header is present and not in `CORS_ORIGINS`. Combined with `SameSite=Strict` this blocks
  cross-site form/fetch submissions. CORS is configured but is **not** treated as authentication.

### Why the frontend proxies `/api`

The browser only talks to the Next.js origin. `frontend/src/app/api/[...path]/route.ts` forwards
`/api/*` to `BACKEND_URL` (a server-side runtime setting, never public) and streams the response back.
This keeps the session cookie first-party (the web and API services are different sites on
`*.onrender.com`, so a cookie set by the API directly would be a blocked third-party cookie), removes
CORS from the browser path, and forwards the browser's abort signal so closing a tab cancels the run.
Only the known API prefixes are proxied.

## Abuse prevention

| Setting | Default | Applies to |
|---|---|---|
| `CHAT_RATE_PER_MINUTE` / `CHAT_BURST` | 10 / 5 | Chat, per session (or per client IP in open mode) |
| `LOGIN_RATE_PER_MINUTE` | 5 | Sign-in attempts per client IP |
| `READ_RATE_PER_MINUTE` | 120 | Traces, evaluation reports, sources |
| `MAX_CONCURRENT_CHATS` | 4 | Global concurrent runs; extra requests get 429 after 2 s instead of queueing |
| `MAX_QUERY_CHARS` / request body | 2000 / 64 KB | 422 / 413 |
| `MAX_AGENT_ITERATIONS` / `MAX_TOOL_CALLS` | 5 / 8 | Per run |

Rate-limited responses are `429` with `Retry-After`. Counters (`chat_rate_limited`, `login_failed`,
`origin_rejected`, `busy_rejected`, `cancelled_on_disconnect`, …) are at `GET /api/metrics`.

The limiter is **in-memory, per process**. That is adequate for the single-instance Render deployment;
with several instances or workers, use a shared limiter (for example Redis) instead.

**Client IP and proxies.** `TRUSTED_PROXY_HOPS` (default 0) is the number of proxies in front of the
backend whose `X-Forwarded-For` entries are trusted; the client is the N-th entry from the right.
Entries further left are client-controlled and ignored. On Render the chain is
browser -> Render LB -> web proxy -> Render LB -> API, so `render.yaml` sets 2. Verify this against your
platform before relying on per-IP limits; signed-in chat is limited per session regardless.

**Cancellation.** If the browser disconnects, the streaming run is cancelled and its concurrency slot is
released (`/api/chat` polls for disconnects as well). Tested over a real socket in
`backend/tests/test_security.py`.

## Trace persistence and privacy

| Setting | Default | Meaning |
|---|---|---|
| `TRACE_BACKEND` | `memory` | `memory` (bounded, lost on restart) or `sqlite` (survives restarts) |
| `TRACE_DB_PATH` | `backend/data/traces.sqlite3` | SQLite file |
| `TRACE_CAPACITY` | 200 | Maximum stored traces (oldest removed first) |
| `TRACE_RETENTION_HOURS` | 24 | Older traces are deleted on every read/write |
| `TRACE_STORE_QUERY_TEXT` | dev: true, prod: false | When false the question is replaced by `[query not retained] #hash` |
| `TRACE_STORE_TOOL_PAYLOADS` | dev: true, prod: false | When false, tool argument values, raw result previews and long document excerpts are dropped |
| `TRACE_REDACT` | true | Always mask API keys, bearer tokens, JWTs, e-mail addresses, phone and 12-digit ID numbers |
| `TRACE_LOG_PATH` | – | Optional JSONL export with the same privacy rules |

Traces are only available to signed-in users in `password` mode. SQLite is meant for **one** backend
instance; several instances need a shared database. API keys are never part of a trace.

## Other protections (unchanged)

- MCP server allowlist (scheme + host) and DNS-rebinding protection on every MCP server.
- Tool arguments validated against discovered schemas; unknown keys rejected; all tools read-only;
  model output never chooses URLs or file paths.
- Retrieved text is untrusted: wrapped, instruction-like text redacted, injection-only passages withheld.
- The academics downloader fetches only manifest URLs on allowlisted hosts, re-checks redirects, caps
  size and requires a PDF signature.
- Secrets come only from the environment; logs pass through a redaction filter.

## Tests

`backend/tests/test_security.py` (unauthenticated/expired/tampered sessions, cookie flags, Origin and
cross-site rejection, chat and login rate limits, spoofed `X-Forwarded-For`, oversized bodies, busy
server, abandoned stream) and `backend/tests/test_trace_store.py` (redaction, query/payload omission,
retention, capacity, SQLite restart, malformed rows).
