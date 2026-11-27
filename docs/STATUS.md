# Status, dependencies and known issues

_Last updated: 2026-11-27_

## Verified in this environment
* Backend: 91 automated tests pass on SQLite (86 also verified on PostgreSQL before the auth tests were added).
* Remote access: password login, sessions, rate limiting and the Cloudflare fail-safe are tested; the login flow,
  sign-out and live WebSocket were verified in a browser through the single-port (same-origin) setup.
* Frontend: TypeScript strict typecheck and production build pass; `npm audit` reports 0 vulnerabilities.
* Browser E2E: all 15 routes render with zero console errors against the backend running on labelled fixture data,
  including a real engine-driven paper trade, the Trade Review Q&A and the mobile layout.
* With no provider configured, every market-facing endpoint returns an explicit “not configured” error (503) —
  confirmed by test.

## Not verified here (needs your credentials)
| Component | Why | How to verify |
|---|---|---|
| Live Alpaca / Massive REST & WebSocket | No API keys in the build environment (endpoints reachable; 401 without keys) | Live smoke test, docs/TESTING.md |
| Finnhub earnings refresh | No key | Settings → Refresh earnings |
| Claude analyst / AI trade explanations | No key; loop tested with a fake client | Ask a question in AI Market Analyst |
| Email / webhook delivery | No SMTP/webhook configured | Trigger an alert with severity ≥ warning |
| Cloudflare quick/named tunnel | Tunnels must run on your PC; the PowerShell scripts could not be executed here (no PowerShell) | Run `scripts\start-public.ps1` |
| Robinhood read-only MCP | Requires OAuth token from Robinhood’s agent authorization; handshake not exercised | `GET /api/brokerage/portfolio` after enabling |

## Dependencies & credentials
* Required for market data: Alpaca account (free) **or** Massive subscription.
* Recommended: Finnhub free key (earnings). Optional: Anthropic API key, SMTP, ntfy topic.
* Python 3.11+, Node 20+. PostgreSQL optional (SQLite default).

## Known issues / limitations
1. **IEX-only live data on the free Alpaca plan**: live volume, quote sizes and intraday VWAP are single-venue. Daily
   indicators use consolidated history; intraday relative volume is understated (flagged in the UI).
2. **Index levels** are ETF proxies (SPY/QQQ/DIA/IWM); true index values need a separate indices data product.
3. **Survivorship bias** in backtests on the static large-cap universe (warned on every run).
4. **No historical earnings calendar** in backtests (blackout/exit not simulated historically; enforced live).
5. Alpaca SIP history starts in 2016, so the 2008 scenario needs a deeper-history provider.
6. VWAP Reclaim (intraday) is forward-test only; intraday backtesting is not implemented.
7. Macro calendar contains only dates verified from official sources on 2026-11-20 (FOMC through Nov 2027; CPI/NFP
   for a few upcoming releases). Add further releases in Settings with their source.
8. Negative-news detection is a keyword heuristic.
9. Single-user password login only (no per-user accounts). For remote access use public mode (docs/CLOUDFLARE.md).
10. Free-plan WebSocket symbol limit (~30): the stream covers the most relevant symbols; the REST poller covers the rest
    every 15 seconds.
11. Next.js `next dev` hot-reload websocket may not work behind some proxies/sandboxes; `npm run build && npm start`
    is unaffected.

## Security notes
* Secrets only in `backend/.env` (git-ignored); settings endpoint reports only whether keys are set.
* Next.js pinned to 16.4.5, which fixes advisories GHSA-mfr8-8qww-v76h, GHSA-vc7v-qv4w-wrv8, GHSA-7qx7-33qx-rqx2 and
  GHSA-f3mh-rxg3-f5g2 affecting ≤ 16.4.4.
