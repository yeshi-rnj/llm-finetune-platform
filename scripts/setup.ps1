# One-time setup: virtual env + backend dependencies + .env + database migrations.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
$py = Join-Path $root ".venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r backend\requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    $secret = & $py -c "import secrets; print(secrets.token_urlsafe(48))"
    (Get-Content ".env") -replace '^JWT_SECRET=.*$', "JWT_SECRET=$secret" | Set-Content ".env"
    Write-Host "Created .env with a fresh JWT_SECRET"
}

Set-Location backend
& $py -m app migrate
Write-Host "Setup complete. Start the app with: .\scripts\run.ps1"
