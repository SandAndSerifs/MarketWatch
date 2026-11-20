# MarketPilot

Personal AI-assisted stock-market intelligence and **paper-trading** platform for U.S. equities and ETFs.

* **Mode 1 – Monitoring & alerts:** scans the market on completed daily bars, runs every idea through an
  8-step checklist (thesis → evidence → *argue against it* → risk → decision), and sends plain-English
  BUY CANDIDATE / SELL-EXIT / WATCH / HOLD-MANAGE / NO TRADE alerts with entry, stop, target, reward:risk,
  reasons it could fail and what would invalidate it.
* **Mode 2 – Autonomous paper trading:** experiments start with **$10,000 of hypothetical money**, use live
  market data, simulate fills with spread / slippage / latency / partial fills / regulatory fees, and track
  P&L, hit rate, drawdowns and the SPY benchmark. Every trade has a full audit trail and a post-trade review.

> **Safety:** MarketPilot contains **no code that places real orders**. The paper engine cannot reach a broker.
> Risk controls are deterministic Python that no AI component can bypass. The optional Robinhood connector
> is read-only, disabled by default, and independent of paper trading. Nothing here is financial advice;
> past or simulated performance does not predict future results.

## Quick start

Requirements: **Python 3.11+** (3.13 tested), **Node.js 20+** (22 tested). Works on Windows, macOS and Linux.

### 1. Backend (FastAPI)

Windows PowerShell:
```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # then edit .env and add your keys
python -m marketpilot       # API on http://127.0.0.1:8000  (docs at /docs)
```
macOS / Linux:
```bash
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env
python -m marketpilot
```

### 2. Frontend (Next.js)
```bash
cd frontend
npm install
npm run build && npm start   # http://localhost:3000   (or `npm run dev` while developing)
```
If the backend is not on `http://127.0.0.1:8000`, set `NEXT_PUBLIC_API_URL` (see `frontend/.env.example`) before building.

Shortcut scripts: `scripts/start.ps1` (Windows) and `scripts/start.sh` (macOS/Linux) start both.

### 3. Minimum configuration for real data

| What | Variable(s) in `backend/.env` | Cost |
|---|---|---|
| Market data (required) | `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` (paper-account keys from alpaca.markets) | Free (IEX real-time + 15-min-delayed consolidated history). $99/mo for real-time consolidated (SIP). |
| Earnings dates (strongly recommended) | `FINNHUB_API_KEY` | Free tier |
| AI analyst (optional) | `ANTHROPIC_API_KEY` | Pay per use (see docs/DATA_SOURCES.md) |
| Phone/email alerts (optional) | `ALERT_WEBHOOK_URL` (e.g. ntfy.sh topic) / SMTP vars | Free |

Without a market-data key the app starts, but every market-facing panel shows *"not configured"* — it never
substitutes invented data. Without Finnhub, every checklist states that earnings dates are **unverified**.

## Using it

1. **Dashboard** – ETF-proxy index levels (SPY/QQQ/DIA/IWM), regime, sector heatmap, movers, unusual volume,
   news, upcoming FOMC/CPI/jobs releases and earnings, alerts, paper-trading summary. Every price shows its feed.
2. **Market Scanner** – run a scan or wait for the automatic pre-market/after-close scans; click a signal to see the
   complete checklist.
3. **Autonomous Paper Trader** – *New experiment* → pick a strategy (default: **Trend Pullback**), keep the default
   risk limits, **Start**. The engine arms setups after the close, enters only when the trigger trades and the Risk
   Manager re-approves with live data, and manages stops/targets/time-stops. **STOP** (top bar) halts everything.
4. **Trade History / Trade Review** – open any trade: chart with entry/exit markers, stop/target lines, indicators at
   entry, original thesis, supporting and conflicting evidence, sizing, costs, exit reason, post-trade review, and
   one-click answers to *“Why did you buy? What triggered it? Why did you sell? What would have invalidated it?
   Was it a good decision? What can be learned?”* — built only from the recorded data.
5. **Strategy Lab** – backtest on genuine history with train / validation / out-of-sample segments, replay
   historical regimes (2020 crash, 2022 bear, 2025 tariff selloff, …), bounded parameter search on the training
   segment only, and permanent strategy versioning.
6. **Strategy Competition** – run several strategies side by side with identical capital/risk/universe; ranked by a
   risk-adjusted score, not raw return.
7. **Performance Analytics** – equity vs SPY, drawdowns, daily/weekly/monthly reports, and the weekly strategy review
   (which checklist objections actually preceded losing trades).
8. **AI Market Analyst** – questions answered with tool calls to live data, recorded trades and the knowledge
   library; statements labelled Fact / Interpretation / Estimate / Uncertain.

Background monitoring and paper trading run in the backend process; the browser can be closed.

## Documentation

* [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) – provider comparison, latency, cost, recommendation
* [docs/STRATEGY.md](docs/STRATEGY.md) – the proposed initial strategy and its strict risk controls
* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) – components, decision pipeline, safety boundaries
* [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md) – phased build plan and current status
* [docs/TESTING.md](docs/TESTING.md) – testing approach and how to validate with live data
* [docs/STATUS.md](docs/STATUS.md) – completed features, outstanding work, known issues

## Tests
```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest -q        # 86 tests (SQLite)
MP_TEST_DATABASE_URL=postgresql+psycopg://user@host/db python -m pytest -q      # same suite on PostgreSQL
cd frontend && npm run typecheck && npm run build
```
