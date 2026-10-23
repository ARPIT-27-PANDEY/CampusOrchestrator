# CampusOS AI developer commands (Linux/macOS; on Windows use the commands in README directly or WSL).
PY ?= .venv/bin/python
SERVICES := library events cafeteria academics

.PHONY: install dev servers backend frontend test test-services test-backend test-integration lint typecheck eval docker-up docker-down

install:  ## create .venv and install every package + dev tools, then frontend deps
	python3 -m venv .venv
	$(PY) -m pip install -U pip
	for s in $(SERVICES); do $(PY) -m pip install -r services/$${s}_mcp/requirements.lock -e "services/$${s}_mcp[dev]"; done
	$(PY) -m pip install -r backend/requirements.lock -e "backend[dev]" ruff mypy pyyaml types-PyYAML
	cd frontend && npm ci

servers:  ## run the four MCP servers in the background (ports 8101-8104)
	@for s in $(SERVICES); do \
	  port=$$(case $$s in library) echo 8101;; events) echo 8102;; cafeteria) echo 8103;; academics) echo 8104;; esac); \
	  MCP_PORT=$$port $(PY) -m $${s}_mcp > /tmp/campusos-$$s.log 2>&1 & echo "$$s MCP on :$$port"; \
	done

backend:  ## run the FastAPI backend on :8000
	cd backend && ../$(PY) -m uvicorn app.main:app_factory --factory --reload --port 8000

frontend:  ## run the Next.js dev server on :3000
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
	$(PY) -m mypy backend/app services/*/[a-z]*_mcp evals/run_eval.py
	cd frontend && npm run typecheck

eval:  ## deterministic eval (mock LLM, in-process MCP servers)
	$(PY) -m evals.run_eval

docker-up:
	docker compose -f infra/docker-compose.yml up --build

docker-down:
	docker compose -f infra/docker-compose.yml down
