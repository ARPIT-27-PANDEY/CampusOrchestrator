#!/bin/sh
# Frontend checks: lint, typecheck, unit tests, production build.
# Runs anywhere Node 22 is available; scripts/frontend_checks.ps1 runs it in a container.
cd "$(dirname "$0")/../frontend" || exit 1
npm ci --no-audit --no-fund || exit 1
status=0
for step in ${STEPS:-lint typecheck test build}; do
  echo "=== npm run $step"
  if npm run "$step"; then echo "=== $step: PASS"; else echo "=== $step: FAIL"; status=1; fi
done
exit $status
