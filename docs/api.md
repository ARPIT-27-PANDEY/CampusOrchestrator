# REST API

Interactive OpenAPI docs: `http://localhost:8000/docs`. In the deployed app the browser calls the same
paths on the frontend origin (`/api/*`), which proxies them to the backend.

## Access

In `ACCESS_MODE=password` the endpoints marked **(session)** need the `campus_session` cookie from
`POST /api/auth/login`; unsafe requests must come from an allowed `Origin`. See [security.md](security.md).

- `POST /api/auth/login` `{"password"}` -> `SessionInfo`, sets the HttpOnly cookie; 401 `invalid_password`, 429 `rate_limited`
- `POST /api/auth/logout` -> clears the cookie
- `GET /api/auth/session` -> `{access_mode: open|password, authenticated, expires_at}`

## POST /api/chat (session)
Request: `{"message": "string (1-2000 chars)", "simulate_failures": {"events": "down"}}`. `simulate_failures` is optional and needs `ALLOW_FAULT_INJECTION=true`, otherwise 403 `fault_injection_disabled`.

Response (`AgentResult`):
```json
{
  "trace_id": "a1b2…",
  "query": "…",
  "answer": "markdown text",
  "status": "ok | partial | error",
  "error_code": null,
  "insufficient_evidence": false,
  "citations": [{"number": 1, "citation_id": "8bc7a6cb06e3-p1-c0", "document_title": "Attendance policy for the students",
                 "source_filename": "iitr-attendance-policy-2024.pdf", "document_version": "…", "page": 1,
                 "section": "…", "excerpt": "…"}],
  "sources": [{"server_id": "academics", "server_name": "Academics", "tool": "search_handbook", "mode": "imported",
               "provider": "qdrant", "source_url": null, "retrieved_at": "2026-10-29T04:30:00Z", "data_as_of": null,
               "stale": null, "staleness_reason": "Newer notifications may exist…", "note": null}],
  "tool_calls": [{"call_id": "…", "tool": "academics__search_handbook", "server_id": "academics",
                  "arguments": {"query": "…"}, "status": "success", "duration_ms": 71.2, "attempts": 1,
                  "error": null, "cached": false}],
  "warnings": [],
  "citation_check": {"checked": 2, "unsupported": []},
  "provider": "groq", "model": "openai/gpt-oss-120b", "iterations": 2, "latency_ms": 2140.5,
  "usage": {"llm_calls": 2, "prompt_tokens": 4120, "completion_tokens": 310},
  "timings": {"wall_ms": 2140.5, "discovery_ms": 12.1, "first_token_ms": 1810.3, "llm_wall_ms": 1950.2,
              "llm_call_ms": [820.4, 1129.8], "tool_wall_ms": 150.7, "tool_work_ms": 71.2,
              "tool_ms_by_tool": {"academics__search_handbook": [71.2]}, "tool_retries": 0, "cache_hits": 0,
              "orchestration_ms": 27.5}
}
```

Tool call `status`: `success`, `tool_error`, `invalid_arguments`, `unknown_tool`, `timeout`, `unavailable`,
`protocol_error`, `malformed_response` (declared structured output missing), `budget_exceeded`. A run is
`partial` when at least one call ended in `timeout`, `unavailable`, `protocol_error` or `malformed_response`.
If the client disconnects, the run is cancelled (499 `client_closed_request`).

## POST /api/chat/stream (session)
Same request. Response is `text/event-stream`; each event is `event: <name>\ndata: <json>\n\n`, with `: keepalive` comments every 15 s.

| Event | Data |
|---|---|
| `start` | `{trace_id, provider, model}` |
| `discovery` | `{tool_count, servers: [{id, status}]}` |
| `llm_start` | `{iteration}` |
| `token` | `{text}`: streamed answer text |
| `answer_reset` | `{}`: discard streamed text; the model turned to tool calls |
| `tool_start` | `{call_id, tool, server_id, arguments}` |
| `tool_end` | `ToolCallSummary` |
| `error` | `{code, message}`: a provider error; a `final` event still follows |
| `final` | `AgentResult` |
| `done` | `{}`: always the last event |

## Other endpoints
- `GET /api/sources?refresh=true` -> `{servers: ServerState[], tool_count, checked_at}`
- `GET /api/tools` -> discovered tools with input schemas
- `GET /api/traces?limit=50`, `GET /api/traces/{id}` **(session)** -> stored traces (see trace privacy in [security.md](security.md))
- `GET /api/evals/latest` -> `evals/reports/latest.json` (404 `no_eval_report` if missing)
- `GET /api/evals/runs` -> saved runs `[{run_id, kind: agent|retrieval, generated_at, dataset, provider, model, transport, retriever, repeat, pass_rate, cases, legacy}]`
- `GET /api/evals/runs/{run_id}` -> one saved run
- `GET /api/metrics` **(session)** -> abuse-prevention counters
- `GET /api/health` -> `{status, version, environment, llm: {...}, mcp: {...}, time, campus_time, access_mode}`; `GET /api/health/live`

## Errors
Always `{"error": {"code": "…", "message": "…", "request_id": "…", "details"?: […]}}` with an `X-Request-ID` header.
Codes: `invalid_request` (422), `query_too_long` (422), `payload_too_large` (413), `auth_required` (401),
`invalid_password` (401), `origin_rejected` (403), `rate_limited` / `too_many_requests` (429, with
`Retry-After`), `fault_injection_disabled` (403), `unknown_server` (422), `trace_not_found` / `run_not_found` /
`not_found` (404), `no_eval_report` (404), `client_closed_request` (499), `internal_error` (500, no internals
exposed). LLM failures come back inside `AgentResult` as `status: "error"` with `error_code` in
`llm_not_configured`, `llm_auth_failed`, `llm_rate_limited`, `llm_timeout`, `llm_unavailable`, `llm_bad_request`,
`llm_malformed_tool_call`, `llm_empty_response`, `max_iterations`.

## MCP tools (discovered at runtime)

| Server | Tools |
|---|---|
| library | `search_books`, `get_book_availability`, `get_library_hours`, `discover_public_books` (when enabled) |
| events | `search_events`, `get_events_for_date`, `get_upcoming_events`, `get_event_details` |
| cafeteria | `get_today_menu`, `get_menu_for_date`, `search_menu_item`, `get_item_price`, `list_dining_locations` |
| academics | `search_handbook`, `get_policy_details` |

The backend does not hard-code these; this table is documentation only.
