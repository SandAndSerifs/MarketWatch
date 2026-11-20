# Phased build plan and status

Legend: ✅ built and tested in this repository · 🟡 built, needs verification with live credentials · ⬜ not started

## Phase 1 – Foundation ✅/🟡
✅ Repository layout, FastAPI backend, SQLAlchemy models (SQLite + PostgreSQL), config/secrets via `.env`
✅ NYSE calendar: holidays, early closes, special closures, DST, session phases
✅ Provider abstraction with data-quality labels; Alpaca and Massive adapters (REST + WebSocket); null provider that never fabricates
🟡 Live calls to Alpaca/Massive (adapters tested against documented response shapes with mocked HTTP; no keys in build environment)
✅ Next.js dashboard, stock search, watchlists, candlestick charts (1Min/5Min/15Min/1Hour/1Day) with overlays and indicator panes

## Phase 2 – Analysis & alerts ✅
✅ Causal indicators: SMA/EMA/RSI/MACD/Bollinger/ATR/ADX/VWAP/relative volume/ROC/Donchian, swing support/resistance
✅ Market regime + sector relative strength; scanner across universe + watchlists
✅ Signals with the 8-step checklist; five categories; trigger/invalidation tracking
✅ Alerts: dedupe, cooldown, hourly cap; in-app, desktop, email, webhook; pre-market brief, intraday watch (unusual moves, ORB, closing strength), daily summary

## Phase 3 – Autonomous paper trading ✅
✅ Experiments ($10k default), start/pause/resume/stop/reset/archive, configurable risk within hard ceilings
✅ Deterministic Risk Manager; execution simulator (spread, slippage, latency, partial/failed fills, SEC/FINRA fees)
✅ Accounting, MAE/MFE, R-multiples, equity snapshots, SPY benchmark, daily loss halt, stale-data auto-pause, emergency STOP
✅ Event awareness: earnings blackout/exit, macro release blackout

## Phase 4 – Professional intelligence ✅/🟡
✅ Curated knowledge library (39 documents across 20 categories, sourced, credibility-tagged), BM25 retrieval
✅ Market Strategist / Quant Analyst / Risk Manager roles; Devil’s-advocate challenge; post-trade review
✅ Trade Review screen with chart markers and record-grounded Q&A (works without AI)
🟡 Claude analyst + AI trade explanations (tool loop unit-tested with a fake client; needs `ANTHROPIC_API_KEY` to exercise live)

## Phase 5 – Backtesting & Strategy Lab ✅
✅ Event-driven backtester (no look-ahead, pessimistic intrabar, costs), train/validation/test, regime breakdown
✅ Historical scenario replays (2017–2025 on Alpaca history; 2008 needs a deeper-history provider)
✅ Bounded optimizer on training data only; strategy versioning with approval gate

## Phase 6 – Strategy Competition ✅
✅ Multiple agents, identical rules, risk-adjusted leaderboard, multi-curve chart vs SPY, permanent history

## Phase 7 – Advanced 🟡/⬜
🟡 Optional read-only Robinhood Trading MCP adapter (read-only allowlist enforced; not verified against live endpoint)
⬜ Point-in-time index constituents (removes survivorship bias; paid dataset)
⬜ Intraday backtesting on minute bars
⬜ AI-drafted strategy proposals written directly as draft versions (today: weekly review + manual versioning)
⬜ Authentication for remote hosting; service installers (Windows service / systemd unit)
⬜ News sentiment beyond keyword heuristics

## Recommended next steps for you
1. Add Alpaca paper keys + Finnhub key → restart → confirm the top bar shows “alpaca · Real-time (IEX only)”.
2. Run the live smoke test in docs/TESTING.md (≈10 minutes during market hours).
3. Run a 2019–2025 backtest of Trend Pullback, then the scenario replays.
4. Start a paper experiment with default risk, plus a Strategy Competition of the four main strategies.
5. Review trades weekly in Trade Review and the weekly strategy review; change strategies only via new versions.
