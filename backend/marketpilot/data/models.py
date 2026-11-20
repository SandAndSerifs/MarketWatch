"""Provider-neutral market data types.

Every object that carries a price also carries *where it came from* and *how
fresh it is*, so the UI and the risk manager can always tell real-time,
exchange-limited (IEX-only) and delayed data apart.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

TIMEFRAMES = ("1Min", "5Min", "15Min", "1Hour", "1Day")


@dataclass(frozen=True)
class DataQuality:
    provider: str
    feed: str  # e.g. "iex", "sip", "delayed_sip", "massive-delayed"
    realtime: bool
    delay_minutes: int
    coverage: str  # human readable description of what the feed includes
    caveats: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["caveats"] = list(self.caveats)
        d["label"] = self.label
        return d

    @property
    def label(self) -> str:
        if self.realtime and self.feed == "iex":
            return "Real-time (IEX only)"
        if self.realtime:
            return "Real-time (consolidated)"
        return f"Delayed {self.delay_minutes} min"


@dataclass(frozen=True)
class Bar:
    t: datetime  # bar open time, UTC
    o: float
    h: float
    l: float  # noqa: E741
    c: float
    v: float
    vwap: float | None = None
    n: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"t": self.t.isoformat(), "o": self.o, "h": self.h, "l": self.l, "c": self.c, "v": self.v,
                "vwap": self.vwap, "n": self.n}


@dataclass
class Snapshot:
    symbol: str
    last_price: float | None
    last_ts: datetime | None
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    quote_ts: datetime | None = None
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    day_volume: float | None = None
    day_vwap: float | None = None
    prev_close: float | None = None
    feed: str = ""

    @property
    def change(self) -> float | None:
        if self.last_price is None or not self.prev_close:
            return None
        return self.last_price - self.prev_close

    @property
    def change_pct(self) -> float | None:
        if self.change is None or not self.prev_close:
            return None
        return self.change / self.prev_close * 100.0

    @property
    def spread_bps(self) -> float | None:
        if not self.bid or not self.ask or self.ask < self.bid:
            return None
        mid = (self.bid + self.ask) / 2
        return (self.ask - self.bid) / mid * 10_000

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "last_price": self.last_price,
            "last_ts": self.last_ts.isoformat() if self.last_ts else None,
            "bid": self.bid,
            "ask": self.ask,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "quote_ts": self.quote_ts.isoformat() if self.quote_ts else None,
            "day_open": self.day_open,
            "day_high": self.day_high,
            "day_low": self.day_low,
            "day_volume": self.day_volume,
            "day_vwap": self.day_vwap,
            "prev_close": self.prev_close,
            "change": self.change,
            "change_pct": self.change_pct,
            "spread_bps": self.spread_bps,
            "feed": self.feed,
        }


@dataclass(frozen=True)
class NewsItem:
    id: str
    headline: str
    summary: str
    url: str | None
    source: str
    symbols: tuple[str, ...]
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "headline": self.headline, "summary": self.summary, "url": self.url,
                "source": self.source, "symbols": list(self.symbols), "created_at": self.created_at.isoformat()}


@dataclass(frozen=True)
class Mover:
    symbol: str
    price: float | None
    change: float | None
    change_pct: float | None
    volume: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Asset:
    symbol: str
    name: str
    exchange: str
    tradable: bool = True
    fractionable: bool = False
    asset_type: str = "stock"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StreamEvent:
    kind: str  # trade | quote | bar | status
    symbol: str
    ts: datetime
    data: dict[str, Any] = field(default_factory=dict)
