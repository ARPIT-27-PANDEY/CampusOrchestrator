# Render image: the backend API plus the four MCP servers in one container.
# Each MCP server still runs as its own process and is reached over Streamable HTTP
# on 127.0.0.1, so discovery, routing and provenance work exactly as in docker-compose.
# Only the backend listens publicly (on Render's $PORT).
#
# Build context is the repo root:
#   docker build -f infra/render/Dockerfile -t campusos-api .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Pinned dependencies first (cached layer). The five lock files have no conflicting pins.
COPY backend/requirements.lock locks/backend.lock
COPY services/library_mcp/requirements.lock locks/library.lock
COPY services/events_mcp/requirements.lock locks/events.lock
COPY services/cafeteria_mcp/requirements.lock locks/cafeteria.lock
COPY services/academics_mcp/requirements.lock locks/academics.lock
RUN pip install -r locks/backend.lock -r locks/library.lock -r locks/events.lock \
        -r locks/cafeteria.lock -r locks/academics.lock

# The four MCP servers.
COPY services/library_mcp/pyproject.toml services/library_mcp/
COPY services/library_mcp/library_mcp services/library_mcp/library_mcp
COPY services/events_mcp/pyproject.toml services/events_mcp/
COPY services/events_mcp/events_mcp services/events_mcp/events_mcp
COPY services/cafeteria_mcp/pyproject.toml services/cafeteria_mcp/
COPY services/cafeteria_mcp/cafeteria_mcp services/cafeteria_mcp/cafeteria_mcp
COPY services/academics_mcp/pyproject.toml services/academics_mcp/
COPY services/academics_mcp/academics_mcp services/academics_mcp/academics_mcp
COPY services/academics_mcp/data/iitr iitr
COPY services/academics_mcp/data/sources sources
RUN pip install --no-deps ./services/library_mcp ./services/events_mcp \
        ./services/cafeteria_mcp ./services/academics_mcp

# Backend (laid out as in the repo so evals/reports/latest.json resolves by default).
COPY backend/pyproject.toml backend/
COPY backend/app backend/app
COPY backend/config backend/config
RUN pip install --no-deps ./backend
COPY evals/reports/latest.json evals/reports/latest.json

COPY infra/render/start.sh /usr/local/bin/campusos-start
RUN sed -i 's/\r$//' /usr/local/bin/campusos-start && chmod +x /usr/local/bin/campusos-start \
    && useradd --create-home --uid 10001 api
USER api

WORKDIR /app/backend
ENV HANDBOOK_DIR=/app/iitr SOURCE_MANIFEST=/app/sources/iitr_sources.yaml APP_ENV=production LOG_JSON=true PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=10 CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health/live', timeout=2)"
CMD ["campusos-start"]
