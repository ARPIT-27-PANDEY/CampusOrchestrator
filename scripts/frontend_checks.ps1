# Runs scripts/frontend_checks.sh inside a node:22 container (for machines without Node.js).
# node_modules and .next live in Docker volumes so the Windows checkout is not touched.
# Usage: powershell -File scripts/frontend_checks.ps1 [-Steps "lint typecheck test build"]
param([string]$Steps = "lint typecheck test build")
$root = Split-Path -Parent $PSScriptRoot
docker run --rm -v "${root}:/repo" -v campusos_fe_node_modules:/repo/frontend/node_modules `
  -v campusos_fe_next:/repo/frontend/.next -e "STEPS=$Steps" -e NEXT_TELEMETRY_DISABLED=1 -e CI=1 `
  node:22-bookworm-slim sh /repo/scripts/frontend_checks.sh
exit $LASTEXITCODE
