# CampusOrchestrator upgrade plan (IIT Roorkee)

Working plan for the reliability / data / evaluation / security upgrade. Each phase ends with a short
report in the "Progress log" at the bottom. Nothing here is a claim of completion until the log says so.

## Baseline (Phase 0, 2026-10-29, Windows 10, Python 3.12.10)

| Check | Result |
|---|---|
| `services/library_mcp` pytest | 19 passed |
| `services/events_mcp` pytest | 8 passed |
| `services/cafeteria_mcp` pytest | 7 passed |
| `services/academics_mcp` pytest | 21 passed |
| `backend` pytest | 69 passed, **1 failed**: `test_server_down_mid_session_then_recovers` |
| `tests/` integration (4 servers as HTTP processes) | 12 passed |
| ruff format / ruff check / mypy --strict | clean / clean / clean (53 files) |
| frontend lint, typecheck, vitest, build | run in a `node:22` container (Node is not installed on the dev PC) |

The backend failure is a real bug: `MCPClientManager.ensure_fresh` re-checks a server only when
`now - last > interval`. With a 0 s interval and Windows' ~15 ms monotonic-clock resolution the
difference is often exactly 0, so a recovered server is never re-checked.

### What the repository actually implements (verified by reading the code)

- MCP SDK 2.3.0 (`mcp.server.MCPServer`, `mcp.Client`); four independent servers over Streamable HTTP.
- Orchestrator discovers tools dynamically; `MockProvider` is a **keyword router**, not an LLM.
  There is no real offline/local LLM provider.
- `GroqProvider` (OpenAI client), streaming with non-streaming fallback.
- Academics RAG: PyMuPDF extraction, page-bounded chunking, Qdrant (in-memory by default),
  `HashingEmbedder` (default) and `FastEmbedEmbedder` (optional extra, not installed, untested in CI).
  Re-ingestion is triggered by vector size or `embedding_model` mismatch per file.
- Corpus: two **fictional** generated PDFs (`academic_handbook_2026.pdf`, `student_services_faq_2026.pdf`).
- Evals: `campus_eval_v1.yaml` (51 cases), mock in-process and HTTP reports; `latest*.json` are overwritten each run.
- Traces: bounded in-memory store + optional append-only JSONL; no retention, redaction or access control.
- API: no authentication, no per-client rate limit (only a global semaphore of 4 chat slots), CORS only.

### Date/time defects found

| Location | Defect |
|---|---|
| `cafeteria_mcp/provider.py` `MenuProvider` | default `today = date.today` → host OS date, not campus date |
| `cafeteria_mcp/provider.py` `menu_from_pdf` | file mtime via naive `datetime.fromtimestamp` reported as `data_as_of` |
| `library_mcp/server.py` `get_library_hours` | default `dt.date.today()` → host OS date |
| `events_mcp/provider.py` `DemoEventsProvider` | timezone comes from the fixture file, not `CAMPUS_TIMEZONE` |
| `events_mcp/provider.py` `GoogleCalendarProvider` | `data_as_of` holds the *fetch time* (should be `retrieved_at`) |
| `events_mcp` | no status (cancelled/completed), no all-day/multi-day handling, no "events on date X" tool |
| `backend/app/config.py` | no `campus_timezone` setting; orchestrator relies on a hard-coded default argument |
| `evals/run_eval.py` | timezone hard-coded; HTTP transport uses the live clock while the dataset assumes a fixed one |

### External source reachability (from the dev PC, 2026-10-29)

| Source | Result | Consequence |
|---|---|---|
| iitr.ac.in Academics: Calendar / Regulations / General Notifications | 200; PDFs linked (UG Ordinance 2025, PhD Regulations 2026, Autumn 2026-27 calendar, Senate notifications) | Real corpus is feasible |
| Open Library search API | 200 | On-demand discovery adapter |
| OpenStax CMS API | 200 | Curated open-textbook adapter |
| Google Books volumes API | 429 without key | Adapter + optional `GOOGLE_BOOKS_API_KEY`; tested with recorded fixtures |
| DOAB REST | 403 | Adapter behind a flag, documented as currently blocked |
| mess.iitr.ac.in, gutendex.com | TLS errors from this network | Menu stays synthetic; Gutenberg via Open Library `ia`/`public_scan` flags only |
| iitr.ac.in/rajivbhawan/fac.html | 404 | Not used |

