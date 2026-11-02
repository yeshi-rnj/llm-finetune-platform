# Start the server (loads variables from .env).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run .\scripts\setup.ps1 first." }

if (Test-Path ".env") {
    foreach ($line in Get-Content ".env") {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$' -and -not $line.TrimStart().StartsWith("#")) {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"'), "Process")
        }
    }
}
Set-Location backend
& $py -m app
