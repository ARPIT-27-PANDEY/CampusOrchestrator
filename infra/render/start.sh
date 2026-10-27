#!/bin/bash
# Starts the four MCP servers on 127.0.0.1 (not reachable from outside the container),
# waits for their /health routes, then runs the backend on $PORT in the foreground.
# If any MCP server exits, the container exits too, so Render restarts it.
set -eu

# The MCP servers and the backend read MCP_ALLOWED_HOSTS in different formats.
# Inside this container both defaults (localhost only) are correct, so ignore any override.
unset MCP_ALLOWED_HOSTS

start_mcp() {
  MCP_HOST=127.0.0.1 MCP_PORT="$2" python -m "$1" &
  echo "started $1 on 127.0.0.1:$2 (pid $!)"
}

start_mcp library_mcp 8101
start_mcp events_mcp 8102
start_mcp cafeteria_mcp 8103
start_mcp academics_mcp 8104

for port in 8101 8102 8103 8104; do
  tries=0
  until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$port/health', timeout=2)" 2>/dev/null; do
    tries=$((tries + 1))
    if [ "$tries" -ge 90 ]; then
      echo "MCP server on :$port did not become healthy" >&2
      exit 1
    fi
    sleep 1
  done
  echo "MCP server on :$port is healthy"
done

uvicorn app.main:app_factory --factory --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips='*' &

# Exit as soon as any child (backend or an MCP server) stops.
wait -n 2>/dev/null || true
echo "a CampusOS process exited; stopping container" >&2
kill 0 2>/dev/null || true
exit 1
