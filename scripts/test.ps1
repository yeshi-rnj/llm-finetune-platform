# Backend unit/integration tests + frontend checks. Browser E2E runs only if Node + Playwright are installed.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run .\scripts\setup.ps1 first." }

Set-Location backend
& $py -m unittest discover -s . -t . -v
if ($LASTEXITCODE -ne 0) { throw "Backend tests failed" }
Set-Location $root

& $py scripts\scan_secrets.py
if ($LASTEXITCODE -ne 0) { throw "Secret scan failed" }

if (Get-Command node -ErrorAction SilentlyContinue) {
    node --check frontend\app.js
    if ($LASTEXITCODE -ne 0) { throw "Frontend syntax check failed" }
    Write-Host "Frontend syntax OK. For the browser E2E: npm i -g playwright; npx playwright install chromium; node e2e\e2e.cjs"
}
