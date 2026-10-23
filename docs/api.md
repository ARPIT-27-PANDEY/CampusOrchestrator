# REST API

Interactive OpenAPI docs: `http://localhost:8000/docs`.

## POST /api/chat
Request: `{"message": "string (1–2000 chars)", "simulate_failures": {"events": "down"}}`. `simulate_failures` is optional and needs `ALLOW_FAULT_INJECTION=true`, otherwise the request gets 403 `fault_injection_disabled`.

Response (`AgentResult`):
```json
{
  "trace_id": "a1b2…",
  "query": "…",
  "answer": "markdown text",
  "status": "ok | partial | error",
  "error_code": null,
  "insufficient_evidence": false,
  "citations": [{"number": 1, "citation_id": "9554771d7a8d-p4-c2", "document_title": "Academic Handbook 2026-27",
                 "source_filename": "academic_handbook_2026.pdf", "document_version": "ce1e90b84acc",
                 "page": 4, "section": "Section 3 - Course Prerequisites", "excerpt": "…"}],
  "sources": [{"server_id": "library", "server_name": "Library", "tool": "search_books", "mode": "demo",
               "provider": "demo-json", "data_as_of": "2026-10-01", "stale": null}],
  "tool_calls": [{"call_id": "…", "tool": "library__search_books", "server_id": "library", "arguments": {"query": "…"},
                  "status": "success", "duration_ms": 71.2, "attempts": 1, "error": null, "cached": false}],
  "warnings": [],
  "citation_check": {"checked": 2, "unsupported": []},
  "provider": "groq", "model": "openai/gpt-oss-120b", "iterations": 3, "latency_ms": 2140.5,
  "usage": {"llm_calls": 3, "prompt_tokens": 4120, "completion_tokens": 310}
}
```

## POST /api/chat/stream
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
- `GET /api/sources?refresh=true` → `{servers: ServerState[], tool_count, checked_at}`
- `GET /api/tools` → discovered tools with input schemas
- `GET /api/traces?limit=50`, `GET /api/traces/{id}` → in-memory traces (discovery, LLM turns with usage, tool calls with result previews)
- `GET /api/evals/latest` → contents of `evals/reports/latest.json` (404 `no_eval_report` if missing)
- `GET /api/health` → `{status: ok|degraded, llm: {provider, model, configured, error}, mcp: {configured, available, tools}}`; `GET /api/health/live`

## Errors
Always `{"error": {"code": "…", "message": "…", "request_id": "…", "details"?: […]}}` with an `X-Request-ID` header.
Codes: `invalid_request` (422), `query_too_long` (422), `payload_too_large` (413), `too_many_requests` (429), `fault_injection_disabled` (403), `unknown_server` (422), `trace_not_found` / `not_found` (404), `no_eval_report` (404), `internal_error` (500, no internals exposed). LLM failures come back inside `AgentResult` as `status: "error"` with `error_code` in `llm_not_configured`, `llm_auth_failed`, `llm_rate_limited`, `llm_timeout`, `llm_unavailable`, `llm_bad_request`, `llm_malformed_tool_call`, `llm_empty_response`, `max_iterations`.
