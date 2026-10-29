# Library MCP server — independently buildable and deployable.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY pyproject.toml requirements.lock requirements-fastembed.lock ./
COPY library_mcp ./library_mcp

# INSTALL_FASTEMBED=1 adds semantic search (fastembed + ONNX runtime) and bakes the BAAI/bge-small-en-v1.5
# model into the image (~130 MB download at build time, ~+250 MB image). 0 keeps the small offline image.
ARG INSTALL_FASTEMBED=0
ENV FASTEMBED_CACHE_PATH=/srv/models
RUN if [ "$INSTALL_FASTEMBED" = "1" ]; then pip install -r requirements-fastembed.lock; else pip install -r requirements.lock; fi \
    && pip install --no-deps . && useradd --create-home --uid 10001 mcp \
    && if [ "$INSTALL_FASTEMBED" = "1" ]; then python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"; fi \
    && mkdir -p /srv/models && chown -R mcp /srv/models
USER mcp

ENV MCP_HOST=0.0.0.0 MCP_PORT=8101
EXPOSE 8101
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"MCP_PORT\"]}/health', timeout=2)"
CMD ["python", "-m", "library_mcp"]
