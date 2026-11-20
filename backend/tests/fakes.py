"""TEST-ONLY synthetic market data. Never imported by application code.

Everything here is clearly labelled as a fixture; it exists so the engine,
risk manager and backtester can be exercised deterministically.
"""
from __future__ import annotations

import math
import random
from datetime import date, datetime, time, timedelta, timezone

from marketpilot.data import calendar as cal
from marketpilot.data.models import Bar, DataQuality, Snapshot
from marketpilot.data.providers.base import MarketDataProvider


def trading_days(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if cal.is_trading_day(d):
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def bar_ts(d: date) -> datetime:
    return datetime.combine(d, time(0), tzinfo=cal.ET).astimezone(timezone.utc)


def make_bars(days: list[date], closes: list[float], vol: float = 1_000_000, spread: float = 0.01) -> list[Bar]:
    bars = []
    prev = closes[0]
    for d, c in zip(days, closes):
        o = prev
        h = max(o, c) * (1 + spread)
        l = min(o, c) * (1 - spread)  # noqa: E741
        bars.append(Bar(bar_ts(d), round(o, 4), round(h, 4), round(l, 4), round(c, 4), vol))
        prev = c
    return bars


def uptrend_then_pullback(days: list[date], start: float = 50.0, drift: float = 0.004, pullback: int = 3,
                          pull_pct: float = 0.012) -> list[float]:
    closes = [start]
    for _ in range(len(days) - 1 - pullback):
        closes.append(closes[-1] * (1 + drift + 0.002 * math.sin(len(closes))))
    for _ in range(pullback):
        closes.append(closes[-1] * (1 - pull_pct))
    return closes


def random_walk(days: list[date], seed: int = 1, start: float = 100.0, mu: float = 0.0004, sigma: float = 0.015) -> list[float]:
    rng = random.Random(seed)
    closes = [start]
    for _ in range(len(days) - 1):
        closes.append(closes[-1] * math.exp(rng.gauss(mu, sigma)))
    return closes


class FakeProvider(MarketDataProvider):
    """TEST FIXTURE provider serving pre-built synthetic bars and snapshots."""

    name = "test-fixture"

    def __init__(self, bars: dict[str, list[Bar]] | None = None, snapshots: dict[str, Snapshot] | None = None) -> None:
        self.bars = bars or {}
        self.snapshots = snapshots or {}

    def quality(self) -> DataQuality:
        return DataQuality("test-fixture", "sip", True, 0, "TEST FIXTURE - synthetic data, not market data")

    async def get_bars(self, symbols, timeframe, start, end=None, adjustment="split"):  # type: ignore[override]
        out = {}
        for s in symbols:
            out[s.upper()] = [b for b in self.bars.get(s.upper(), []) if b.t >= start and (end is None or b.t <= end)]
        return out

    async def get_snapshots(self, symbols):  # type: ignore[override]
        return {s: self.snapshots[s] for s in symbols if s in self.snapshots}
