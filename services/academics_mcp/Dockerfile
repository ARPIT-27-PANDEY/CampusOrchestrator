# Academics MCP server (PDF ingestion + Qdrant retrieval).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY pyproject.toml requirements.lock requirements-fastembed.lock ./
COPY academics_mcp ./academics_mcp
# INSTALL_FASTEMBED=1 adds semantic search (fastembed + ONNX runtime) and bakes the BAAI/bge-small-en-v1.5
# model into the image (~130 MB download at build time, ~+250 MB image). 0 keeps the small offline image.
ARG INSTALL_FASTEMBED=0
ENV FASTEMBED_CACHE_PATH=/srv/models
RUN if [ "$INSTALL_FASTEMBED" = "1" ]; then pip install -r requirements-fastembed.lock; else pip install -r requirements.lock; fi \
    && pip install --no-deps . && useradd --create-home --uid 10001 mcp \
    && if [ "$INSTALL_FASTEMBED" = "1" ]; then python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"; fi \
    && mkdir -p /srv/models && chown -R mcp /srv/models
# Official IIT Roorkee PDFs (fetched with: python -m academics_mcp.sources fetch) + their manifest.
COPY data/iitr /srv/iitr
COPY data/sources /srv/sources
USER mcp

ENV MCP_HOST=0.0.0.0 MCP_PORT=8104 HANDBOOK_DIR=/srv/iitr SOURCE_MANIFEST=/srv/sources/iitr_sources.yaml
EXPOSE 8104
HEALTHCHECK --interval=15s --timeout=3s --retries=10 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8104/health', timeout=2)"
CMD ["python", "-m", "academics_mcp"]
