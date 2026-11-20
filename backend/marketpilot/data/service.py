"""Market data service: caching, polling, streaming, staleness and broadcast.

* `QuoteCache` holds the latest verified price per symbol with both the exchange
  timestamp and the local receive time, which is what staleness checks use.
* A REST snapshot poller always runs (robust baseline); a WebSocket stream is
  layered on top for lower latency when the provider supports it, with
  exponential-backoff reconnects.
* `Hub` fans out updates to connected dashboard WebSockets.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import Settings, get_settings
from . import calendar as cal
from .models import Bar, Snapshot, StreamEvent
from .providers.base import MarketDataProvider, NotSupported, NullProvider, ProviderError, ProviderNotConfigured
from .universe import INDEX_PROXIES, SECTOR_ETFS

log = logging.getLogger(__name__)


def build_provider(settings: Settings | None = None) -> MarketDataProvider:
    s = settings or get_settings()
    try:
        if s.market_data_provider == "alpaca":
            from .providers.alpaca import AlpacaProvider

            return AlpacaProvider(
                s.alpaca_api_key_id.get_secret_value() if s.alpaca_api_key_id else None,
                s.alpaca_api_secret_key.get_secret_value() if s.alpaca_api_secret_key else None,
                feed=s.alpaca_feed, data_url=s.alpaca_data_url, stream_url=s.alpaca_stream_url,
                reference_url=s.alpaca_reference_url,
            )
        if s.market_data_provider == "massive":
            from .providers.massive import MassiveProvider

            return MassiveProvider(s.massive_api_key.get_secret_value() if s.massive_api_key else None,
                                   s.massive_rest_url, s.massive_realtime)
    except ProviderNotConfigured as e:
        return NullProvider(str(e))
    return NullProvider("MARKET_DATA_PROVIDER=none")


@dataclass
class LiveQuote:
    symbol: str
    price: float
    exchange_ts: datetime
    received_at: datetime
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "price": self.price, "exchange_ts": self.exchange_ts.isoformat(),
                "received_at": self.received_at.isoformat(), "bid": self.bid, "ask": self.ask,
                "bid_size": self.bid_size, "ask_size": self.ask_size, "source": self.source}


class QuoteCache:
    def __init__(self) -> None:
        self._q: dict[str, LiveQuote] = {}

    def get(self, symbol: str) -> LiveQuote | None:
        return self._q.get(symbol.upper())

    def all(self) -> dict[str, LiveQuote]:
        return dict(self._q)

    def update_from_snapshot(self, s: Snapshot, now: datetime) -> LiveQuote | None:
        if s.last_price is None or s.last_price <= 0:
            return None
        ex_ts = max([t for t in (s.last_ts, s.quote_ts) if t is not None], default=now)
        prev = self._q.get(s.symbol)
        if prev and prev.exchange_ts > ex_ts:  # never overwrite newer stream data with an older snapshot
            prev.received_at = now
            return prev
        q = LiveQuote(s.symbol, float(s.last_price), ex_ts, now, s.bid, s.ask, s.bid_size, s.ask_size, s.feed)
        self._q[s.symbol] = q
        return q

    def update_from_event(self, ev: StreamEvent, now: datetime, source: str) -> LiveQuote | None:
        q = self._q.get(ev.symbol)
        if ev.kind == "trade":
            price = float(ev.data["price"])
            if price <= 0:
                return None
            if q is None:
                q = LiveQuote(ev.symbol, price, ev.ts, now, source=source)
                self._q[ev.symbol] = q
            elif ev.ts >= q.exchange_ts:
                q.price, q.exchange_ts = price, ev.ts
            q.received_at = now
            return q
        if ev.kind == "quote" and q is not None:
            bid, ask = ev.data.get("bid"), ev.data.get("ask")
            if bid and ask and ask >= bid:
                q.bid, q.ask = bid, ask
                q.bid_size, q.ask_size = ev.data.get("bid_size"), ev.data.get("ask_size")
                q.exchange_ts = max(q.exchange_ts, ev.ts)
                q.received_at = now
            return q
        return q

    def age_seconds(self, symbol: str, now: datetime | None = None) -> float | None:
        q = self.get(symbol)
        if q is None:
            return None
        now = now or datetime.now(timezone.utc)
        return (now - q.received_at).total_seconds()


class Hub:
    """In-process pub/sub for dashboard WebSockets."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.discard(q)

    def publish(self, msg: dict[str, Any]) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # slow client; drop rather than block the engine


