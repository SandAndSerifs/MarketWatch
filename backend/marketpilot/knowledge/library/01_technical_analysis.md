---json
{"slug": "technical-analysis-evidence", "title": "What the evidence says about technical analysis", "category": "Technical analysis",
 "tags": ["evidence", "technical analysis", "data snooping"],
 "sources": [
  {"title": "Simple Technical Trading Rules and the Stochastic Properties of Stock Returns", "authors": "Brock, W., Lakonishok, J., LeBaron, B.", "year": 1992, "publisher": "Journal of Finance 47(5)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "What Do We Know About the Profitability of Technical Analysis?", "authors": "Park, C.-H., Irwin, S.", "year": 2007, "publisher": "Journal of Economic Surveys 21(4)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Foundations of Technical Analysis", "authors": "Lo, A., Mamaysky, H., Wang, J.", "year": 2000, "publisher": "Journal of Finance 55(4)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Technical analysis studies price and volume to estimate the balance of supply and demand. The academic record is mixed and that mixture is the key lesson:

* Early studies of simple moving-average and trading-range rules on long US index histories found returns after buy signals that differed from returns after sell signals. Later work showed much of this weakened after the rules became widely known and once transaction costs were included.
* Surveys of the literature find many studies reporting profits, but also flag frequent methodological problems: data snooping (testing many rules and reporting the best), ignoring costs, and not adjusting for risk.
* Pattern-recognition work using statistical smoothing found that some classic chart patterns carry incremental information about the distribution of returns, without implying a reliable profit after costs.

**How MarketPilot uses this:** indicators are treated as *descriptive evidence* inside a checklist, never as a guarantee. Every strategy is a fixed, versioned rule set that must be tested out-of-sample, after realistic costs, before anyone should trust it. The system argues against each setup and records what would prove it wrong.

---json
{"slug": "moving-averages", "title": "Moving averages (SMA/EMA) and trend definition", "category": "Technical analysis",
 "tags": ["sma", "ema", "trend", "crossover", "indicator"],
 "sources": [
  {"title": "Simple Technical Trading Rules and the Stochastic Properties of Stock Returns", "authors": "Brock, Lakonishok, LeBaron", "year": 1992, "publisher": "Journal of Finance", "type": "peer-reviewed", "credibility": "high"},
  {"title": "A Century of Evidence on Trend-Following Investing", "authors": "Hurst, B., Ooi, Y. H., Pedersen, L. H.", "year": 2017, "publisher": "Journal of Portfolio Management 44(1)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
A simple moving average (SMA) is the arithmetic mean of the last *n* closes; an exponential moving average (EMA) weights recent closes more (alpha = 2/(n+1)). Both lag price by construction.

Common practitioner uses:
* **Trend filter:** price above a rising 200-day average is a widely used definition of a long-term uptrend; 50-day for the intermediate trend; 20-day EMA for the short-term.
* **Crossovers:** a shorter average crossing above a longer one signals a possible trend change. Crossovers whipsaw in sideways markets; most of the signal's value comes from staying with long trends, accepting many small losses.
* **Dynamic support:** in strong trends, pullbacks often pause near the 20-day EMA or 50-day SMA.

**Failure modes:** sideways, range-bound markets (repeated false crosses); sharp V-shaped reversals (averages react too late); gap moves around news.

---json
{"slug": "rsi", "title": "Relative Strength Index (RSI)", "category": "Technical analysis",
 "tags": ["rsi", "momentum oscillator", "overbought", "oversold", "wilder"],
 "sources": [
  {"title": "New Concepts in Technical Trading Systems", "authors": "Wilder, J. W.", "year": 1978, "publisher": "Trend Research", "type": "practitioner-book", "credibility": "medium"}
 ], "updated": "2026-11-20"}
---
RSI compares the size of recent gains with recent losses on a 0-100 scale using Wilder's smoothing (alpha = 1/n). Wilder used 14 periods and 70/30 as overbought/oversold reference lines.

Practical notes:
* In strong uptrends RSI can stay above 70 for long periods; "overbought" is not a sell signal by itself. In uptrends, RSI dips toward 40-50 often mark pullback lows.
* Very short RSI (2-period) is popular in short-term mean-reversion systems: readings below 5-10 indicate a sharp multi-day selloff.
* Divergence (price makes a new high, RSI does not) is a warning of weakening momentum, not a timing tool.

**Failure modes:** news-driven selloffs where oversold keeps getting more oversold; regime changes (bear markets) where buying oversold readings catches falling knives.

---json
{"slug": "macd", "title": "MACD (Moving Average Convergence Divergence)", "category": "Technical analysis",
 "tags": ["macd", "momentum", "histogram", "signal line"],
 "sources": [
  {"title": "Technical Analysis: Power Tools for Active Investors", "authors": "Appel, G.", "year": 2005, "publisher": "FT Press", "type": "practitioner-book", "credibility": "medium"}
 ], "updated": "2026-11-20"}
---
MACD is the 12-period EMA minus the 26-period EMA; the signal line is a 9-period EMA of MACD; the histogram is MACD minus signal. It measures the *change* in trend momentum.

* Bullish cross: MACD crosses above its signal; more meaningful when it happens in the direction of the larger trend (e.g. price above its 200-day average).
* Histogram turning up from a negative extreme shows downside momentum fading, often before the cross.
* Zero-line: MACD above zero means the short EMA is above the long EMA (an uptrend by that definition).

**Failure modes:** lag in fast reversals; frequent crosses in choppy markets. Treat as confirming evidence, not a stand-alone system.

---json
{"slug": "bollinger-bands", "title": "Bollinger Bands and volatility contraction", "category": "Technical analysis",
 "tags": ["bollinger", "volatility", "squeeze", "bands", "pct b"],
 "sources": [
  {"title": "Bollinger on Bollinger Bands", "authors": "Bollinger, J.", "year": 2001, "publisher": "McGraw-Hill", "type": "practitioner-book", "credibility": "medium"}
 ], "updated": "2026-11-20"}
---
Bollinger Bands plot a 20-period SMA with bands two standard deviations above and below. %B locates price within the bands (0 = lower band, 1 = upper band); band width measures volatility.

* **Volatility cycles:** periods of unusually narrow bands (low width percentile) tend to be followed by expansion. The direction of the expansion is not predicted by the squeeze itself.
* Touching a band is not a signal by itself: in trends, price can "walk the band".
* Mean-reversion systems often buy closes below the lower band *only* when the longer-term trend is up.

---json
{"slug": "atr-stops", "title": "Average True Range (ATR) and volatility-based stops", "category": "Risk management",
 "tags": ["atr", "stops", "volatility", "wilder", "stop loss"],
 "sources": [
  {"title": "New Concepts in Technical Trading Systems", "authors": "Wilder, J. W.", "year": 1978, "publisher": "Trend Research", "type": "practitioner-book", "credibility": "medium"},
  {"title": "Investor Bulletin: Stop, Stop-Limit, and Trailing Stop Orders", "authors": "U.S. SEC Office of Investor Education and Advocacy", "year": 2021, "publisher": "Investor.gov", "url": "https://www.investor.gov/", "type": "regulator", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
True range is the greatest of: today's high minus low, |high - prior close|, |low - prior close| (so overnight gaps count). ATR is its Wilder-smoothed average, usually 14 periods.

Why ATR stops: a stop placed inside normal daily noise gets hit by randomness. Placing stops a multiple of ATR (commonly 1.5-3x) beyond entry, or just beyond a structural level (swing low) plus a small ATR buffer, ties the stop to how much the stock normally moves.

Consequences for sizing: a wider (ATR-based) stop means fewer shares for the same dollar risk. This is the link between volatility and position size.

**Important limitation (regulator guidance):** a stop order becomes a market order once triggered; in fast markets or across overnight gaps it can fill far below the stop price. A stop limits *expected* loss, not the *maximum* loss. MarketPilot's simulator models this by filling at the then-current bid, and the post-trade review flags losses beyond -1R as gap events.
