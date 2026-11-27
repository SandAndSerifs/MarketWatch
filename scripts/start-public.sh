#!/usr/bin/env bash
# Make MarketPilot reachable on the internet through a free Cloudflare quick tunnel (macOS/Linux).
# Requirements: APP_PASSWORD (12+ chars) in backend/.env, and cloudflared installed
# (macOS: brew install cloudflared; Linux: see docs/CLOUDFLARE.md).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENVF="$ROOT/backend/.env"
[ -f "$ENVF" ] || cp "$ROOT/backend/.env.example" "$ENVF"
PW="$(grep -E '^\s*APP_PASSWORD\s*=' "$ENVF" | head -1 | sed -E 's/^\s*APP_PASSWORD\s*=\s*//')"
if [ "${#PW}" -lt 12 ]; then echo "Set APP_PASSWORD (at least 12 characters) in backend/.env first."; exit 1; fi
command -v cloudflared >/dev/null || { echo "cloudflared not found - see docs/CLOUDFLARE.md"; exit 1; }

cd "$ROOT/backend"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
PUBLIC_MODE=true .venv/bin/python -m marketpilot & BACK=$!

cd "$ROOT/frontend"
[ -d node_modules ] || npm install
if [ "$(cat .next/MP_MODE 2>/dev/null)" != "same-origin" ]; then
  NEXT_PUBLIC_API_URL=same-origin npm run build && echo same-origin > .next/MP_MODE
fi
npm start & FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null' INT TERM EXIT
sleep 6
echo "Starting Cloudflare tunnel - look for https://....trycloudflare.com below. Ctrl+C stops everything."
cloudflared tunnel --url http://localhost:3000
