# Start MarketPilot backend and frontend on Windows (PowerShell).
# First run: creates the Python venv and installs dependencies.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"
if (-not (Test-Path ".venv")) { py -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt }
if (-not (Test-Path ".env")) { Copy-Item .env.example .env; Write-Host "Created backend\.env - add your API keys, then re-run." }
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m","marketpilot" -WorkingDirectory "$root\backend"
Set-Location "$root\frontend"
if (-not (Test-Path "node_modules")) { npm install }
if (-not (Test-Path ".next\BUILD_ID")) { npm run build }
Start-Process -FilePath "npm.cmd" -ArgumentList "start" -WorkingDirectory "$root\frontend"
Start-Sleep -Seconds 4
Start-Process "http://localhost:3000"
