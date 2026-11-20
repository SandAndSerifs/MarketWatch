"""Runtime container and session-aware scheduler.

The backend process owns all background work; the dashboard is only a client.
Closing the browser does not stop monitoring or paper trading.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from ..alerts.service import AlertService
from ..config import Settings, get_settings
from ..data import calendar as cal
from ..data.providers.base import ProviderError, ProviderNotConfigured
from ..data.service import MarketDataService, build_provider
from ..data.universe import DEFAULT_UNIVERSE
from ..db import AppSetting, Experiment, session_scope
from ..paper.engine import PaperEngine, exp_strategy
from .analysis import AnalysisService
from .scanner import Scanner

log = logging.getLogger(__name__)


def last_completed_session(now: datetime) -> str:
    d = cal.et_date(now)
    st = cal.session_times(d)
    if st and now >= st.close + timedelta(minutes=20):
        return d.isoformat()
    return cal.previous_trading_day(d).isoformat()


class Runtime:
    def __init__(self, settings: Settings | None = None, md: MarketDataService | None = None) -> None:
        self.settings = settings or get_settings()
        self.md = md or MarketDataService(build_provider(self.settings), self.settings)
        self.alerts = AlertService(self.md.hub)
        self.analysis = AnalysisService(self.md)
        self.engine = PaperEngine(self.md, self.analysis, self.alerts)
        self.scanner = Scanner(self.md, self.analysis, self.alerts)
        self._task: asyncio.Task[Any] | None = None
        self._stop = False
        self.job_errors: dict[str, str] = {}
        self._last: dict[str, datetime] = {}

    # ----------------------------------------------------------- job ledger
    def _job_done(self, key: str) -> str | None:
        with session_scope() as s:
            row = s.get(AppSetting, "jobs")
            return (row.value if row else {}).get(key)

    def _mark_job(self, key: str, value: str) -> None:
        with session_scope() as s:
            row = s.get(AppSetting, "jobs")
            val = dict(row.value) if row else {}
            val[key] = value
            s.merge(AppSetting(key="jobs", value=val))

    async def _run_job(self, key: str, value: str, coro_factory: Any) -> None:
        if self._job_done(key) == value:
            return
        try:
            await coro_factory()
            self._mark_job(key, value)
            self.job_errors.pop(key, None)
        except ProviderNotConfigured as e:
            self.job_errors[key] = str(e)
        except Exception as e:
            log.exception("job %s failed", key)
            self.job_errors[key] = f"{type(e).__name__}: {e}"[:300]

    def _every(self, key: str, seconds: int, now: datetime) -> bool:
        last = self._last.get(key)
        if last is None or (now - last).total_seconds() >= seconds:
            self._last[key] = now
            return True
        return False

    # ---------------------------------------------------------------- loop
    async def start(self) -> None:
        await self.md.start()
        if self.settings.run_engine:
            self._stop = False
            self._task = asyncio.create_task(self._loop(), name="scheduler")

    async def stop(self) -> None:
        self._stop = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        await self.md.stop()

    async def _loop(self) -> None:
        await asyncio.sleep(3)
        while not self._stop:
            try:
                await self.step(datetime.now(timezone.utc))
            except Exception:
                log.exception("scheduler step failed")
            await asyncio.sleep(20)

    async def step(self, now: datetime) -> None:
        if not self.md.configured:
            return
        et = cal.to_et(now)
        today = et.date().isoformat()
        trading_day = cal.is_trading_day(et.date())
        phase = cal.session_phase(now)
        hm = et.hour * 60 + et.minute

        if self.settings.finnhub_api_key and hm >= 6 * 60:
            await self._run_job("earnings_refresh", today, self._refresh_earnings)

        # Setups for the next session, built on the latest completed session's bars.
        completed = last_completed_session(now)
        with session_scope() as s:
            running = [(e.id, exp_strategy(e).timeframe) for e in s.execute(
                select(Experiment).where(Experiment.status == "running", Experiment.archived.is_(False))).scalars()]
        for exp_id, tf in running:
            if tf == "1Day" and phase != "opening":
                await self._run_job(f"setups:{exp_id}", completed, lambda i=exp_id: self.engine.generate_setups(i, now))

        if trading_day and hm >= 8 * 60 + 30:
            await self._run_job("premarket", today, self._premarket)
        if trading_day and hm >= 9 * 60 + 35:
            await self._run_job("manage_watch", today, lambda: self.scanner.manage_watch(now))

        if phase in ("opening", "intraday", "power_hour"):
            await self.engine.tick(now)
            if self._every("intraday_watch", 300, now):
                try:
                    await self.scanner.intraday_watch(now)
                except (ProviderError, ProviderNotConfigured) as e:
                    self.job_errors["intraday_watch"] = str(e)
                for exp_id, tf in running:
                    if tf != "1Day":
                        await self.engine.intraday_scan(exp_id, now)
            if self._every("equity_snapshot", 1800, now):
                self.engine.snapshot_equity(now)
        if trading_day and phase == "afterhours":
            await self._run_job("close_snapshot", today, self._close_snapshot)
            await self._run_job("daily_summary", today, lambda: self.scanner.daily_summary(now))
            await self._run_job("post_close_scan", today, lambda: self.scanner.full_scan(now))

    async def _premarket(self) -> None:
        await self.scanner.full_scan()
        await self.scanner.premarket_brief()

    async def _close_snapshot(self) -> None:
        try:
            await self.md.get_snapshots(["SPY"])
        except ProviderError:
            pass
        self.engine.snapshot_equity()

    async def _refresh_earnings(self) -> None:
        from ..events.calendar import refresh_earnings_finnhub

        syms = set(DEFAULT_UNIVERSE) | set(self.scanner.universe())
        key = self.settings.finnhub_api_key.get_secret_value()  # type: ignore[union-attr]
        with session_scope() as s:
            await refresh_earnings_finnhub(s, key, sorted(syms))

    def status(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        healthy, reason = self.md.is_feed_healthy(now)
        return {
            "market": cal.market_status(now),
            "data": {"configured": self.md.configured, "quality": self.md.provider.quality().to_dict(),
                     "healthy": healthy, "reason": reason, "health": self.md.health.to_dict(),
                     "watched_symbols": len(self.md.watched)},
            "engine": {**self.engine.status(), "scheduler_running": bool(self._task and not self._task.done()),
                       "run_engine": self.settings.run_engine},
            "scanner": {"last_scan": self.scanner.last_scan},
            "job_errors": self.job_errors,
            "ai": {"provider": self.settings.ai_provider, "configured": bool(self.settings.anthropic_api_key),
                   "model": self.settings.ai_model},
            "paper_only": True,
        }
