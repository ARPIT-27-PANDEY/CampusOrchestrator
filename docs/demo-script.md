# Demo script (about 5 minutes)

Start everything with Docker Compose, or locally with `make servers` and `make frontend`, plus the backend started with fault injection enabled:
`cd backend && ALLOW_FAULT_INJECTION=true uvicorn app.main:app_factory --factory --port 8000`. Open http://localhost:3000.

1. **Single source.** On *Ask*, type *"What are the library hours on Sunday?"* The route shows one stop (Library `get_library_hours`, `date="…"`); the answer gives 12:00–18:00 and a hatched "Library Demo data" tag. Point out that the model passed a resolved date and only one of the 11 discovered tools ran.
2. **Multi-server.** Click the first example: *"Find the next AI workshop, check whether Introduction to Algorithms is available…"* Four stops appear live: Events `search_events`, Library `search_books`, Academics `search_handbook`, then Library `get_book_availability` (a follow-up that uses the `book_id` from the search). Cafeteria is never called.
3. **RAG with citations.** In the same answer, expand *[1] Academic Handbook 2026-27, page 4*. Show the excerpt, file name, version hash and passage id. Then ask *"What does the handbook say about parking permits?"* and show the *No supporting passage found* notice: nothing is quoted.
4. **Simulated failure.** Open *Failure testing*, choose **Events**, and ask the step 2 question again. The Events stop turns red (*Unreachable after 2 attempts*), the answer is marked **Partial**, and the Library and Academics parts still arrive with their citation. Optionally stop the real container (`docker compose -f infra/docker-compose.yml stop events-mcp`) and refresh *Sources* to see *Unavailable*, then start it again.
5. **Execution trace.** Click *Open trace*. Walk through tool discovery (11 tools, 4 servers), each model turn (requested tools and token usage on Groq), each MCP call with arguments, status, attempts and duration, and *Result returned to the model*, the structured server result that was wrapped as untrusted data for the model.

Close on *Evaluation*: 51 cases, what the mock numbers do and don't prove, and the known `rag-07` failure.
