# Runs every deterministic check on Windows (same set as `make test lint typecheck` + eval).
# Usage: powershell -File scripts/check_all.ps1 [-SkipFrontend]
param([switch]$SkipFrontend)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$results = [ordered]@{}

function Run-Step($name, $dir, [scriptblock]$cmd) {
  Push-Location $dir
  $out = & $cmd 2>&1 | Out-String
  $code = $LASTEXITCODE
  Pop-Location
  $tail = ($out -split "`n" | Where-Object { $_.Trim() } | Select-Object -Last 3) -join " / "
  $results[$name] = "exit=$code  $tail"
  Write-Output "=== $name (exit $code)"
  Write-Output $out
}

foreach ($s in "library", "events", "cafeteria", "academics") {
  Run-Step "pytest $s" (Join-Path $root "services\${s}_mcp") { & $py -m pytest -q -p no:cacheprovider }
}
Run-Step "pytest backend" (Join-Path $root "backend") { & $py -m pytest -q -p no:cacheprovider }
Run-Step "pytest integration" $root { & $py -m pytest tests -q -p no:cacheprovider }
Run-Step "ruff format" $root { & $py -m ruff format --check backend services tests evals scripts }
Run-Step "ruff check" $root { & $py -m ruff check backend services tests evals scripts }
Run-Step "mypy" $root { & $py -m mypy backend/app services/library_mcp/library_mcp services/events_mcp/events_mcp services/cafeteria_mcp/cafeteria_mcp services/academics_mcp/academics_mcp evals/run_eval.py evals/run_retrieval.py evals/run_library_search.py evals/compare.py }
if (-not $SkipFrontend) {
  $fe = Join-Path $root "frontend"
  Run-Step "npm lint" $fe { npm run lint }
  Run-Step "npm typecheck" $fe { npm run typecheck }
  Run-Step "npm test" $fe { npm test }
  Run-Step "npm build" $fe { npm run build }
}
Write-Output "`n===== SUMMARY"
$results.GetEnumerator() | ForEach-Object { Write-Output ("{0,-20} {1}" -f $_.Key, $_.Value) }