## Phases and acceptance criteria

**A. Timezone and provenance.** `CAMPUS_TIMEZONE` (validated, default `Asia/Kolkata`) read by backend and
every service; injectable aware clock; cafeteria/library/events agree on the campus date at the
18:29Z/18:30Z boundary; `get_events_for_date`; event status handling; provenance fields
(`retrieved_at`, `data_as_of`, `stale`, `staleness_reason`, `source_url`, `record_version`) without breaking
existing fields; Google Calendar fetch time moved to `retrieved_at`; manager recheck bug fixed.

**B. Data.** Library: `discover_public_books` (Open Library, OpenStax, Google Books optional) with the shared
access-type schema, TTL cache, rate limit, partial results; local catalogue expanded with verified
bibliographic metadata and explicitly synthetic holdings; topic/alias search. Cafeteria: four-week,
multi-location, cuisine-tagged synthetic rotation + date/location/cuisine/veg filters. Events: 80–120 records
mixing official IITR calendar dates (from the 2026-27 calendar PDF) and labelled synthetic events.
Academics: `iitr_sources.yaml` manifest, allowlisted downloader, scanned-PDF detection, applicability metadata.

**C. Retrieval evaluation.** Labelled retrieval set (dev/test split) over the real corpus; hashing vs FastEmbed vs
hybrid (RRF); Recall@1/3/5, MRR, nDCG, abstention P/R, latency; embedding identity per collection.

**D. Agent evaluation.** v2 scenario set (v1 preserved), richer per-case expectations, fault matrix, latency
breakdown (wall vs accumulated, first token), immutable run artifacts + `latest` pointer, `--repeat`,
`--yes-live` gate; extensibility test with a test-only Transport MCP server.

**E. Trust, persistence, security.** Source/freshness badges; no-results vs failure wording; trace store with
memory/SQLite backends, retention, redaction, query-text opt-in; shared-password gate with signed HttpOnly
cookies, Origin checks, per-client rate limit, trusted-proxy handling; production fail-closed.

**F. Verification and docs.** All checks green, regenerated reports, README/docs/.env.example updated, Ubuntu guide.

## Progress log

### Phase A: timezone and provenance (done)

- `campus_time.py` (validated `CAMPUS_TIMEZONE`, injectable `CampusClock`, naive = campus-local) in the backend
  and each service package; a test keeps the five copies byte-identical.
- Cafeteria: "today" computed per request in campus time; provenance splits `retrieved_at` (query),
  `imported_at` (file import), `data_as_of` (only if the source states it), validity window, `stale`
  (true / false / **null = unverifiable**) + `staleness_reason`, `record_version`. PDF mtime is no longer
  reported as `data_as_of`.
- Library: `get_library_hours` default date = campus today; `retrieved_at` vs catalogue `data_as_of`;
  synthetic holdings flagged.
- Events: provider/catalog split; statuses (scheduled/cancelled/rescheduled/completed), `timing`
  (past/ongoing/upcoming), all-day + multi-day + past-midnight overlap logic, duplicate-record handling,
  new `get_events_for_date` tool, explicit "queried successfully, nothing matched" notes, provider failure
  -> tool error. Google Calendar: `retrieved_at` = fetch time, `data_as_of` = API `updated` or null.
- Backend: `campus_timezone` setting (validated), orchestrator uses `CampusClock`, prompt states campus
  date/tomorrow explicitly, fault-injection route keeps the clock, `SourceRef` carries the new fields
  (https-only `source_url`). `ensure_fresh` `>=` fix.
- Frontend: timestamps rendered in campus time with "IST"; source tags distinguish out-of-date vs
  unverifiable vs current and show "checked" time.
- Tests: 137 -> 175 Python tests (all pass), frontend 9 -> 13. Boundary cases 18:29Z/18:30Z verified for
  cafeteria, library, events and the agent prompt, in-process across all three servers.
- Mock eval unchanged: 50/51 (rag-07 is the documented paraphrase case hashing cannot solve).
- `tzdata` added to library/cafeteria/academics (needed by `zoneinfo` on Windows); locks regenerated with uv
  for Linux and pinned to the backend's tzdata 2026.5.

