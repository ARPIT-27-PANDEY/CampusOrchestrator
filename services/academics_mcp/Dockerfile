# Academics MCP server (PDF ingestion + Qdrant retrieval).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY pyproject.toml requirements.lock ./
COPY academics_mcp ./academics_mcp
RUN pip install -r requirements.lock && pip install --no-deps . && useradd --create-home --uid 10001 mcp
# Official IIT Roorkee PDFs (fetched with: python -m academics_mcp.sources fetch) + their manifest.
COPY data/iitr /srv/iitr
COPY data/sources /srv/sources
USER mcp

ENV MCP_HOST=0.0.0.0 MCP_PORT=8104 HANDBOOK_DIR=/srv/iitr SOURCE_MANIFEST=/srv/sources/iitr_sources.yaml
EXPOSE 8104
HEALTHCHECK --interval=15s --timeout=3s --retries=10 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8104/health', timeout=2)"
CMD ["python", "-m", "academics_mcp"]
