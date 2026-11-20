---json
{"slug": "support-resistance", "title": "Support, resistance and market structure", "category": "Support and resistance",
 "tags": ["support", "resistance", "swing high", "swing low", "market structure", "price action"],
 "sources": [
  {"title": "Foundations of Technical Analysis", "authors": "Lo, A., Mamaysky, H., Wang, J.", "year": 2000, "publisher": "Journal of Finance 55(4)", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Support is a price area where buying has repeatedly absorbed selling (prior swing lows); resistance is where selling has capped rallies (prior swing highs). Levels matter more when touched several times and when they coincide with round numbers or moving averages. Market structure describes the sequence of swings: higher highs and higher lows define an uptrend; a lower low after a series of higher lows is an early warning of trend change.

MarketPilot detects levels from *confirmed* swing pivots (a pivot needs three bars on each side, so the newest bars cannot create a level) and clusters nearby pivots. The challenge step objects when resistance sits less than 1R above entry.

---json
{"slug": "candlestick-patterns", "title": "Candlestick basics (and their limits)", "category": "Price action",
 "tags": ["candlestick", "doji", "hammer", "engulfing", "price action"],
 "sources": [
  {"title": "Foundations of Technical Analysis", "authors": "Lo, Mamaysky, Wang", "year": 2000, "publisher": "Journal of Finance", "type": "peer-reviewed", "credibility": "high"},
  {"title": "What Do We Know About the Profitability of Technical Analysis?", "authors": "Park, Irwin", "year": 2007, "publisher": "Journal of Economic Surveys", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
A candlestick shows open, high, low and close. The body is open-to-close; wicks show the extremes. Common descriptions:
* **Doji:** open and close nearly equal - indecision.
* **Hammer:** small body near the high with a long lower wick after a decline - sellers pushed price down but buyers recovered it.
* **Bullish engulfing:** a large up candle whose body engulfs the prior down candle's body.
* **Shooting star:** long upper wick after an advance - rejection of higher prices.

Single-candle patterns are weak evidence on their own; context (trend, location at support/resistance, volume) matters more than the pattern. MarketPilot uses candles as context in explanations, not as stand-alone triggers.

---json
{"slug": "gaps", "title": "Gaps and overnight risk", "category": "Price action",
 "tags": ["gap", "overnight", "pre-market", "gap fill"],
 "sources": [
  {"title": "Investor Bulletin: Stop, Stop-Limit, and Trailing Stop Orders", "authors": "U.S. SEC", "year": 2021, "publisher": "Investor.gov", "type": "regulator", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
A gap occurs when the open is above the prior high or below the prior low, usually because of overnight news. Stops do not protect against gaps: a stop below a gap-down open executes at the open or worse. Holding overnight, especially through earnings or macro events, accepts this risk. Pre-market prices are thin and can be misleading; MarketPilot only enters during the regular session and waits five minutes after the open.

---json
{"slug": "volume-analysis", "title": "Volume analysis", "category": "Volume and liquidity",
 "tags": ["volume", "relative volume", "confirmation", "distribution", "accumulation"],
 "sources": [
  {"title": "Illiquidity and Stock Returns", "authors": "Amihud, Y.", "year": 2002, "publisher": "Journal of Financial Markets", "type": "peer-reviewed", "credibility": "high"}
 ], "updated": "2026-11-20"}
---
Volume shows participation. Practitioner heuristics: moves on rising volume are more credible than on falling volume; breakouts on volume well above average are more likely to hold; heavy volume on down days in an uptrend can signal distribution. Always compare volume with the same feed and time of day: on IEX-only data, absolute volume is a small fraction of the market total.
