# Library MCP server — independently buildable and deployable.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY pyproject.toml requirements.lock ./
COPY library_mcp ./library_mcp

RUN pip install -r requirements.lock && pip install --no-deps . && useradd --create-home --uid 10001 mcp
USER mcp

ENV MCP_HOST=0.0.0.0 MCP_PORT=8101
EXPOSE 8101
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"MCP_PORT\"]}/health', timeout=2)"
CMD ["python", "-m", "library_mcp"]
