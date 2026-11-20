---json
{"slug": "earnings-analysis", "title": "Earnings announcements: gaps, surprises and drift", "category": "Earnings analysis",
 "tags": ["earnings", "gap", "surprise", "post-earnings drift", "event risk"],
 "sources": [
  {"title": "An Empirical Evaluation of Accounting Income Numbers", "authors": "Ball, R., Brown, P.", "year": 1968, "publisher": "Journal of Accounting Research 6(2)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium?", "authors": "Bernard, V., Thomas, J.", "year": 1989, "publisher": "Journal of Accounting Research 27", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Earnings releases are scheduled, high-information events. Stocks frequently gap overnight on the report, moving through any stop level. Historically, prices continued to drift in the direction of large earnings surprises for weeks after the announcement, a long-documented anomaly that has weakened in recent decades.

Rules MarketPilot applies by default: no new swing entries within 3 sessions of a known earnings date; open swing positions are closed before the report (configurable); if no earnings date is on file (no earnings data provider configured), every checklist states that the date is unverified. Reports before the open are tagged "bmo", after the close "amc".

---json
{"slug": "macro-drivers", "title": "Macroeconomic releases that move the US market", "category": "Macroeconomic market drivers",
 "tags": ["fomc", "cpi", "jobs report", "nfp", "macro", "interest rates"],
 "sources": [
  {"title": "The Pre-FOMC Announcement Drift", "authors": "Lucca, D., Moench, E.", "year": 2015, "publisher": "Journal of Finance 70(1)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "How Much Do Investors Care About Macroeconomic Risk? Evidence from Scheduled Economic Announcements", "authors": "Savor, P., Wilson, M.", "year": 2013, "publisher": "Journal of Financial and Quantitative Analysis 48(2)", "type": "peer-reviewed", "credibility": "high"},
  {"title": "Meeting calendars and information", "authors": "Federal Reserve Board", "year": 2026, "publisher": "federalreserve.gov", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "type": "regulator", "credibility": "high"},
  {"title": "Release calendars", "authors": "U.S. Bureau of Labor Statistics", "year": 2026, "publisher": "bls.gov", "url": "https://www.bls.gov/schedule/", "type": "government", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
The scheduled releases with the largest market impact are typically: FOMC rate decisions (2:00 p.m. ET, followed by the press conference), the CPI inflation report (8:30 a.m. ET), and the Employment Situation / nonfarm payrolls report (8:30 a.m. ET, usually the first Friday of the month). Others include PCE inflation, GDP, retail sales and ISM surveys.

Research found that a large share of the equity premium has historically been earned on scheduled announcement days, and that US stocks tended to drift up ahead of FOMC announcements over the period studied. Volatility around releases is elevated: spreads widen and prices can jump.

MarketPilot blocks new entries from 60 minutes before to 30 minutes after high-importance releases, and flags any high-importance release within three days in the challenge step.

---json
{"slug": "fundamental-analysis", "title": "Fundamental analysis essentials for traders", "category": "Fundamental analysis",
 "tags": ["fundamentals", "valuation", "financial statements", "earnings quality"],
 "sources": [
  {"title": "Beginners' Guide to Financial Statements", "authors": "U.S. SEC", "year": 2007, "publisher": "SEC", "url": "https://www.sec.gov/about/reports-publications/beginners-guide-financial-statements", "type": "regulator", "credibility": "high"},
  {"title": "Investment Valuation (3rd ed.)", "authors": "Damodaran, A.", "year": 2012, "publisher": "Wiley", "type": "practitioner-book", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Short-term traders mainly need fundamentals to understand *event risk* and *why* a stock is moving: earnings and revenue growth versus expectations, guidance changes, margins, balance-sheet stress (leverage, refinancing), dilution (share offerings), and valuation extremes that make a stock sensitive to disappointment. Primary sources are company filings (10-K, 10-Q, 8-K) on SEC EDGAR. MarketPilot's v1 does not score fundamentals; it surfaces news headlines and earnings dates and treats unexplained large moves as a reason for caution.

---json
{"slug": "market-history", "title": "Historical market regimes: crashes, bear markets and rallies", "category": "Historical market behavior",
 "tags": ["history", "crash", "bear market", "rally", "regime", "drawdown"],
 "sources": [
  {"title": "Findings Regarding the Market Events of May 6, 2010", "authors": "Staffs of the CFTC and SEC", "year": 2010, "publisher": "SEC/CFTC", "type": "regulator", "credibility": "high"},
  {"title": "Manias, Panics, and Crashes (7th ed.)", "authors": "Aliber, R., Kindleberger, C.", "year": 2015, "publisher": "Palgrave Macmillan", "type": "practitioner-book", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Approximate peak-to-trough declines (closing levels; rounded):
* **Oct 19, 1987:** the Dow fell about 22.6% in one day.
* **2000-2002 dot-com bust:** Nasdaq Composite down roughly 78% from its March 2000 peak.
* **2007-2009 financial crisis:** S&P 500 down about 57% (Oct 2007 to Mar 2009).
* **May 6, 2010 Flash Crash:** a rapid intraday collapse and rebound within minutes.
* **Feb-Mar 2020 COVID crash:** S&P 500 down about 34% in roughly a month, followed by one of the fastest recoveries on record.
* **2022 bear market:** S&P 500 down about 25% (Jan to Oct 2022) amid rapid rate hikes.
* **Aug 2024 volatility spike** and the **April 2025 tariff selloff** (S&P 500 down close to 19% from its February 2025 peak) show that sharp shocks can occur inside broader bull markets.

Lessons: volatility clusters; correlations rise in selloffs (diversification across stocks helps less when it is needed most); long-only strategies suffer in bear markets, which is why MarketPilot uses a market-regime filter and flags risk-off conditions. The Strategy Lab's scenario replays let you test strategies on specific regimes where data is available (Alpaca SIP history starts in 2016).

---json
{"slug": "market-efficiency", "title": "Market efficiency and what an 'edge' means", "category": "Algorithmic trading",
 "tags": ["efficient markets", "edge", "expectancy", "alpha"],
 "sources": [
  {"title": "Efficient Capital Markets: A Review of Theory and Empirical Work", "authors": "Fama, E.", "year": 1970, "publisher": "Journal of Finance 25(2)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
In an efficient market, prices reflect available information and systematic excess returns after costs are hard to earn. Documented anomalies (momentum, short-term reversal, post-earnings drift) are small, noisy, and often weaker after publication. An edge is a positive expectancy after all costs that persists out of sample and is large relative to its estimation error.

Practical definition used by MarketPilot's Quantitative Analyst role: expectancy in R > 0, profit factor >= 1.2, on at least 30 out-of-sample trades, and confirmation in forward paper trading against the SPY benchmark over the same period. Anything less is labelled "unproven" or "weak", and no result is presented as a guarantee.

---json
{"slug": "portfolio-management", "title": "Portfolio construction for a small trading account", "category": "Portfolio management",
 "tags": ["diversification", "correlation", "sector exposure", "portfolio"],
 "sources": [
  {"title": "Portfolio Selection", "authors": "Markowitz, H.", "year": 1952, "publisher": "Journal of Finance 7(1)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Diversification reduces risk only to the extent holdings are not correlated. Five technology stocks behave more like one large position than five independent bets. MarketPilot limits concurrent positions (5), positions per sector (2), and position notional (5% of starting equity), and the challenge step flags correlated exposure. Most of a small account sits in cash by design; idle cash is not a failure.

---json
{"slug": "algorithmic-trading-basics", "title": "Algorithmic trading: rules, automation and controls", "category": "Algorithmic trading",
 "tags": ["algorithmic", "automation", "controls", "kill switch", "risk checks"],
 "sources": [
  {"title": "Risk Management Controls for Brokers or Dealers with Market Access (Rule 15c3-5)", "authors": "U.S. SEC", "year": 2010, "publisher": "SEC Release No. 34-63241", "type": "regulator", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Automated trading requires the same pre-trade controls that regulators require of brokers with market access: credit/capital thresholds, order-size limits, duplicate-order prevention, and the ability to halt immediately. MarketPilot mirrors these in deterministic code: the Risk Manager must approve every simulated order, client order ids prevent duplicates, data staleness pauses trading, a daily loss limit halts entries, and an emergency STOP halts everything. Language models may explain and critique, but they cannot place, size, or approve orders.

---json
{"slug": "intraday-trading-risks", "title": "Intraday trading risks", "category": "Trading psychology",
 "tags": ["day trading", "intraday", "pattern day trader", "risk"],
 "sources": [
  {"title": "Day Trading: Your Dollars at Risk", "authors": "U.S. SEC", "year": 2005, "publisher": "SEC", "type": "regulator", "credibility": "high"},
  {"title": "FINRA Rule 4210 (Margin Requirements), pattern day trader provisions", "authors": "FINRA", "year": 2024, "publisher": "finra.org", "type": "regulator", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Intraday trading concentrates costs (many round trips), noise (small moves relative to spread), and psychological pressure. In US margin accounts, FINRA's pattern-day-trader rules have imposed minimum equity requirements on frequent day traders; check current rules with your broker before trading real money. MarketPilot's intraday strategy is marked forward-test only and always flattens before the close.
