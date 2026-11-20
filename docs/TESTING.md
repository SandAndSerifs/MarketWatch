# Testing approach

## Automated (run on every change)

```bash
cd backend && python -m pytest -q                         # 86 tests, ~10 s
MP_TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/mp_test python -m pytest -q
cd frontend && npm run typecheck && npm run build
```

| Area | What is verified |
|---|---|
| Calendar | NYSE holidays 2021/2025/2026/2027 incl. weekend observance and the 2025 day of mourning; early closes; DST shifts of the UTC open; session phases; Thanksgiving |
| Indicators | Known values; independent Wilder-RSI reference; **causality** of every indicator (value at i unchanged when future data is removed); `profile_at(i)` == profile of truncated bars; swing levels ignore unconfirmed pivots; JSON-safety |
| Risk Manager | Sizing math and binding constraint; forbidden settings (short/margin/leverage) rejected; ceilings clamped; **each of 14 rules can veto**; earnings/macro blackouts; unverified earnings is a warning |
| Execution | Ask/bid + slippage; stale/no quote rejection; wide-spread rejection; one-sided quote assumption; limit marketability; partial fills; SEC/FINRA fee math incl. TAF cap |
| Paper engine (E2E with fixture data and a controlled clock) | Setup → trigger → re-check → fill → target exit with review; stop exit through a gap; duplicate-entry prevention; stale-data auto-pause with hysteresis; daily loss halt; emergency STOP; no entries outside the session |
| Backtester | Chronological disjoint segments; **future-bar corruption does not change past trades** (no look-ahead); pessimistic entry-day stop; gap-through-stop fills at open; intraday strategy refused |
| Providers | Alpaca bars pagination, SIP history parameter, snapshots, 429 retry, auth errors, stream messages; Massive aggregates & snapshots; paper-host guard; timestamp parsing; corrupt-bar rejection |
| Checklist | Objections and falsifiers; timing vs structural classification |
| Platform | Knowledge library sourced & searchable; alert cooldown; Robinhood read-only allowlist; paper/risk packages never import brokerage code; Claude tool loop (fake client) sends adaptive thinking + fallbacks and returns tool results; full API flow with no provider (never fabricates) |
| Statistics | Small-sample handling, Wilson CI, undefined profit factor, Sharpe requires ≥20 days, leaderboard score does not reward luck or risk |

### Browser E2E (isolated fixture)
`backend/tests/e2e_fixture_server.py` boots the real API on synthetic data labelled **TEST FIXTURE**, drives a real
engine trade, and stores a fixture backtest. A Playwright script then loads all 15 routes, checks key content,
answers a Trade Review question, checks zero console errors and no horizontal scroll at 390 px. (Synthetic data is
used only here; the application never ships it.)

## Live smoke test (needs your keys, ~10 minutes in market hours)
1. Start backend; `GET /api/status` → `data.configured: true`, `healthy: true`, quality label as expected.
2. Dashboard: SPY/QQQ/DIA/IWM prices match your broker within the feed’s expected tolerance; timestamps advance.
3. `/analysis/AAPL` at 1Min and 1Day: bars present; last daily bar flagged as forming during the session.
4. Watchlist: add a symbol; price updates via the live link (green dot).
5. Scanner → Run scan: signals appear with full checklists (no errors in Settings → job errors).
6. Paper trader: create default experiment → Start → “Scan now” shows evaluated/proposals/armed counts.
7. Disconnect network for 2 minutes → experiment shows “Automatically paused”; reconnect → resumes.
8. Press STOP → all experiments halted; clear STOP.
9. Settings → Refresh earnings (Finnhub) → events list shows earnings with bmo/amc.
10. AI analyst (if configured): ask “What are the strongest bullish setups right now?” → answer cites tool lookups.

## Forward-testing protocol (strategy validation)
* Minimum 3 months and 30 closed trades per strategy version before drawing conclusions.
* Compare with SPY over the identical snapshot period; examine drawdown, not just return.
* Use the weekly strategy review to find objections associated with losses; test any rule change as a new version
  (backtest with out-of-sample segment, then forward paper) before using it.
