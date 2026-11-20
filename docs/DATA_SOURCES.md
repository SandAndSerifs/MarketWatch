# Data sources: recommendation, latency and cost

Researched 2026-11-20. Prices change; confirm on the vendors' pages before subscribing.

## Recommendation

| Stage | Market data | Earnings | Macro calendar | AI |
|---|---|---|---|---|
| **Start (free)** | **Alpaca Basic** – real-time IEX + consolidated (SIP) history older than 15 min | **Finnhub** free tier | Seeded official dates (Fed, BLS) + manual entries with source | Optional (Claude) |
| **Serious paper trading** | **Alpaca Algo Trader Plus ($99/mo)** – real-time SIP, unlimited WebSocket symbols | Finnhub | same | Claude |
| **Alternative / deeper history** | **Massive** (formerly Polygon.io) real-time stocks tier | Finnhub or Benzinga via Massive | same | Claude |

Why Alpaca first: the free plan gives genuine real-time prices (IEX venue) for live monitoring and **full consolidated
daily history** (2016 onwards) for indicators and backtests, with one key that also works for the optional
Alpaca paper-trading API. MarketPilot uses the consolidated history for all daily indicators, so volume-based
signals are not distorted by IEX’s small market share.

## Provider comparison

| | Alpaca Basic (free) | Alpaca Algo Trader Plus | Massive Stocks Starter | Massive real-time tiers |
|---|---|---|---|---|
| Live prices | Real-time, **IEX only** (~2–3% of volume) | Real-time **SIP** (all exchanges) | **15-min delayed** | Real-time (SIP on top tier) |
| History | SIP bars since 2016, must be ≥15 min old | SIP, no delay limit | Multi-year aggregates | Deeper history |
| WebSocket | Yes, small symbol limit (~30) | Unlimited symbols | Delayed cluster | Real-time cluster |
| REST limit | ~200 req/min | ~10,000 req/min | Plan-dependent | Unlimited on top tier |
| Movers / most-active | Yes (screener) | Yes | Yes (snapshot gainers/losers) | Yes |
| News | Yes (Benzinga feed) | Yes | Yes | Yes |
| Price | $0 | ~$99/mo | ~$29/mo | sources disagree: ~$79 (IEX-based real-time) to ~$199 (full SIP) per month |
| Index levels (SPX, NDX, DJI) | Not included → ETF proxies | Not included → ETF proxies | Separate Indices product | Separate Indices product |

Sources: Alpaca market-data docs (`docs.alpaca.markets/docs/about-market-data-api`), Alpaca forum statements on SIP
history access for free accounts, Massive knowledge base (real-time vs delayed WebSocket clusters,
`socket.massive.com` vs `delayed.massive.com`), Massive comparison pages. Polygon.io became Massive on 2025-10-30;
existing keys and `api.polygon.io` keep working (MarketPilot uses `api.massive.com`).

### How MarketPilot labels data
Every quote carries provider, feed and timestamps. The UI shows **“Real-time (IEX only)”**, **“Real-time
(consolidated)”** or **“Delayed N min”**. Checklists flag IEX-only and delayed data. Index cards are explicitly labelled
“ETF proxy”.

## Latency budget (design targets, not measured here)

| Path | Expected latency | Notes |
|---|---|---|
| Exchange → Alpaca/Massive WebSocket → backend | typically sub-second | network-dependent; not measured in this build environment |
| REST snapshot poll (baseline, always on) | 15 s cadence in session; 60 s pre/after hours | keeps working if the stream drops |
| Backend → dashboard (WebSocket hub) | milliseconds on localhost | |
| Paper engine tick | 20 s | entries/exits checked each tick |
| Simulated order latency | 300 ms (configurable) | fill uses the quote after the delay |
| Daily-bar decisions | after the close / pre-market | swing strategies are not latency-sensitive |
| Stale-data guard | 90 s without a successful response → auto-pause | resumes after 2 healthy checks |

The default strategies trade daily setups, so seconds of latency are immaterial; the IEX-vs-SIP *coverage* question
matters more than milliseconds. Intraday strategies (VWAP Reclaim) are marked forward-test only.

## Event data

* **FOMC**: dates fetched from `federalreserve.gov/monetarypolicy/fomccalendars.htm` (2026 Dec 9; 2027 schedule as
  revised 2026-11-12, including the Oct 27 strategy-only meeting with no decision). Decisions at 14:00 ET.
* **CPI / Employment Situation**: BLS release schedules (CPI 2026-12-10, 2027-01-13, 2027-02-11; jobs 2026-12-04,
  2027-01-08, 2027-04-02, 2027-07-02), 08:30 ET. Only verified dates are seeded; add more in Settings with a source.
* **Earnings**: Finnhub `/calendar/earnings` (free key), refreshed daily at 06:00 ET for the scan universe; bmo/amc
  timing respected. Without it, earnings risk is reported as unverified.

## Costs at a glance

| Item | Monthly |
|---|---|
| Alpaca Basic + Finnhub free + no AI | **$0** |
| + Claude analyst, ~10 questions/day | roughly $30–75 (Claude Opus 5.5 at $4/$20 per million input/output tokens; a tool-using question typically uses ~10–40k input and 1–2k output tokens ⇒ ~$0.10–0.25). Set `AI_MODEL=claude-sonnet-5-5` ($2/$10) to roughly halve it. |
| + Alpaca Algo Trader Plus | +$99 |
| Hosting on an always-on PC | electricity only; small cloud VM ≈ $5–20 |

## Regulatory fees used by the simulator
SEC Section 31: $20.60 per $1M of sale proceeds (effective 2026-04-04; sec.gov fee rate advisory). FINRA TAF:
$0.000195/share, max $9.79 per trade (2026 schedule; FINRA has filed to pause TAF for Oct–Dec 2026 — status not
confirmed, so the simulator keeps charging it, which is conservative). Commissions default to $0.
