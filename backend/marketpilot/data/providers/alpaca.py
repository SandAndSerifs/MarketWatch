"""Alpaca Market Data API v2 provider (read-only).

Plans (verify current terms at https://alpaca.markets/data):
  * Basic (free): real-time IEX feed (IEX exchange only, ~2-3% of US volume),
    consolidated SIP history older than 15 minutes, 200 REST calls/min,
    WebSocket limited to a small number of symbols.
  * Algo Trader Plus ($99/mo at time of writing): real-time SIP (all US exchanges).

Design choices:
  * Live snapshots/streams use the configured feed (default IEX) and are labelled.
  * Historical bars use feed=sip with `end` clamped to now-16min on non-SIP plans,
    so indicators see consolidated volume instead of IEX-only volume.
  * Only data endpoints and *reference* endpoints (assets, clock, calendar on the
    paper host) are called. There is deliberately no order-submission code here.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time as _time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..models import Asset, Bar, DataQuality, Mover, NewsItem, Snapshot, StreamEvent
from .base import (
    EventHandler,
    MarketDataProvider,
    ProviderError,
    ProviderNotConfigured,
    parse_ts,
    validate_bar,
)

log = logging.getLogger(__name__)

_TF_MAP = {"1Min": "1Min", "5Min": "5Min", "15Min": "15Min", "1Hour": "1Hour", "1Day": "1Day"}


class AlpacaProvider(MarketDataProvider):
    name = "alpaca"

    def __init__(
        self,
        key_id: str | None,
        secret: str | None,
        feed: str = "iex",
        data_url: str = "https://data.alpaca.markets",
        stream_url: str = "wss://stream.data.alpaca.markets",
        reference_url: str = "https://paper-api.alpaca.markets",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not key_id or not secret:
            raise ProviderNotConfigured("Alpaca keys missing: set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY")
        if "paper-api" not in reference_url and "localhost" not in reference_url:
            # Defence in depth: the reference host must never be the live trading host.
            raise ProviderError("ALPACA_REFERENCE_URL must point at the paper host (paper-api.alpaca.markets)")
        self.feed = feed
        self.data_url = data_url.rstrip("/")
        self.stream_url = stream_url.rstrip("/")
        self.reference_url = reference_url.rstrip("/")
        self._headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}
        self._key, self._secret = key_id, secret
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))
        self._assets_cache: tuple[float, list[Asset]] | None = None

    # ------------------------------------------------------------------ meta
    def quality(self) -> DataQuality:
        if self.feed == "sip":
            return DataQuality("alpaca", "sip", True, 0, "Consolidated tape, all US exchanges (Algo Trader Plus)")
        if self.feed == "delayed_sip":
            return DataQuality("alpaca", "delayed_sip", False, 15, "Consolidated tape, 15-minute delayed")
        return DataQuality(
            "alpaca",
            "iex",
            True,
            0,
            "Real-time trades/quotes from the IEX exchange only",
            (
                "IEX is a single venue (~2-3% of US volume): live volume and quote sizes are partial.",
                "Intraday volume-based signals use IEX volume; daily history uses consolidated SIP data older than 15 minutes.",
                "Index levels are shown via ETF proxies (SPY, QQQ, DIA), not the indices themselves.",
            ),
        )

    def stream_symbol_limit(self) -> int:
        return 1000 if self.feed == "sip" else 30

    # --------------------------------------------------------------- helpers
    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(4):
            try:
                r = await self._client.get(url, params=params, headers=self._headers)
            except httpx.TransportError as e:
                if attempt == 3:
                    raise ProviderError(f"Alpaca network error: {e}") from e
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if r.status_code == 429 and attempt < 3:
                await asyncio.sleep(float(r.headers.get("Retry-After", 1.0 * 2**attempt)))
                continue
            if r.status_code in (401, 403):
                raise ProviderError(f"Alpaca rejected credentials or plan for {url} ({r.status_code}): {r.text[:200]}")
            if r.status_code >= 400:
                raise ProviderError(f"Alpaca error {r.status_code} for {url}: {r.text[:300]}")
            return r.json()
        raise ProviderError("Alpaca: retries exhausted")

    def _hist_feed_and_end(self, end: datetime | None) -> tuple[str, datetime]:
        now = datetime.now(timezone.utc)
        if self.feed == "sip":
            return "sip", end or now
        # Free plan: SIP history allowed only if older than 15 minutes.
        cap = now - timedelta(minutes=16)
        return "sip", min(end, cap) if end else cap

    # ------------------------------------------------------------------ bars
    async def get_bars(self, symbols, timeframe, start, end=None, adjustment="split"):  # type: ignore[override]
        if timeframe not in _TF_MAP:
            raise ProviderError(f"Unsupported timeframe {timeframe}")
        syms = sorted({s.upper() for s in symbols})
        feed, end_ts = self._hist_feed_and_end(end)
        out: dict[str, list[Bar]] = {s: [] for s in syms}
        # Chunk symbols to keep URLs short.
        for i in range(0, len(syms), 100):
            chunk = syms[i : i + 100]
            params: dict[str, Any] = {
                "symbols": ",".join(chunk),
                "timeframe": _TF_MAP[timeframe],
                "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "end": end_ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "limit": 10000,
                "adjustment": adjustment,
                "feed": feed,
                "sort": "asc",
            }
            while True:
                data = await self._get(f"{self.data_url}/v2/stocks/bars", params)
                for sym, rows in (data.get("bars") or {}).items():
                    for r in rows:
                        b = Bar(parse_ts(r["t"]), float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"]),
                                float(r.get("v", 0)), r.get("vw"), r.get("n"))
                        if validate_bar(b):
                            out.setdefault(sym, []).append(b)
                token = data.get("next_page_token")
                if not token:
                    break
                params["page_token"] = token
        for s in out:
            out[s].sort(key=lambda b: b.t)
        return out

    # ------------------------------------------------------------- snapshots
    async def get_snapshots(self, symbols):  # type: ignore[override]
        syms = sorted({s.upper() for s in symbols})
        feed = "sip" if self.feed == "sip" else ("delayed_sip" if self.feed == "delayed_sip" else "iex")
        out: dict[str, Snapshot] = {}
        for i in range(0, len(syms), 200):
            chunk = syms[i : i + 200]
            data = await self._get(f"{self.data_url}/v2/stocks/snapshots", {"symbols": ",".join(chunk), "feed": feed})
            for sym, snap in (data or {}).items():
                if not isinstance(snap, dict):
                    continue
                out[sym] = self._parse_snapshot(sym, snap, feed)
        return out

    @staticmethod
    def _parse_snapshot(sym: str, s: dict[str, Any], feed: str) -> Snapshot:
        lt = s.get("latestTrade") or {}
        lq = s.get("latestQuote") or {}
        db = s.get("dailyBar") or {}
        pdb = s.get("prevDailyBar") or {}
        return Snapshot(
            symbol=sym,
            last_price=lt.get("p"),
            last_ts=parse_ts(lt.get("t")),
            bid=lq.get("bp") or None,
            ask=lq.get("ap") or None,
            bid_size=lq.get("bs"),
            ask_size=lq.get("as"),
            quote_ts=parse_ts(lq.get("t")),
            day_open=db.get("o"),
            day_high=db.get("h"),
            day_low=db.get("l"),
            day_volume=db.get("v"),
            day_vwap=db.get("vw"),
            prev_close=pdb.get("c"),
            feed=f"alpaca:{feed}",
        )

    # ---------------------------------------------------------- screener/news
    async def get_movers(self, top=10):  # type: ignore[override]
        data = await self._get(f"{self.data_url}/v1beta1/screener/stocks/movers", {"top": min(max(top, 1), 50)})

        def conv(rows: list[dict[str, Any]]) -> list[Mover]:
            return [Mover(r["symbol"], r.get("price"), r.get("change"), r.get("percent_change")) for r in rows or []]

        return {"gainers": conv(data.get("gainers")), "losers": conv(data.get("losers")),
                "as_of": data.get("last_updated")}  # type: ignore[dict-item]

    async def get_most_active(self, top=20):  # type: ignore[override]
        data = await self._get(f"{self.data_url}/v1beta1/screener/stocks/most-actives",
                               {"by": "volume", "top": min(max(top, 1), 100)})
        return [Mover(r["symbol"], None, None, None, r.get("volume")) for r in data.get("most_actives") or []]

    async def get_news(self, symbols=None, limit=30):  # type: ignore[override]
        params: dict[str, Any] = {"limit": min(limit, 50), "sort": "desc"}
        if symbols:
            params["symbols"] = ",".join(sorted({s.upper() for s in symbols}))
        data = await self._get(f"{self.data_url}/v1beta1/news", params)
        out = []
        for n in data.get("news") or []:
            out.append(NewsItem(str(n.get("id")), n.get("headline", ""), n.get("summary", "") or "", n.get("url"),
                                n.get("source", "") or n.get("author", ""), tuple(n.get("symbols") or []),
                                parse_ts(n.get("created_at")) or datetime.now(timezone.utc)))
        return out

    async def list_assets(self):  # type: ignore[override]
        if self._assets_cache and _time.time() - self._assets_cache[0] < 86_400:
            return self._assets_cache[1]
        data = await self._get(f"{self.reference_url}/v2/assets", {"status": "active", "asset_class": "us_equity"})
        assets = [
            Asset(a["symbol"], a.get("name") or "", a.get("exchange") or "", bool(a.get("tradable")),
                  bool(a.get("fractionable")), "stock")
            for a in data
            if a.get("tradable") and a.get("exchange") not in ("OTC",)
        ]
        self._assets_cache = (_time.time(), assets)
        return assets

    async def get_calendar(self, start: str, end: str) -> list[dict[str, Any]]:
        return await self._get(f"{self.reference_url}/v2/calendar", {"start": start, "end": end})

    # --------------------------------------------------------------- stream
    async def stream(self, symbols: list[str], on_event: EventHandler, stop: Callable[[], bool]) -> None:
        """One connection lifetime. The caller (StreamSupervisor) handles reconnects."""
        import websockets

        feed = self.feed if self.feed in ("iex", "sip", "delayed_sip") else "iex"
        url = f"{self.stream_url}/v2/{feed}"
        syms = sorted({s.upper() for s in symbols})[: self.stream_symbol_limit()]
        async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**22) as ws:
            await ws.send(json.dumps({"action": "auth", "key": self._key, "secret": self._secret}))
            authed = False
            while not authed:
                msgs = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                for m in msgs:
                    if m.get("T") == "error":
                        raise ProviderError(f"Alpaca stream error {m.get('code')}: {m.get('msg')}")
                    if m.get("T") == "success" and m.get("msg") == "authenticated":
                        authed = True
            await ws.send(json.dumps({"action": "subscribe", "trades": syms, "quotes": syms, "bars": syms}))
            while not stop():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5)
                except asyncio.TimeoutError:
                    continue
                for m in json.loads(raw):
                    ev = self._parse_stream_msg(m)
                    if ev is not None:
                        await on_event(ev)

    @staticmethod
    def _parse_stream_msg(m: dict[str, Any]) -> StreamEvent | None:
        t = m.get("T")
        if t == "t":
            return StreamEvent("trade", m["S"], parse_ts(m["t"]), {"price": m["p"], "size": m.get("s")})
        if t == "q":
            return StreamEvent("quote", m["S"], parse_ts(m["t"]),
                               {"bid": m.get("bp"), "ask": m.get("ap"), "bid_size": m.get("bs"), "ask_size": m.get("as")})
        if t == "b":
            return StreamEvent("bar", m["S"], parse_ts(m["t"]),
                               {"o": m["o"], "h": m["h"], "l": m["l"], "c": m["c"], "v": m.get("v")})
        if t == "error":
            raise ProviderError(f"Alpaca stream error {m.get('code')}: {m.get('msg')}")
        return None

    async def aclose(self) -> None:
        await self._client.aclose()
