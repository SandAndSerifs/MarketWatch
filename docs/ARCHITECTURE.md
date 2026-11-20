# Architecture

```
                         ┌────────────────────── Next.js frontend (port 3000) ──────────────────────┐
                         │ 14 sections · lightweight-charts · WebSocket live quotes/alerts · desktop  │
                         │ notifications · no secrets in the browser                                  │
                         └───────────────▲──────────────────────────────▲─────────────────────────────┘
                                         │ REST /api/*                  │ WS /api/ws
┌────────────────────────────────────────┴──────────────────────────────┴───────────────────────────────┐
│ FastAPI backend (python -m marketpilot, port 8000) – owns ALL background work                          │
│                                                                                                         │
│  data/            providers/{alpaca,massive}.py ─► MarketDataService (quote cache, staleness, REST poller, │
│                   calendar.py (NYSE holidays, early closes, DST)        stream supervisor w/ backoff, hub) │
│  analysis/        indicators (causal) · technicals (TechSeries.profile_at) · regime · performance stats   │
│  strategies/      Market Strategist role: 8 built-ins + custom rules; versioned by parameter hash          │
│  decision/        checklist.py: 8 steps, Devil's-advocate challenge, Quant Analyst view, classification   │
│                   review.py: deterministic post-trade review                                              │
│  risk/            RiskManager: deterministic, itemised verdicts, hard ceilings, veto power                │
│  paper/           execution.py (spread/slippage/latency/partial/rejects/fees) · accounting.py · engine.py │
│  backtest/        event-driven daily backtester, segments, scenarios, bounded optimizer                   │
│  services/        runtime (scheduler by session phase) · scanner (Mode 1) · analysis glue · reports       │
│  alerts/          dedupe + cooldown + hourly cap → in-app, desktop, email (SMTP), webhook (ntfy)          │
│  events/          FOMC/CPI/NFP seeds (official sources) · Finnhub earnings                                │
│  knowledge/       curated library (markdown + sources) · BM25 retrieval (RAG)                            │
│  ai/              provider abstraction · Anthropic (Claude) tool loop · read-only analyst tools           │
│  brokerage/       OPTIONAL read-only Robinhood MCP adapter (disabled; not imported by paper/ or risk/)   │
│  db.py            SQLAlchemy models → SQLite (default) or PostgreSQL                                      │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Decision pipeline (every signal and every paper trade)
1. **Market conditions** – regime from SPY (50/200-day, realized vol, drawdown) + sector relative strength + events.
2. **Stock analysis** – technical profile on completed daily bars, liquidity, spread, news.
3. **Thesis** – produced by the strategy (Market Strategist).
4. **Confirming evidence** – strategy-specific observations.
5. **Challenge** – deterministic objections with severities + explicit falsifiers (“what would prove it wrong”),
   plus the Quant Analyst’s evidence status for that exact strategy version.
6. **Risk assessment** – Risk Manager verdict: every rule itemised, sizing with the binding constraint.
7. **Decision** – BUY_CANDIDATE / WATCH / NO_TRADE (timing-only failures become gates re-checked at trigger).
8. **Post-trade evaluation** – written on exit; separates process quality from outcome.

The record is stored verbatim (`decisions.record`). When a paper trigger fires, the checklist is **re-run with live
data** and stored as a new decision linked to the armed setup. Trade explanations (UI and AI) read only these records.

## Safety boundaries
* No order-submission code exists for any real broker. Alpaca is used for data and reference endpoints only, and the
  provider refuses to start if the reference host is not the paper host.
* The paper engine’s only path to a fill is `ExecutionSimulator`; entries require an approved `RiskVerdict`.
* Idempotent client order ids (unique per experiment) + armed-setup state prevent duplicate entries.
* Stops only tighten. Stale data pauses actions. Daily loss limit halts entries. Emergency STOP halts all.
* Experiments with open positions keep being managed even when paused/stopped (stops stay active).
* The AI’s tools are read-only; it cannot create orders, size positions or change strategies.
* Strategy changes create new versions; experiments can only be reconfigured while stopped (audited).

## Scheduling (America/New_York, holiday-aware)
| When | Job |
|---|---|
| 06:00 | Earnings refresh (Finnhub) |
| ≥ 08:30 trading days | Full scan + pre-market brief |
| any time a new completed session exists | Arm setups for each running daily experiment |
| ≥ 09:35 | SELL/EXIT & HOLD/MANAGE signals for open positions |
| regular session, every 20 s | Paper engine tick (marks, stops, targets, triggers) |
| regular session, every 5 min | Trigger/invalidation/unusual-move/ORB/closing-strength alerts; intraday strategies |
| every 30 min in session | Equity snapshots (with SPY) |
| after the close | Close snapshot, daily summary, post-close scan |

## Data model (main tables)
`watchlists`, `watchlist_items`, `signals`, `decisions`, `alerts`, `experiments`, `pending_setups`, `orders`,
`fills`, `trades`, `positions`, `equity_snapshots`, `strategy_versions`, `backtest_runs`, `market_events`,
`knowledge_docs`, `ai_messages`, `audit_log`, `app_settings`.

## Deployment
Local: two processes (backend, frontend). Always-on: run the backend as a service (Windows Task Scheduler / NSSM,
systemd, or Docker) with `DATABASE_URL` pointing to PostgreSQL (`docker-compose.yml` provides one). The dashboard
can be closed; monitoring and paper trading continue while the backend runs. Keep the API bound to 127.0.0.1 or put
it behind an authenticated reverse proxy — it has no user authentication of its own (single-user design).
