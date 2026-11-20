---json
{"slug": "backtest-overfitting", "title": "Backtest overfitting and data snooping", "category": "Statistical strategy evaluation",
 "tags": ["overfitting", "data snooping", "multiple testing", "deflated sharpe", "out of sample"],
 "sources": [
  {"title": "Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance", "authors": "Bailey, D., Borwein, J., Lopez de Prado, M., Zhu, Q.", "year": 2014, "publisher": "Notices of the American Mathematical Society 61(5)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "The Deflated Sharpe Ratio", "authors": "Bailey, D., Lopez de Prado, M.", "year": 2014, "publisher": "Journal of Portfolio Management 40(5)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "A Reality Check for Data Snooping", "authors": "White, H.", "year": 2000, "publisher": "Econometrica 68(5)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "...and the Cross-Section of Expected Returns", "authors": "Harvey, C., Liu, Y., Zhu, H.", "year": 2016, "publisher": "Review of Financial Studies 29(1)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
If you try enough parameter combinations, some will look excellent on historical data by chance alone. The more configurations tested, the higher the in-sample Sharpe ratio you should *expect* from pure noise, and the less that in-sample performance predicts out-of-sample results. Researchers have argued that, because so many factors have been tested, new findings should clear much higher statistical hurdles than conventional significance levels.

Defences used in the MarketPilot Strategy Lab:
* Chronological split into **train / validation / out-of-sample test** segments. Parameters may only be chosen using train and validation; the test segment is reported separately and should be looked at once.
* Record the **number of configurations tried** with each run.
* Prefer simple rules with few parameters and conventional values.
* Require a minimum number of out-of-sample trades before calling evidence "supported".
* Confirm with forward paper trading, which is kept separate from backtests.

---json
{"slug": "lookahead-survivorship", "title": "Look-ahead bias and survivorship bias", "category": "Statistical strategy evaluation",
 "tags": ["look-ahead", "survivorship", "bias", "backtest"],
 "sources": [
  {"title": "Pseudo-Mathematics and Financial Charlatanism", "authors": "Bailey et al.", "year": 2014, "publisher": "Notices of the AMS", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
**Look-ahead bias:** using information that was not available at decision time, e.g. deciding on today's close and also filling at today's close, using indicators computed on the full series, or using today's still-forming bar. MarketPilot's indicators are causal (tested), decisions use only completed bars, and backtest entries fill on later bars.

**Survivorship bias:** testing on today's index members excludes companies that were delisted or went bankrupt, inflating historical returns. A static list of current large caps has this bias; MarketPilot warns about it on every such backtest. Remedying it requires point-in-time constituent data (a paid dataset).

---json
{"slug": "transaction-costs", "title": "Transaction costs: spread, slippage, fees, market impact", "category": "Volume and liquidity",
 "tags": ["costs", "spread", "slippage", "fees", "market impact", "sec fee", "taf"],
 "sources": [
  {"title": "Optimal Execution of Portfolio Transactions", "authors": "Almgren, R., Chriss, N.", "year": 2001, "publisher": "Journal of Risk 3(2)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Section 31 Transaction Fee Rate Advisory for Fiscal Year 2026", "authors": "U.S. SEC", "year": 2026, "publisher": "sec.gov", "url": "https://www.sec.gov/rules-regulations/fee-rate-advisories", "type": "regulator", "credibility": "high"},
  {"title": "FINRA Trading Activity Fee schedule", "authors": "FINRA", "year": 2026, "publisher": "finra.org", "url": "https://www.finra.org/rules-guidance/rulebooks/corporate-organization/section-1-member-regulatory-fees", "type": "regulator", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Costs a retail trader faces even with "zero commission": the bid-ask spread (buy at the ask, sell at the bid), slippage (price moves between decision and fill), market impact (larger orders move price), and regulatory fees on sales (SEC Section 31 fee, FINRA Trading Activity Fee). For small orders in liquid large caps, spread and slippage dominate.

MarketPilot's simulator charges the quoted spread (or an assumed half-spread when no two-sided quote exists), plus configurable slippage, plus sell-side SEC and FINRA fees at current rates, and models latency between decision and fill.

---json
{"slug": "liquidity", "title": "Liquidity and why it matters for risk", "category": "Volume and liquidity",
 "tags": ["liquidity", "volume", "dollar volume", "spread", "relative volume"],
 "sources": [
  {"title": "Illiquidity and Stock Returns: Cross-Section and Time-Series Effects", "authors": "Amihud, Y.", "year": 2002, "publisher": "Journal of Financial Markets 5(1)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Continuous Auctions and Insider Trading", "authors": "Kyle, A.", "year": 1985, "publisher": "Econometrica 53(6)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Liquidity is the ability to trade size quickly at a price close to the last trade. Illiquid stocks have wider spreads, larger price impact, more gap risk, and stops that fill further away. Average daily dollar volume (price x volume) is a simple filter; MarketPilot requires at least $20M by default and rejects quotes with spreads wider than 25 basis points.

Relative volume (today's volume vs its recent average) indicates unusual participation: breakouts on high relative volume are more credible, but unusual volume also accompanies news shocks. Note that intraday relative volume needs a time-of-day adjustment because volume is concentrated near the open and close.

---json
{"slug": "market-structure-data-feeds", "title": "US market structure: exchanges, the SIP, IEX-only feeds", "category": "Institutional trading concepts",
 "tags": ["sip", "iex", "nbbo", "market data", "reg nms", "exchanges"],
 "sources": [
  {"title": "Regulation NMS", "authors": "U.S. SEC", "year": 2005, "publisher": "SEC Release No. 34-51808", "type": "regulator", "credibility": "high"},
  {"title": "About Market Data API", "authors": "Alpaca Securities", "year": 2026, "publisher": "docs.alpaca.markets", "url": "https://docs.alpaca.markets/docs/about-market-data-api", "type": "vendor-documentation", "credibility": "medium"}
 ], "updated": "2026-11-20"}
---
US equities trade on more than a dozen exchanges plus off-exchange venues. The Securities Information Processors (SIPs) consolidate quotes and trades into the national best bid and offer (NBBO) and the consolidated tape. A single-exchange feed such as IEX shows only that venue's quotes and trades, a few percent of total volume.

Consequences for MarketPilot users on Alpaca's free plan: last-trade prices are generally close to the consolidated price for liquid stocks, but volume, quote sizes and sometimes the bid/ask are partial. The app labels every price with its feed, uses consolidated (SIP) history older than 15 minutes for daily indicators, and flags IEX-only data in each checklist.

---json
{"slug": "circuit-breakers-luld", "title": "Market-wide circuit breakers and LULD halts", "category": "Institutional trading concepts",
 "tags": ["circuit breaker", "halt", "luld", "volatility"],
 "sources": [
  {"title": "Investor Bulletin: Measures to Address Market Volatility", "authors": "U.S. SEC", "year": 2012, "publisher": "SEC / Investor.gov", "type": "regulator", "credibility": "high"},
  {"title": "Findings Regarding the Market Events of May 6, 2010", "authors": "Staffs of the CFTC and SEC", "year": 2010, "publisher": "SEC/CFTC", "type": "regulator", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Market-wide circuit breakers halt trading across US exchanges when the S&P 500 falls 7% (Level 1) or 13% (Level 2) from the prior close (15-minute halts if before 3:25 p.m. ET) and close the market for the day at 20% (Level 3). Individual stocks are subject to Limit Up-Limit Down (LULD) bands that pause trading when prices move outside a percentage band. These mechanisms were strengthened after the May 6, 2010 "Flash Crash". During halts, stop orders cannot execute; when trading resumes, fills can be far from stop levels.
