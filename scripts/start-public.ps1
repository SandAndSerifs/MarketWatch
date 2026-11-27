# Make MarketPilot reachable on the internet through a free Cloudflare quick tunnel (Windows).
# Requirements: APP_PASSWORD (12+ chars) in backend\.env, and cloudflared installed:
#   winget install --id Cloudflare.cloudflared
# The public https://<random>.trycloudflare.com address is printed below and changes on every start.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = "$root\backend\.env"
if (-not (Test-Path $envFile)) { Copy-Item "$root\backend\.env.example" $envFile }
$line = Select-String -Path $envFile -Pattern '^\s*APP_PASSWORD\s*=\s*(.*)$' | Select-Object -First 1
$pw = if ($line) { $line.Matches[0].Groups[1].Value.Trim() } else { "" }
if ($pw.Length -lt 12) { Write-Host "Set APP_PASSWORD (at least 12 characters) in backend\.env first, then re-run." -ForegroundColor Red; exit 1 }
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
  Write-Host "cloudflared not found. Install it with:  winget install --id Cloudflare.cloudflared  (then open a new PowerShell window)" -ForegroundColor Red; exit 1
}

# Backend in public mode (login required for every request)
Set-Location "$root\backend"
if (-not (Test-Path ".venv")) { py -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt }
$env:PUBLIC_MODE = "true"
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m","marketpilot" -WorkingDirectory "$root\backend"

# Frontend built in same-origin mode (browser calls /api on the same address; Next.js forwards it)
Set-Location "$root\frontend"
if (-not (Test-Path "node_modules")) { npm install }
$marker = ".next\MP_MODE"
if (-not (Test-Path $marker) -or (Get-Content $marker) -ne "same-origin") {
  $env:NEXT_PUBLIC_API_URL = "same-origin"
  npm run build
  Set-Content -Path $marker -Value "same-origin"
}
Start-Process -FilePath "npm.cmd" -ArgumentList "start" -WorkingDirectory "$root\frontend"
Start-Sleep -Seconds 6

Write-Host "`nStarting Cloudflare tunnel. Look for the line with  https://....trycloudflare.com  below." -ForegroundColor Green
Write-Host "Keep this window open; closing it takes the site offline.`n"
cloudflared tunnel --url http://localhost:3000
