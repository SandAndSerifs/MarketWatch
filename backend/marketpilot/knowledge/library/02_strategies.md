---json
{"slug": "momentum-evidence", "title": "Momentum: cross-sectional and time-series evidence", "category": "Momentum trading",
 "tags": ["momentum", "evidence", "anomaly", "winners", "losers"],
 "sources": [
  {"title": "Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency", "authors": "Jegadeesh, N., Titman, S.", "year": 1993, "publisher": "Journal of Finance 48(1)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Time Series Momentum", "authors": "Moskowitz, T., Ooi, Y. H., Pedersen, L. H.", "year": 2012, "publisher": "Journal of Financial Economics 104(2)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Value and Momentum Everywhere", "authors": "Asness, C., Moskowitz, T., Pedersen, L. H.", "year": 2013, "publisher": "Journal of Finance 68(3)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Momentum Crashes", "authors": "Daniel, K., Moskowitz, T.", "year": 2016, "publisher": "Journal of Financial Economics 122(2)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
**Cross-sectional momentum:** stocks with the highest returns over roughly the past 3-12 months have, on average, continued to outperform past losers over the following months. The effect has been documented across many markets and asset classes.

**Time-series momentum:** an asset's own past 12-month return has predicted its near-term direction across futures markets; trend-following funds exploit this.

**Crash risk:** momentum strategies suffer rare but severe losses, typically in "rebound" markets right after a bear market, when beaten-down losers rally violently. Losses cluster when volatility is high.

**Practical implications:** momentum is a statistical tendency across many positions, not a property of one stock. Single-stock momentum trades still fail frequently; position sizing and stops matter. Academic portfolios are often monthly-rebalanced and diversified across hundreds of stocks; a five-position paper account is a much noisier test.

---json
{"slug": "trend-following", "title": "Trend following", "category": "Trend following",
 "tags": ["trend", "trend following", "cut losses", "let profits run"],
 "sources": [
  {"title": "A Century of Evidence on Trend-Following Investing", "authors": "Hurst, B., Ooi, Y. H., Pedersen, L. H.", "year": 2017, "publisher": "Journal of Portfolio Management 44(1)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Time Series Momentum", "authors": "Moskowitz, Ooi, Pedersen", "year": 2012, "publisher": "Journal of Financial Economics", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Trend following buys assets in established uptrends and exits when the trend ends. Its return profile is characteristically *positively skewed*: many small losses and scratches, a minority of large winners. Win rates of 35-45% are normal; the edge, if any, comes from average win being much larger than average loss.

Core rules practitioners use: define the trend objectively (moving averages, highs/lows), enter with the trend, cut losers quickly with predefined stops, let winners run with trailing exits, size positions by volatility.

Psychological trap: long losing streaks are normal and tempt traders to abandon or modify a system right before a large winner. MarketPilot prevents silent rule changes: every modification is a new version that must be re-tested.

---json
{"slug": "pullbacks-in-trends", "title": "Buying pullbacks within uptrends", "category": "Trend following",
 "tags": ["pullback", "buy the dip", "trend", "entry timing"],
 "sources": [
  {"title": "Evidence of Predictable Behavior of Security Returns", "authors": "Jegadeesh, N.", "year": 1990, "publisher": "Journal of Finance 45(3)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Returns to Buying Winners and Selling Losers", "authors": "Jegadeesh, Titman", "year": 1993, "publisher": "Journal of Finance", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
A pullback strategy combines two documented tendencies: intermediate-term trend continuation (momentum) and very short-term reversal (one-week to one-month losers tend to bounce). The idea is to enter an established uptrend during a temporary dip rather than after an extended run.

Typical structure: (1) trend filter (price above rising 50-day and 200-day averages); (2) pullback condition (short-term oversold, e.g. 2-period RSI very low, or price back near the 20-day EMA); (3) confirmation (price trades back above the prior day's high) to avoid catching a dip that keeps falling; (4) stop below the pullback low; (5) target in multiples of risk; (6) time stop.

**How it fails:** the "pullback" is the start of a trend reversal (often news-driven); the market regime turns risk-off; the stock is extended and the dip is shallow so the stop sits too close.

---json
{"slug": "mean-reversion", "title": "Mean reversion", "category": "Mean reversion",
 "tags": ["mean reversion", "reversal", "oversold", "rsi2"],
 "sources": [
  {"title": "Fads, Martingales, and Market Efficiency", "authors": "Lehmann, B.", "year": 1990, "publisher": "Quarterly Journal of Economics 105(1)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Evidence of Predictable Behavior of Security Returns", "authors": "Jegadeesh, N.", "year": 1990, "publisher": "Journal of Finance", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Short-horizon (days to a month) returns of individual stocks have shown negative autocorrelation: recent losers tend to bounce and recent winners give back some gains. Part of this is attributed to liquidity provision (buyers are paid for absorbing temporary selling pressure) and overreaction.

Mean-reversion systems usually have high win rates and small average wins relative to losses (negative skew). That profile is dangerous: one large loss can erase many small wins. Rules that help: trade only liquid names, only in long-term uptrends, avoid news-driven drops (earnings misses, guidance cuts, fraud allegations), use time stops, and keep positions small.

---json
{"slug": "short-term-reversal-evidence", "title": "Short-term reversal and news vs no-news moves", "category": "Mean reversion",
 "tags": ["reversal", "news", "earnings", "drift"],
 "sources": [
  {"title": "Fads, Martingales, and Market Efficiency", "authors": "Lehmann, B.", "year": 1990, "publisher": "QJE", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium?", "authors": "Bernard, V., Thomas, J.", "year": 1989, "publisher": "Journal of Accounting Research 27", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Not all drops are alike. Price moves without identifiable news have tended to reverse more than moves driven by fundamental news; news-driven moves (notably earnings surprises) have shown continuation ("drift") in the direction of the news. Practical rule: before buying an oversold stock, check whether the drop has a fundamental cause. MarketPilot flags negative-keyword headlines in the challenge step, but keyword matching is only a heuristic and can miss context.

---json
{"slug": "breakouts", "title": "Breakout trading", "category": "Breakout strategies",
 "tags": ["breakout", "donchian", "new highs", "volume"],
 "sources": [
  {"title": "Simple Technical Trading Rules and the Stochastic Properties of Stock Returns", "authors": "Brock, Lakonishok, LeBaron", "year": 1992, "publisher": "Journal of Finance", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Bollinger on Bollinger Bands", "authors": "Bollinger, J.", "year": 2001, "publisher": "McGraw-Hill", "type": "practitioner-book", "credibility": "medium"}
 ], "updated": "2026-11-20"}
---
A breakout buys when price exceeds a recent high (e.g. the prior 20- or 55-day high) on the expectation that a new trend leg is starting. Trading-range-break rules were among those studied in early academic work on technical rules.

Quality filters practitioners use: an existing uptrend, a period of contracting volatility before the break, and rising volume on the breakout day. Entries are usually buy-stop orders slightly above the level so the order only fills if the market proves the breakout.

---json
{"slug": "failed-breakouts", "title": "Failed breakouts and bull traps", "category": "Breakout strategies",
 "tags": ["failed breakout", "bull trap", "false signal"],
 "sources": [
  {"title": "What Do We Know About the Profitability of Technical Analysis?", "authors": "Park, Irwin", "year": 2007, "publisher": "Journal of Economic Surveys", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Many breakouts fail: price pokes above resistance, triggers buy-stops, then reverses back into the range. Signs of elevated failure risk: low volume on the break, a broad market in a downtrend, the breakout happening right into a major overhead level, or a break that occurs late in an already extended move.

Defences: small initial size, a stop that is hit quickly if the move reverses back into the range, and willingness to re-enter if the setup re-forms. Expect a breakout system's hit rate to be low; judge it by expectancy over many trades.

---json
{"slug": "volatility-contraction", "title": "Volatility contraction before expansion", "category": "Breakout strategies",
 "tags": ["volatility", "squeeze", "contraction", "range"],
 "sources": [
  {"title": "Bollinger on Bollinger Bands", "authors": "Bollinger, J.", "year": 2001, "publisher": "McGraw-Hill", "type": "practitioner-book", "credibility": "medium"},
  {"title": "Volatility-Managed Portfolios", "authors": "Moreira, A., Muir, T.", "year": 2017, "publisher": "Journal of Finance 72(4)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Volatility clusters: calm periods tend to follow calm periods and turbulent ones follow turbulence, but extremes mean-revert over time. Narrow trading ranges (low Bollinger width percentile, small ATR relative to history) often precede range expansion. The contraction says *a move is likely*, not *which direction*; trend context decides the bias.

---json
{"slug": "vwap", "title": "VWAP (Volume-Weighted Average Price)", "category": "Volume and liquidity",
 "tags": ["vwap", "intraday", "execution", "institutional"],
 "sources": [
  {"title": "The Total Cost of Transactions on the NYSE", "authors": "Berkowitz, S., Logue, D., Noser, E.", "year": 1988, "publisher": "Journal of Finance 43(1)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
VWAP is the cumulative (typical price x volume) divided by cumulative volume since the session open. Institutions use it as an execution benchmark: buying below VWAP is considered good execution. Intraday traders read price above VWAP as buyers in control for the session.

Caveat for MarketPilot users on the free Alpaca IEX feed: intraday volume comes from a single exchange (IEX), so VWAP is IEX-weighted and can differ from the consolidated VWAP that institutions see.
