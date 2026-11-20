#!/usr/bin/env bash
# Start MarketPilot backend and frontend (macOS/Linux). Ctrl+C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -r requirements.txt; }
[ -f .env ] || { cp .env.example .env; echo "Created backend/.env - add your API keys."; }
.venv/bin/python -m marketpilot & BACK=$!
cd "$ROOT/frontend"
[ -d node_modules ] || npm install
[ -f .next/BUILD_ID ] || npm run build
npm start & FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null' INT TERM EXIT
echo "MarketPilot: http://localhost:3000  (API http://127.0.0.1:8000/docs)"
wait