### Phase B: data (done)

- Academics: `iitr_sources.yaml` (17 official documents, titles/dates from iitr.ac.in listing pages) +
  allowlisted downloader (`academics_mcp.sources`: redirect checks, size cap, PDF signature, atomic writes,
  lock file, change detection). 15 indexed (491 chunks); 2 scanned PDFs reported as needing OCR.
  `chunk_official` for regulations/notifications/calendars; manifest metadata on every chunk; supersession
  ordering + applicability notes; ingest `--dry-run`/`--json`. Default corpus switched to the official one;
  the fictional handbooks remain for v1/tests.
- Events: 122 records (83 official from the 2026-27/2025-26 calendars with document+page, Convocation
  tentative; 39 labelled synthetic). Removed synthetic EVT-109 (an invented academic date).
- Library: 138-record catalogue with Open Library-verified metadata (6 of 144 skipped, reported), synthetic
  holdings; tiered search (identifier/title/subject+aliases/author/keywords, filters, honest misses);
  `discover_public_books` (Open Library, OpenStax; Google Books opt-in) with access types, rate limits,
  retries, TTL cache and partial results. DOAB (403) and gutendex (TLS) not integrated.
- Cafeteria: synthetic four-week rotation, 3 demo locations, 82 dishes, cuisine/meal/veg filters,
  `get_menu_for_date`, `list_dining_locations`, location-specific prices; invalid files rejected.
- v1 fixtures frozen (`*_v1.json`) so the v1 benchmark stays reproducible.

### Phase C: retrieval evaluation (done)

- `retrieval_iitr_v1.yaml`: 71 labelled questions (21 dev / 50 test), labels validated against the index.
- Retrievers: hashing, FastEmbed (bge-small-en-v1.5), hybrid (BM25 + RRF) and hybrid-FastEmbed; one
  Qdrant collection per embedder; thresholds tuned on dev only; per-embedder default thresholds.
- Two bugs found in the first run of my own runner (nDCG > 1; hybrid tuning swept one threshold) were
  fixed; the invalid run is kept and documented in `evals/reports/runs/README.md`.

### Phase D: agent evaluation (done)

- `campus_eval_v2.yaml` (66 scenarios incl. MCP and model fault injection, dynamic discovery);
  v1 unchanged. Runner: exact tool sets, arguments, source modes, failure classes, repeats,
  `--yes-live`, immutable runs + descriptive `latest-*` pointers, legacy reports preserved;
  `evals/compare.py`. Run timings (wall, discovery, LLM wall, first token, tool wall vs work).
- `malformed_response` tool status; test-only Transport server + `tests/test_extensibility.py`
  (real HTTP, config-only registration, schema change, restart, no core-code mentions).
- Mock fixes found by the benchmark: plural matching, vague-question handling, abbreviation-aware
  sentence splitting; real bugs fixed: subject-vs-title-prefix ranking, OpenStax prefix matching
  ("physics" -> "Physiology").

### Phase E: trust, persistence, security (done)

- Same-origin `/api` proxy in Next.js; shared-password gate with signed HttpOnly cookies, Origin/Fetch-
  Metadata checks, fail-closed production config, per-session/IP token buckets, trusted proxy hops,
  disconnect cancellation, metrics endpoint.
- Trace store: memory/SQLite, retention, capacity, redaction, production defaults that drop query text
  and tool payloads; traces require a session.
- Frontend: sign-in gate, freshness labels, named failed services in partial answers, evaluation page
  with run history, comparison, retrieval table and the five questions.

### Phase F: verification and docs (done)

- Final code: 273 Python tests (library 52, events 36, cafeteria 30, academics 35, backend 99, integration 21),
  14 frontend tests, ruff, mypy --strict, eslint, tsc and next build pass. Render image built and smoke-tested in
  production mode with the password gate (about 425 MB of 512 MB).
- All reports regenerated from the final code (numbers unchanged from the previous runs apart from latency).
- Docs: README, DEPLOY, architecture, API, data sources, evaluation, security, demo script, .env.example, Makefile, CI.
- Not done: live Groq evaluation (opt-in, needs the owner's key and quota); screenshots not retaken; OCR for the
  two scanned PDFs; verification of TRUSTED_PROXY_HOPS on Render.
