# Proposed initial strategy: Trend Pullback (v1.0.0)

Goal: a simple, explainable, long-only swing strategy whose **first priority is capital preservation**, used to
learn whether the decision process produces a measurable edge over SPY after costs. It is not presented as
profitable; it must earn that label through out-of-sample backtests *and* forward paper trading.

## Idea
Buy temporary dips inside established uptrends, but only after the dip shows signs of ending. This combines two
documented tendencies — intermediate-term momentum and very-short-term reversal (Jegadeesh & Titman 1993;
Jegadeesh 1990; Lehmann 1990) — see the knowledge-library entries `pullbacks-in-trends` and `momentum-evidence`.

## Rules (evaluated on completed daily bars)
1. **Universe**: ~80 liquid large caps and sector/index ETFs (≥ $20M average daily dollar volume, price ≥ $5).
2. **Trend filter**: close > 50-day SMA > 200-day SMA, and the 50-day SMA is rising; ADX(14) ≥ 15.
3. **Pullback**: RSI(2) ≤ 15, *or* a down day closing within 1 ATR of the 20-day EMA.
4. **Entry trigger**: buy-stop at the prior day’s high + 0.05 ATR, valid for 2 sessions (only fills if buyers return).
5. **Stop**: below the 5-day low minus 0.1 ATR, but never wider than 2.5 ATR.
6. **Target**: 2R. **Breakeven** stop after +1R. **Time stop**: 10 sessions.
7. **Thesis exit**: a daily close below the 50-day SMA → exit at the next open.

## Strict risk controls (enforced by the Risk Manager, not the strategy)
| Control | Default | Hard ceiling |
|---|---|---|
| Position notional | 5% of starting equity ($500 on $10k) | 20% |
| Risk per trade (at stop) | 0.5% of equity | 2% |
| Concurrent positions | 5 | 10 |
| Positions per sector | 2 | 5 |
| Daily loss limit | 2% of starting equity → halt entries for the session | 5% |
| Min reward:risk | 1.5 | floor 0.8 |
| Max stop distance | 10% | – |
| Max spread | 25 bps | – |
| Earnings | no new swing entry within 3 sessions; exit open positions before the report | – |
| Macro releases | no entries 60 min before → 30 min after FOMC/CPI/NFP | – |
| Session | regular hours only; not in the first 5 or last 10 minutes | – |
| Data | stale/unavailable data → automatic pause | – |
| Always | long-only, cash-only: no margin, leverage, options or shorting | not configurable |

With $10,000 the 5% notional cap usually binds, so actual risk per trade is often ~$15–30. Most of the account
sits in cash. That is intended.

## Devil’s advocate (Step 5) – objections that downgrade or block a trade
Risk-off or high-volatility market regime; weak sector; resistance < 1R above entry; extended > 3.5 ATR above the
50-day; RSI(14) > 75; outsized last move; illiquidity; earnings ahead (blocking) or unverified; macro event within 3
days; negative headlines (keyword heuristic); correlated existing exposure; delayed or IEX-only data; unproven /
negative out-of-sample evidence. One blocking objection or two serious ones → no entry.

## How we decide whether it works
1. **Backtest** 2019-2025 (Strategy Lab): train / validation / out-of-sample = 60/20/20 chronologically, realistic
   costs, pessimistic intrabar assumptions. Do not tune on the test segment.
2. **Scenario replays**: 2020 crash and rebound, 2022 bear, 2024 vol shock, 2025 tariff selloff — check drawdowns
   and that the regime filter keeps the strategy mostly in cash during bear phases.
3. **Forward paper trading** for at least 3 months / 30+ closed trades alongside a **Strategy Competition** with the
   other built-ins.
4. **Evidence bar** (“supported”): out-of-sample profit factor ≥ 1.2, expectancy > 0R, ≥ 30 trades, and forward
   results not materially worse than backtest, with drawdown below SPY’s over the same period. Otherwise it remains
   “unproven/weak”, and changes go through new versions — never silent edits.
5. **Kill criteria**: forward max drawdown > 8% of starting equity, or forward expectancy < 0 after 30 trades →
   stop, review, re-version.

## Known weaknesses
Whipsaws in choppy markets; gaps through stops (earnings handled, macro/news gaps not); survivorship bias in a
static universe; small-account statistics are noisy; IEX-only live quotes on the free plan.
