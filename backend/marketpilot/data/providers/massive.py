"""Massive (formerly Polygon.io, rebranded Oct 2025) Stocks REST/WebSocket provider.

Plans (verify at https://massive.com/pricing): Stocks Starter is 15-minute delayed;
real-time consolidated data requires a higher tier. Set MASSIVE_REALTIME=true only
if your plan includes real-time; otherwise data is labelled delayed and the
delayed WebSocket cluster is used.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import Asset, Bar, DataQuality, Mover, NewsItem, Snapshot, StreamEvent
from .base import EventHandler, MarketDataProvider, ProviderError, ProviderNotConfigured, parse_ts, validate_bar

_TF = {"1Min": (1, "minute"), "5Min": (5, "minute"), "15Min": (15, "minute"), "1Hour": (1, "hour"), "1Day": (1, "day")}


class MassiveProvider(MarketDataProvider):
    name = "massive"

    def __init__(self, api_key: str | None, rest_url: str = "https://api.massive.com", realtime: bool = False,
                 client: httpx.AsyncClient | None = None) -> None:
        if not api_key:
            raise ProviderNotConfigured("Massive key missing: set MASSIVE_API_KEY")
        self.rest_url = rest_url.rstrip("/")
        self.realtime = realtime
        self._key = api_key
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))

    def quality(self) -> DataQuality:
        if self.realtime:
            return DataQuality("massive", "massive-realtime", True, 0, "Consolidated tape (real-time plan)")
        return DataQuality("massive", "massive-delayed", False, 15, "Consolidated tape, 15-minute delayed plan",
                           ("Index levels shown via ETF proxies.",))

    def stream_symbol_limit(self) -> int:
        return 500

    async def _get(self, path_or_url: str, params: dict[str, Any] | None = None) -> Any:
        url = path_or_url if path_or_url.startswith("http") else f"{self.rest_url}{path_or_url}"
        for attempt in range(4):
            try:
                r = await self._client.get(url, params=params, headers=self._headers)
            except httpx.TransportError as e:
                if attempt == 3:
                    raise ProviderError(f"Massive network error: {e}") from e
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if r.status_code == 429 and attempt < 3:
                await asyncio.sleep(1.0 * 2**attempt)
                continue
            if r.status_code in (401, 403):
                raise ProviderError(f"Massive rejected key or plan ({r.status_code}): {r.text[:200]}")
            if r.status_code >= 400:
                raise ProviderError(f"Massive error {r.status_code}: {r.text[:300]}")
            return r.json()
        raise ProviderError("Massive: retries exhausted")

    async def get_bars(self, symbols, timeframe, start, end=None, adjustment="split"):  # type: ignore[override]
        if timeframe not in _TF:
            raise ProviderError(f"Unsupported timeframe {timeframe}")
        mult, span = _TF[timeframe]
        end = end or datetime.now(timezone.utc)
        out: dict[str, list[Bar]] = {}
        for sym in sorted({s.upper() for s in symbols}):
            rows: list[Bar] = []
            url = f"/v2/aggs/ticker/{sym}/range/{mult}/{span}/{int(start.timestamp()*1000)}/{int(end.timestamp()*1000)}"
            params: dict[str, Any] | None = {"adjusted": "true", "sort": "asc", "limit": 50000}
            while url:
                data = await self._get(url, params)
                for r in data.get("results") or []:
                    b = Bar(parse_ts(r["t"]), float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"]),
                            float(r.get("v", 0)), r.get("vw"), r.get("n"))
                    if validate_bar(b):
                        rows.append(b)
                url, params = data.get("next_url"), None
            out[sym] = rows
        return out

    async def get_snapshots(self, symbols):  # type: ignore[override]
        syms = sorted({s.upper() for s in symbols})
        out: dict[str, Snapshot] = {}
        for i in range(0, len(syms), 250):
            data = await self._get("/v2/snapshot/locale/us/markets/stocks/tickers", {"tickers": ",".join(syms[i:i+250])})
            for t in data.get("tickers") or []:
                out[t["ticker"]] = self._parse_snapshot(t)
        return out

    def _parse_snapshot(self, t: dict[str, Any]) -> Snapshot:
        day, prev, lt, lq = t.get("day") or {}, t.get("prevDay") or {}, t.get("lastTrade") or {}, t.get("lastQuote") or {}
        return Snapshot(
            symbol=t["ticker"], last_price=lt.get("p") or day.get("c"), last_ts=parse_ts(lt.get("t") or t.get("updated")),
            bid=lq.get("p") or None, ask=lq.get("P") or None, bid_size=lq.get("s"), ask_size=lq.get("S"),
            quote_ts=parse_ts(lq.get("t")), day_open=day.get("o"), day_high=day.get("h"), day_low=day.get("l"),
            day_volume=day.get("v"), day_vwap=day.get("vw"), prev_close=prev.get("c"),
            feed="massive:realtime" if self.realtime else "massive:delayed",
        )

    async def get_movers(self, top=10):  # type: ignore[override]
        res: dict[str, Any] = {}
        for direction in ("gainers", "losers"):
            data = await self._get(f"/v2/snapshot/locale/us/markets/stocks/{direction}")
            res[direction] = [
                Mover(t["ticker"], (t.get("lastTrade") or {}).get("p") or (t.get("day") or {}).get("c"),
                      t.get("todaysChange"), t.get("todaysChangePerc"), (t.get("day") or {}).get("v"))
                for t in (data.get("tickers") or [])[:top]
            ]
        res["as_of"] = datetime.now(timezone.utc).isoformat()
        return res

    async def get_news(self, symbols=None, limit=30):  # type: ignore[override]
        params: dict[str, Any] = {"limit": min(limit, 100), "order": "desc", "sort": "published_utc"}
        if symbols and len(symbols) == 1:
            params["ticker"] = symbols[0].upper()
        data = await self._get("/v2/reference/news", params)
        return [
            NewsItem(str(n.get("id")), n.get("title", ""), n.get("description", "") or "", n.get("article_url"),
                     (n.get("publisher") or {}).get("name", ""), tuple(n.get("tickers") or []),
                     parse_ts(n.get("published_utc")) or datetime.now(timezone.utc))
            for n in data.get("results") or []
        ]

    async def list_assets(self):  # type: ignore[override]
        out: list[Asset] = []
        url: str | None = "/v3/reference/tickers"
        params: dict[str, Any] | None = {"market": "stocks", "active": "true", "limit": 1000}
        pages = 0
        while url and pages < 15:
            data = await self._get(url, params)
            for t in data.get("results") or []:
                out.append(Asset(t["ticker"], t.get("name", ""), t.get("primary_exchange", ""), True, False,
                                 "etf" if t.get("type") == "ETF" else "stock"))
            url, params, pages = data.get("next_url"), None, pages + 1
        return out

    async def stream(self, symbols: list[str], on_event: EventHandler, stop: Callable[[], bool]) -> None:
        import websockets

        host = "wss://socket.massive.com/stocks" if self.realtime else "wss://delayed.massive.com/stocks"
        syms = sorted({s.upper() for s in symbols})[: self.stream_symbol_limit()]
        async with websockets.connect(host, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(json.dumps({"action": "auth", "params": self._key}))
            await ws.send(json.dumps({"action": "subscribe",
                                      "params": ",".join([f"T.{s}" for s in syms] + [f"Q.{s}" for s in syms] + [f"AM.{s}" for s in syms])}))
            while not stop():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5)
                except asyncio.TimeoutError:
                    continue
                for m in json.loads(raw):
                    ev = m.get("ev")
                    if ev == "status" and m.get("status") in ("auth_failed", "error"):
                        raise ProviderError(f"Massive stream: {m.get('message')}")
                    if ev == "T":
                        await on_event(StreamEvent("trade", m["sym"], parse_ts(m["t"]), {"price": m["p"], "size": m.get("s")}))
                    elif ev == "Q":
                        await on_event(StreamEvent("quote", m["sym"], parse_ts(m["t"]),
                                                   {"bid": m.get("bp"), "ask": m.get("ap"), "bid_size": m.get("bs"), "ask_size": m.get("as")}))
                    elif ev == "AM":
                        await on_event(StreamEvent("bar", m["sym"], parse_ts(m["s"]),
                                                   {"o": m["o"], "h": m["h"], "l": m["l"], "c": m["c"], "v": m.get("v")}))

    async def aclose(self) -> None:
        await self._client.aclose()

