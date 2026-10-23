# CampusOS AI — development conventions

Monorepo: `frontend/` (Next.js 16), `backend/` (FastAPI + orchestrator), `services/*_mcp/` (4 independent MCP servers), `evals/`, `tests/` (integration), `infra/`.

## Rules
- MCP SDK is **v2.3.0** (`from mcp.server import MCPServer`, `from mcp import Client`). Don't use v1 `FastMCP`/`ClientSession` examples.
- The orchestrator must never hardcode tool names; tools come from MCP discovery (`backend/app/mcp/manager.py`).
- All tools are read-only. Model-generated arguments must never choose URLs or file paths.
- Every tool result includes a `source` block with `mode` = demo | imported | live. Never label demo/imported data live.
- Groq: no `messages[].name`, no `parallel_tool_calls`; keep provider-specific code inside `backend/app/llm/groq.py`.
- Don't add a silent fallback LLM. Tests must run without network or API keys (mock provider).
- This is Next.js 16 — read `frontend/node_modules/next/dist/docs/` before using unfamiliar APIs (see `frontend/AGENTS.md`).

## Commands (repo root, venv at `.venv`)
```bash
make install                      # all packages from lock files + npm ci
make test                         # each Python suite in its own pytest process + vitest
make lint typecheck               # ruff format/check, eslint, mypy --strict, tsc (via next typegen)
make eval                         # 51-case deterministic benchmark -> evals/reports/latest.{json,md}
(cd services/academics_mcp && ../../.venv/bin/python -m pytest -q)   # one service
(cd backend && ../.venv/bin/python -m pytest -q)
.venv/bin/python -m pytest tests -q   # integration (spawns the 4 servers over HTTP)
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```
Run Python suites separately: `backend/tests` and `tests/` are both packages named `tests`.

## Dependency pins
Each package has `requirements.lock` (Python 3.12 runtime pins). After changing a `pyproject.toml`:
`uv pip compile <pkg>/pyproject.toml --python-version 3.12 -o <pkg>/requirements.lock --no-header` and keep the header comment.

## Demo data
Regenerate the fictional handbook PDFs with `python services/academics_mcp/scripts/generate_demo_pdfs.py`, then re-run `make eval` and update README numbers only from the generated report.