@dataclass
class FeedHealth:
    last_success: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    consecutive_failures: int = 0
    stream_connected: bool = False
    stream_reconnects: int = 0
    stream_last_event: datetime | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at.isoformat() if self.last_error_at else None,
            "consecutive_failures": self.consecutive_failures,
            "stream_connected": self.stream_connected,
            "stream_reconnects": self.stream_reconnects,
            "stream_last_event": self.stream_last_event.isoformat() if self.stream_last_event else None,
        }


_BAR_TTL = {"1Min": 20, "5Min": 60, "15Min": 120, "1Hour": 300, "1Day": 600}
_LOOKBACK = {"1Min": timedelta(days=3), "5Min": timedelta(days=10), "15Min": timedelta(days=30),
             "1Hour": timedelta(days=120), "1Day": timedelta(days=550)}


class MarketDataService:
    def __init__(self, provider: MarketDataProvider, settings: Settings | None = None) -> None:
        self.provider = provider
        self.settings = settings or get_settings()
        self.quotes = QuoteCache()
        self.hub = Hub()
        self.health = FeedHealth()
        self._bar_cache: dict[tuple[str, str], tuple[float, list[Bar]]] = {}
        self._snap_cache: dict[str, Snapshot] = {}
        self._watched: set[str] = set(INDEX_PROXIES) | set(SECTOR_ETFS)
        self._stop = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._stream_symbols: frozenset[str] = frozenset()

    # ----------------------------------------------------------- configuration
    @property
    def configured(self) -> bool:
        return not isinstance(self.provider, NullProvider)

    def watch(self, symbols: Iterable[str]) -> None:
        self._watched |= {s.upper() for s in symbols}

    def set_watched(self, symbols: Iterable[str]) -> None:
        self._watched = {s.upper() for s in symbols} | set(INDEX_PROXIES) | set(SECTOR_ETFS)

    @property
    def watched(self) -> set[str]:
        return set(self._watched)

    # -------------------------------------------------------------- data access
    async def get_bars(self, symbol: str, timeframe: str, lookback: timedelta | None = None,
                       end: datetime | None = None, use_cache: bool = True) -> list[Bar]:
        res = await self.get_bars_multi([symbol], timeframe, lookback, end, use_cache)
        return res.get(symbol.upper(), [])

    async def get_bars_multi(self, symbols: list[str], timeframe: str, lookback: timedelta | None = None,
                             end: datetime | None = None, use_cache: bool = True) -> dict[str, list[Bar]]:
        syms = [s.upper() for s in symbols]
        lookback = lookback or _LOOKBACK.get(timeframe, timedelta(days=30))
        now_mono = time.monotonic()
        out: dict[str, list[Bar]] = {}
        missing = []
        for s in syms:
            key = (s, f"{timeframe}:{int(lookback.total_seconds())}")
            hit = self._bar_cache.get(key)
            if use_cache and end is None and hit and now_mono - hit[0] < _BAR_TTL.get(timeframe, 60):
                out[s] = hit[1]
            else:
                missing.append(s)
        if missing:
            start = (end or datetime.now(timezone.utc)) - lookback
            fetched = await self._call(self.provider.get_bars(missing, timeframe, start, end))
            for s in missing:
                bars = fetched.get(s, [])
                out[s] = bars
                if end is None:
                    self._bar_cache[(s, f"{timeframe}:{int(lookback.total_seconds())}")] = (now_mono, bars)
        return out

    async def get_snapshots(self, symbols: list[str]) -> dict[str, Snapshot]:
        snaps = await self._call(self.provider.get_snapshots([s.upper() for s in symbols]))
        now = datetime.now(timezone.utc)
        for s in snaps.values():
            self._snap_cache[s.symbol] = s
            q = self.quotes.update_from_snapshot(s, now)
            if q:
                self.hub.publish({"type": "quote", "data": q.to_dict()})
        return snaps

    def cached_snapshot(self, symbol: str) -> Snapshot | None:
        return self._snap_cache.get(symbol.upper())

    async def _call(self, coro: Any) -> Any:
        try:
            res = await coro
        except (ProviderNotConfigured, NotSupported):
            raise
        except ProviderError as e:
            self._record_error(str(e))
            raise
        except Exception as e:  # network or parsing failure
            self._record_error(f"{type(e).__name__}: {e}")
            raise ProviderError(str(e)) from e
        self.health.last_success = datetime.now(timezone.utc)
        self.health.consecutive_failures = 0
        return res

    def _record_error(self, msg: str) -> None:
        self.health.last_error = msg[:500]
        self.health.last_error_at = datetime.now(timezone.utc)
        self.health.consecutive_failures += 1
        log.warning("market data error: %s", msg[:300])

    # ---------------------------------------------------------------- staleness
    def is_feed_healthy(self, now: datetime | None = None) -> tuple[bool, str]:
        now = now or datetime.now(timezone.utc)
        if not self.configured:
            return False, "No market data provider configured"
        if self.health.last_success is None:
            return False, "No successful market data response yet"
        age = (now - self.health.last_success).total_seconds()
        limit = self.settings.stale_quote_seconds
        if age > limit:
            return False, f"Last successful market data response was {age:.0f}s ago (limit {limit}s)"
        return True, "ok"

    def quote_freshness(self, symbol: str, now: datetime | None = None) -> tuple[bool, str]:
        """Is the cached price for `symbol` fresh enough to act on right now?"""
        now = now or datetime.now(timezone.utc)
        q = self.quotes.get(symbol)
        if q is None:
            return False, f"No live price for {symbol}"
        recv_age = (now - q.received_at).total_seconds()
        if recv_age > self.settings.stale_quote_seconds:
            return False, f"{symbol} price last received {recv_age:.0f}s ago"
        if cal.is_regular_session(now):
            ex_age = (now - q.exchange_ts).total_seconds()
            # IEX-only feeds can legitimately have older last trades for thinner names;
            # allow a wider exchange-time window but still bound it.
            limit = self.settings.stale_quote_seconds * (5 if "iex" in q.source else 2)
            if ex_age > limit:
                return False, f"{symbol} last exchange print is {ex_age:.0f}s old (limit {limit:.0f}s)"
        return True, "ok"

    # ---------------------------------------------------------------- loops
    async def start(self) -> None:
        if not self.configured:
            log.warning("Market data provider not configured: %s", self.provider.quality().caveats)
            return
        self._stop = False
        self._tasks.append(asyncio.create_task(self._poll_loop(), name="md-poll"))
        if self.provider.stream_symbol_limit() > 0:
            self._tasks.append(asyncio.create_task(self._stream_supervisor(), name="md-stream"))

    async def stop(self) -> None:
        self._stop = True
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        await self.provider.aclose()

    async def _poll_loop(self) -> None:
        while not self._stop:
            now = datetime.now(timezone.utc)
            phase = cal.session_phase(now)
            interval = 15 if phase in ("opening", "intraday", "power_hour") else (60 if phase != "closed" else 300)
            try:
                await self.get_snapshots(sorted(self._watched))
                self.hub.publish({"type": "feed_health", "data": self.health.to_dict()})
            except (ProviderError, ProviderNotConfigured) as e:
                self.hub.publish({"type": "feed_health", "data": {**self.health.to_dict(), "error": str(e)[:200]}})
            except Exception:  # pragma: no cover - defensive
                log.exception("poll loop failure")
            await asyncio.sleep(interval)

    async def _stream_supervisor(self) -> None:
        backoff = 1.0
        source = f"{self.provider.name}:{self.provider.quality().feed}"
        while not self._stop:
            now = datetime.now(timezone.utc)
            if cal.session_phase(now) == "closed":
                self.health.stream_connected = False
                await asyncio.sleep(60)
                continue
            symbols = sorted(self._watched)
            self._stream_symbols = frozenset(symbols)

            async def on_event(ev: StreamEvent) -> None:
                t = datetime.now(timezone.utc)
                self.health.stream_last_event = t
                self.health.last_success = t
                q = self.quotes.update_from_event(ev, t, source)
                if q is not None and ev.kind in ("trade", "quote"):
                    self.hub.publish({"type": "quote", "data": q.to_dict()})
                elif ev.kind == "bar":
                    self.hub.publish({"type": "bar", "symbol": ev.symbol, "data": {"t": ev.ts.isoformat(), **ev.data}})

            def should_stop() -> bool:
                # Reconnect with a new subscription when the watched set changes.
                return self._stop or frozenset(self._watched) != self._stream_symbols

            try:
                self.health.stream_connected = True
                await self.provider.stream(symbols, on_event, should_stop)
                backoff = 1.0
            except NotSupported:
                self.health.stream_connected = False
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.health.stream_connected = False
                self.health.stream_reconnects += 1
                self._record_error(f"stream: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            finally:
                self.health.stream_connected = False
