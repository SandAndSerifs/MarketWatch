"""Glue between market data, technicals, strategies and the checklist."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..analysis.technicals import market_regime, technical_profile
from ..data import calendar as cal
from ..data.models import Bar, NewsItem
from ..data.providers.base import NotSupported, ProviderError
from ..data.service import MarketDataService
from ..data.universe import BENCHMARK, SECTOR_ETFS
from ..decision.checklist import build_decision, quant_view
from ..events.calendar import earnings_coverage_ok, upcoming_events
from ..risk.manager import MarketState, PortfolioState, RiskConfig, RiskManager
from ..strategies.base import SetupProposal, Strategy, StrategyContext

log = logging.getLogger(__name__)


def completed_daily_bars(bars: list[Bar], now: datetime) -> list[Bar]:
    """Drop the current session's still-forming daily bar (prevents acting on partial data)."""
    if not bars:
        return bars
    today = cal.et_date(now)
    last_day = cal.et_date(bars[-1].t + timedelta(hours=6))  # daily bar stamps are 00:00 ET (04:00/05:00 UTC)
    st = cal.session_times(today)
    if last_day == today and st is not None and now < st.close + timedelta(minutes=20):
        return bars[:-1]
    return bars


class AnalysisService:
    def __init__(self, md: MarketDataService) -> None:
        self.md = md
        self._regime: tuple[float, dict[str, Any]] | None = None
        self._news_cache: dict[str, tuple[float, list[NewsItem]]] = {}

    async def regime(self, force: bool = False) -> dict[str, Any]:
        if not force and self._regime and time.monotonic() - self._regime[0] < 600:
            return self._regime[1]
        now = datetime.now(timezone.utc)
        bars = await self.md.get_bars_multi([BENCHMARK, *SECTOR_ETFS], "1Day", timedelta(days=550))
        spy = completed_daily_bars(bars.get(BENCHMARK, []), now)
        sectors = {k: completed_daily_bars(v, now) for k, v in bars.items() if k != BENCHMARK}
        reg = market_regime(spy, sectors)
        reg["sector_names"] = SECTOR_ETFS
        self._regime = (time.monotonic(), reg)
        return reg

    async def daily(self, symbol: str, now: datetime | None = None) -> list[Bar]:
        now = now or datetime.now(timezone.utc)
        return completed_daily_bars(await self.md.get_bars(symbol, "1Day", timedelta(days=550)), now)

    async def daily_multi(self, symbols: list[str], now: datetime | None = None) -> dict[str, list[Bar]]:
        now = now or datetime.now(timezone.utc)
        res = await self.md.get_bars_multi(symbols, "1Day", timedelta(days=550))
        return {k: completed_daily_bars(v, now) for k, v in res.items()}

    async def news(self, symbol: str) -> list[NewsItem]:
        hit = self._news_cache.get(symbol)
        if hit and time.monotonic() - hit[0] < 900:
            return hit[1]
        try:
            items = await self.md.provider.get_news([symbol], 10)
        except (NotSupported, ProviderError) as e:
            log.info("news unavailable for %s: %s", symbol, e)
            items = []
        self._news_cache[symbol] = (time.monotonic(), items)
        return items

    def context(self, s: Session, symbol: str, bars: list[Bar], regime: dict[str, Any], now: datetime,
                intraday: list[Bar] | None = None) -> StrategyContext:
        tech = technical_profile(bars)
        events = upcoming_events(s, [symbol], cal.et_date(now) - timedelta(days=1), 21)
        return StrategyContext(symbol=symbol, as_of=now, bars=bars, tech=tech, regime=regime,
                               snapshot=self.md.cached_snapshot(symbol), intraday=intraday, events=events)

    def market_state(self, s: Session, ctx: StrategyContext, now: datetime, kill_switch: bool) -> MarketState:
        q = self.md.quotes.get(ctx.symbol)
        fresh, reason = self.md.quote_freshness(ctx.symbol, now)
        return MarketState(now=now, price=q.price if q else None, bid=q.bid if q else None, ask=q.ask if q else None,
                           data_fresh=fresh, data_reason=reason, avg_dollar_volume=ctx.tech.get("avg_dollar_volume20"),
                           events=ctx.events, kill_switch=kill_switch, earnings_checked=earnings_coverage_ok(s))

    async def evaluate(self, s: Session, strategy: Strategy, ctx: StrategyContext, risk_cfg: RiskConfig,
                       portfolio: PortfolioState, now: datetime, kill_switch: bool = False,
                       with_news: bool = True) -> tuple[SetupProposal | None, dict[str, Any] | None]:
        proposal = strategy.evaluate(ctx)
        if proposal is None:
            return None, None
        market = self.market_state(s, ctx, now, kill_switch)
        verdict = RiskManager(risk_cfg).evaluate_entry(ctx.symbol, proposal.entry_price, proposal.stop, proposal.target,
                                                       proposal.holding, portfolio, market)
        news = await self.news(ctx.symbol) if with_news else []
        quant = quant_view(s, strategy.key, strategy.version)
        q = self.md.quotes.get(ctx.symbol)
        record = build_decision(ctx, strategy, proposal, risk_cfg, verdict, self.md.provider.quality(), quant, news,
                                portfolio.open_symbols, q.price if q else ctx.tech.get("close"),
                                q.exchange_ts if q else None)
        return proposal, record

    async def gather_limited(self, coros: list[Any], limit: int = 8) -> list[Any]:
        sem = asyncio.Semaphore(limit)

        async def run(c: Any) -> Any:
            async with sem:
                try:
                    return await c
                except Exception as e:  # keep scanning other symbols
                    log.warning("analysis task failed: %s", e)
                    return e

        return await asyncio.gather(*(run(c) for c in coros))


def reference_portfolio() -> PortfolioState:
    """Illustrative $10k account used to size scanner signals (Mode 1 alerts)."""
    return PortfolioState(starting_capital=10_000, cash=10_000, equity=10_000, day_start_equity=10_000, open_symbols=[])
