# CampusOrchestrator developer commands (Linux/macOS; on Windows use the commands in README directly or WSL).
PY ?= .venv/bin/python
SERVICES := library events cafeteria academics

.PHONY: install dev servers stop-servers backend frontend test test-services test-backend test-integration lint \
        typecheck eval eval-v1 eval-http eval-faults eval-retrieval eval-retrieval-all eval-compare fetch-sources \
        check-sources ingest docker-up docker-down

install:  ## create .venv and install every package + dev tools, then frontend deps
	python3 -m venv .venv
	$(PY) -m pip install -U pip
	for s in $(SERVICES); do $(PY) -m pip install -r services/$${s}_mcp/requirements.lock -e "services/$${s}_mcp[dev]"; done
	$(PY) -m pip install -r backend/requirements.lock -e "backend[dev]" ruff mypy pyyaml types-PyYAML
	cd frontend && npm ci

servers:  ## run the four MCP servers in the background (ports 8101-8104); logs in /tmp/campusos-*.log
	@for s in $(SERVICES); do \
	  port=$$(case $$s in library) echo 8101;; events) echo 8102;; cafeteria) echo 8103;; academics) echo 8104;; esac); \
	  MCP_PORT=$$port $(PY) -m $${s}_mcp > /tmp/campusos-$$s.log 2>&1 & echo "$$s MCP on :$$port (pid $$!)"; \
	done

stop-servers:  ## stop MCP servers started with `make servers`
	-pkill -f "python -m (library|events|cafeteria|academics)_mcp" || true

backend:  ## run the FastAPI backend on :8000
	cd backend && ../$(PY) -m uvicorn app.main:app_factory --factory --reload --port 8000

frontend:  ## run the Next.js dev server on :3000 (proxies /api to BACKEND_URL, default :8000)
	cd frontend && npm run dev

dev: servers backend

test: test-services test-backend test-integration  ## all Python tests (each suite runs in its own pytest process)
	cd frontend && npm test

test-services:
	for s in $(SERVICES); do (cd services/$${s}_mcp && ../../$(PY) -m pytest -q) || exit 1; done

test-backend:
	cd backend && ../$(PY) -m pytest -q

test-integration:
	$(PY) -m pytest tests -q

lint:
	$(PY) -m ruff format --check backend services tests evals
	$(PY) -m ruff check backend services tests evals
	cd frontend && npm run lint

typecheck:
	$(PY) -m mypy backend/app services/*/[a-z]*_mcp evals/run_eval.py evals/run_retrieval.py evals/compare.py
	cd frontend && npm run typecheck

fetch-sources:  ## download the curated official IIT Roorkee PDFs (allowlisted hosts only)
	cd services/academics_mcp && ../../$(PY) -m academics_mcp.sources fetch

check-sources:  ## report official documents that changed or are missing
	cd services/academics_mcp && ../../$(PY) -m academics_mcp.sources check

ingest:  ## (re)build the academics index and print the ingestion report
	cd services/academics_mcp && ../../$(PY) -m academics_mcp.ingest --json

eval:  ## agent benchmark v2 (mock LLM, in-process MCP servers, deterministic)
	$(PY) -m evals.run_eval

eval-v1:  ## the original 51-case benchmark
	$(PY) -m evals.run_eval --dataset evals/datasets/campus_eval_v1.yaml

eval-http:  ## v2 against MCP servers already running (make servers)
	$(PY) -m evals.run_eval --transport http

eval-faults:  ## fault-injection scenarios only
	$(PY) -m evals.run_eval --category failure --category llm_failure --category tool_budget

eval-retrieval:  ## retrieval benchmark, offline retrievers, thresholds tuned on dev
	$(PY) -m evals.run_retrieval --retrievers hashing,hybrid --tune

eval-retrieval-all:  ## + FastEmbed (needs the optional extra; downloads ~130 MB once)
	$(PY) -m evals.run_retrieval --retrievers hashing,fastembed,hybrid,hybrid-fastembed --tune

eval-compare:  ## list saved runs; compare with: $(PY) -m evals.compare RUN_A RUN_B
	$(PY) -m evals.compare --list

docker-up:
	docker compose -f infra/docker-compose.yml up --build

docker-down:
	docker compose -f infra/docker-compose.yml down
