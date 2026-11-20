"""Symbol universes.

NOTE ON SURVIVORSHIP BIAS: these lists reflect *today's* liquid names. Using them
for backtests over past years silently excludes companies that were delisted,
acquired or fell out of favour, which flatters historical results. The backtester
records this caveat on every run that uses a static universe.
"""
from __future__ import annotations

INDEX_PROXIES = {
    "SPY": "S&P 500 (SPY ETF proxy)",
    "QQQ": "Nasdaq-100 (QQQ ETF proxy)",
    "DIA": "Dow Jones Industrial Avg (DIA ETF proxy)",
    "IWM": "Russell 2000 (IWM ETF proxy)",
}

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}

# Mapping used for sector-concentration risk checks and sector-strength context.
SYMBOL_SECTOR = {
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "AVGO": "XLK", "AMD": "XLK", "ORCL": "XLK", "CRM": "XLK",
    "ADBE": "XLK", "CSCO": "XLK", "QCOM": "XLK", "INTC": "XLK", "TXN": "XLK", "MU": "XLK", "AMAT": "XLK",
    "NOW": "XLK", "IBM": "XLK",
    "AMZN": "XLY", "TSLA": "XLY", "HD": "XLY", "MCD": "XLY", "NKE": "XLY", "LOW": "XLY", "SBUX": "XLY", "BKNG": "XLY",
    "GOOGL": "XLC", "META": "XLC", "NFLX": "XLC", "DIS": "XLC", "TMUS": "XLC", "VZ": "XLC", "T": "XLC",
    "JPM": "XLF", "BAC": "XLF", "WFC": "XLF", "GS": "XLF", "MS": "XLF", "V": "XLF", "MA": "XLF", "BRK.B": "XLF",
    "AXP": "XLF", "C": "XLF",
    "UNH": "XLV", "JNJ": "XLV", "LLY": "XLV", "PFE": "XLV", "MRK": "XLV", "ABBV": "XLV", "TMO": "XLV", "ABT": "XLV",
    "XOM": "XLE", "CVX": "XLE", "COP": "XLE", "SLB": "XLE",
    "CAT": "XLI", "GE": "XLI", "HON": "XLI", "UPS": "XLI", "BA": "XLI", "RTX": "XLI", "DE": "XLI",
    "PG": "XLP", "KO": "XLP", "PEP": "XLP", "COST": "XLP", "WMT": "XLP",
    "LIN": "XLB", "NEE": "XLU", "PLD": "XLRE",
}

ETF_SYMBOLS = set(INDEX_PROXIES) | set(SECTOR_ETFS) | {"TLT", "GLD", "HYG", "IEF"}

# Default scanner / paper-trading universe: highly liquid large caps and ETFs,
# where IEX quotes are representative and spreads are tight.
DEFAULT_UNIVERSE = sorted(
    {s for s in SYMBOL_SECTOR if s != "BRK.B"} | set(INDEX_PROXIES) | set(SECTOR_ETFS)
)

BENCHMARK = "SPY"


def sector_of(symbol: str) -> str | None:
    if symbol in SECTOR_ETFS:
        return symbol
    return SYMBOL_SECTOR.get(symbol.upper())
