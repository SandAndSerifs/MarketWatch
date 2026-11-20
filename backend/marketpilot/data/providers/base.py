"""Market data provider interface.

Switching providers means implementing this interface; nothing else in the
application talks to a vendor API directly.
"""
from __future__ import annotations

import abc
from collections.abc import Awaitable, Callable
from datetime import datetime

from ..models import Asset, Bar, DataQuality, Mover, NewsItem, Snapshot, StreamEvent


class ProviderError(RuntimeError):
    """The provider returned an error or invalid data."""


class ProviderNotConfigured(ProviderError):
    """No credentials configured. Callers must surface this; never substitute fake data."""


class NotSupported(ProviderError):
    """The provider (or the current plan) does not offer this capability."""


EventHandler = Callable[[StreamEvent], Awaitable[None]]


class MarketDataProvider(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def quality(self) -> DataQuality: ...

    @abc.abstractmethod
    async def get_bars(
        self,
        symbols: list[str],
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        adjustment: str = "split",
    ) -> dict[str, list[Bar]]:
        """Historical OHLCV bars, oldest first. `end` defaults to the latest the plan allows."""

    @abc.abstractmethod
    async def get_snapshots(self, symbols: list[str]) -> dict[str, Snapshot]: ...

    async def get_movers(self, top: int = 10) -> dict[str, list[Mover]]:
        raise NotSupported(f"{self.name} does not provide market movers")

    async def get_most_active(self, top: int = 20) -> list[Mover]:
        raise NotSupported(f"{self.name} does not provide most-active lists")

    async def get_news(self, symbols: list[str] | None = None, limit: int = 30) -> list[NewsItem]:
        raise NotSupported(f"{self.name} does not provide news")

    async def list_assets(self) -> list[Asset]:
        raise NotSupported(f"{self.name} does not provide an asset list")

    async def stream(self, symbols: list[str], on_event: EventHandler, stop: Callable[[], bool]) -> None:
        raise NotSupported(f"{self.name} does not support streaming")

    def stream_symbol_limit(self) -> int:
        return 0

    async def aclose(self) -> None:  # pragma: no cover - default no-op
        return None


class NullProvider(MarketDataProvider):
    """Used when no credentials are configured. Every data call fails loudly."""

    name = "none"

    def __init__(self, reason: str = "No market data provider is configured.") -> None:
        self.reason = reason

    def quality(self) -> DataQuality:
        return DataQuality("none", "none", False, 0, "No data source configured", (self.reason,))

    async def get_bars(self, symbols, timeframe, start, end=None, adjustment="split"):  # type: ignore[override]
        raise ProviderNotConfigured(self.reason)

    async def get_snapshots(self, symbols):  # type: ignore[override]
        raise ProviderNotConfigured(self.reason)

    async def get_movers(self, top=10):  # type: ignore[override]
        raise ProviderNotConfigured(self.reason)

    async def get_most_active(self, top=20):  # type: ignore[override]
        raise ProviderNotConfigured(self.reason)

    async def get_news(self, symbols=None, limit=30):  # type: ignore[override]
        raise ProviderNotConfigured(self.reason)

    async def list_assets(self):  # type: ignore[override]
        raise ProviderNotConfigured(self.reason)


def parse_ts(value: str | int | float | None) -> datetime | None:
    """Parse RFC3339 strings or epoch (s / ms / ns) into aware UTC datetimes."""
    from datetime import timezone

    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e17:
            v /= 1e9
        elif v > 1e14:
            v /= 1e6
        elif v > 1e11:
            v /= 1e3
        return datetime.fromtimestamp(v, tz=timezone.utc)
    s = str(value).replace("Z", "+00:00")
    # Python handles up to microseconds; Alpaca sends nanoseconds.
    if "." in s:
        head, rest = s.split(".", 1)
        frac, tz = rest, ""
        for sep in ("+", "-"):
            if sep in rest:
                frac, tz = rest.split(sep, 1)
                tz = sep + tz
                break
        s = f"{head}.{frac[:6]}{tz}"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_bar(b: Bar) -> bool:
    """Reject obviously corrupt bars rather than letting them reach indicators."""
    vals = (b.o, b.h, b.l, b.c)
    if any(v is None or v != v or v <= 0 for v in vals):  # None, NaN, non-positive
        return False
    if b.h < max(b.o, b.c, b.l) - 1e-9 or b.l > min(b.o, b.c, b.h) + 1e-9:
        return False
    return b.v is None or b.v >= 0
