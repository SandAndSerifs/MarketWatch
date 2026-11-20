---json
{"slug": "position-sizing-fixed-fractional", "title": "Position sizing: fixed-fractional risk", "category": "Position sizing",
 "tags": ["position sizing", "risk per trade", "fixed fractional", "R multiple"],
 "sources": [
  {"title": "Portfolio Selection", "authors": "Markowitz, H.", "year": 1952, "publisher": "Journal of Finance 7(1)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Day Trading: Your Dollars at Risk", "authors": "U.S. Securities and Exchange Commission", "year": 2005, "publisher": "SEC / Investor.gov", "url": "https://www.sec.gov/about/reports-publications/investorpubsdaytipshtm", "type": "regulator", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Fixed-fractional sizing risks a constant small fraction of equity on each trade:

`shares = (equity x risk%) / (entry - stop)`

Example: $10,000 equity, 0.5% risk = $50; entry $100, stop $96 -> $4 risk per share -> 12 shares ($1,200 notional).

MarketPilot then applies caps: notional no more than 5% of starting equity, no more than available cash (no margin), at most 5 concurrent positions. With a $10,000 account the 5% notional cap ($500) usually binds before the risk budget, so real risk per trade is often well under 0.5%. That is intentional: capital preservation first.

The "R multiple" expresses outcomes in units of initial risk: +2R means the trade made twice what it risked. Thinking in R separates the quality of a strategy from position size.

---json
{"slug": "kelly-criterion", "title": "Kelly criterion and why traders use fractions of it", "category": "Position sizing",
 "tags": ["kelly", "optimal f", "growth", "overbetting"],
 "sources": [
  {"title": "A New Interpretation of Information Rate", "authors": "Kelly, J. L.", "year": 1956, "publisher": "Bell System Technical Journal 35(4)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "The Kelly Criterion in Blackjack, Sports Betting and the Stock Market", "authors": "Thorp, E. O.", "year": 2006, "publisher": "Handbook of Asset and Liability Management (Elsevier)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
The Kelly fraction maximises long-run geometric growth when the true win probability and payoff are *known*: f* = p - (1-p)/b, where b is the win/loss ratio. In trading the inputs are estimates with large error; betting full Kelly on an overestimated edge leads to severe drawdowns. Practitioners who use Kelly typically bet a fraction (e.g. a quarter or half) or use it only as an upper bound. MarketPilot does not use Kelly sizing; fixed small fractional risk is more robust when the edge is unproven.

---json
{"slug": "drawdowns-and-recovery", "title": "Drawdowns and the mathematics of recovery", "category": "Risk management",
 "tags": ["drawdown", "capital preservation", "recovery", "daily loss limit"],
 "sources": [
  {"title": "Performance Measurement in a Downside Risk Framework", "authors": "Sortino, F., Price, L.", "year": 1994, "publisher": "Journal of Investing 3(3)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
A loss of L% requires a gain of L/(1-L) to recover: -10% needs +11.1%, -25% needs +33%, -50% needs +100%. Losses compound against you faster than gains help, which is why capital preservation dominates.

Controls used in MarketPilot: small per-trade risk; a daily loss limit (2% of starting equity) that halts new entries for the session; a maximum number of positions; sector concentration limits; automatic pause on stale data; and an emergency stop. Maximum drawdown is reported for every experiment and backtest, alongside the benchmark's drawdown over the same period.

---json
{"slug": "risk-adjusted-returns", "title": "Risk-adjusted performance: Sharpe, Sortino, Calmar", "category": "Statistical strategy evaluation",
 "tags": ["sharpe", "sortino", "calmar", "risk adjusted", "volatility"],
 "sources": [
  {"title": "Mutual Fund Performance", "authors": "Sharpe, W. F.", "year": 1966, "publisher": "Journal of Business 39(1)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Performance Measurement in a Downside Risk Framework", "authors": "Sortino, F., Price, L.", "year": 1994, "publisher": "Journal of Investing", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Raw return rewards risk-taking. Risk-adjusted measures divide return by a measure of risk:
* **Sharpe ratio:** mean excess return / standard deviation of returns (annualised with sqrt(252) for daily data).
* **Sortino ratio:** uses only downside deviation, so upside volatility is not penalised.
* **Calmar ratio:** annualised return / maximum drawdown.

All three are noisy over short samples. A Sharpe estimate from a few months of daily data has a wide error band. The Strategy Competition ranks by Sharpe scaled by sample size and penalised for drawdowns, so a strategy cannot top the leaderboard merely by taking more risk or by getting lucky on three trades.

---json
{"slug": "trading-psychology", "title": "Trading psychology: documented behavioural biases", "category": "Trading psychology",
 "tags": ["psychology", "disposition effect", "loss aversion", "overconfidence", "bias"],
 "sources": [
  {"title": "Prospect Theory: An Analysis of Decision under Risk", "authors": "Kahneman, D., Tversky, A.", "year": 1979, "publisher": "Econometrica 47(2)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "The Disposition to Sell Winners Too Early and Ride Losers Too Long", "authors": "Shefrin, H., Statman, M.", "year": 1985, "publisher": "Journal of Finance 40(3)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Are Investors Reluctant to Realize Their Losses?", "authors": "Odean, T.", "year": 1998, "publisher": "Journal of Finance 53(5)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Trading Is Hazardous to Your Wealth", "authors": "Barber, B., Odean, T.", "year": 2000, "publisher": "Journal of Finance 55(2)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
* **Loss aversion:** losses feel roughly twice as painful as equal gains feel good, which makes people avoid realising losses.
* **Disposition effect:** investors sell winners too early and hold losers too long; brokerage-account studies confirm it.
* **Overconfidence and overtrading:** households that traded the most earned the lowest net returns, largely due to costs.
* **Recency and narrative bias:** recent wins or a good story inflate confidence in the next trade.

Countermeasures built into MarketPilot: predefined stops and targets recorded before entry; a written thesis and explicit falsifiers; a forced counter-argument step; stops that can only tighten; no silent strategy changes; post-trade reviews that judge process separately from outcome.

---json
{"slug": "common-trading-mistakes", "title": "Common trading mistakes and failure patterns", "category": "Common mistakes",
 "tags": ["mistakes", "overtrading", "revenge trading", "averaging down", "curve fitting"],
 "sources": [
  {"title": "Day Trading: Your Dollars at Risk", "authors": "U.S. SEC", "year": 2005, "publisher": "SEC", "type": "regulator", "credibility": "high"},
  {"title": "The Cross-Section of Speculator Skill: Evidence from Day Trading", "authors": "Barber, B., Lee, Y.-T., Liu, Y.-J., Odean, T.", "year": 2014, "publisher": "Journal of Financial Markets 18", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
1. **No predefined exit.** Entering without a stop and target turns a trade into a hope.
2. **Moving stops further away** to avoid taking a loss.
3. **Averaging down** on losing positions without a plan.
4. **Oversizing** after a winning streak; revenge trading after losses.
5. **Ignoring costs:** spreads, slippage and fees turn small edges negative, especially for frequent trading.
6. **Holding through known events** (earnings) without accepting the gap risk.
7. **Curve fitting:** optimising a backtest until it looks perfect.
8. **Judging a strategy by a handful of trades.**

Evidence from large datasets of day traders shows the large majority lose money after costs and only a small minority show persistent skill. MarketPilot defaults to paper trading and long-only, cash-only constraints for this reason.
