"""Backtest orchestration: fetch genuine history, run off the event loop, persist results."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from ..data.calendar import ET
from ..data.models import Bar
from ..data.service import MarketDataService
from ..data.universe import BENCHMARK, SECTOR_ETFS
from ..db import BacktestRun, StrategyVersion, session_scope
from ..strategies.library import create_strategy
from .engine import optimize_on_train, run_backtest

log = logging.getLogger(__name__)

# Historical regimes for replay. Alpaca SIP history begins in 2016; earlier windows need a
# provider/plan with deeper history (e.g. Massive) and are marked accordingly.
SCENARIOS: dict[str, dict[str, str]] = {
    "gfc_2008": {"name": "2008 financial crisis (bear market / crash)", "start": "2007-10-09", "end": "2009-03-09",
                 "type": "bear market", "note": "Requires data before 2016 (not available on Alpaca)."},
    "bull_2017": {"name": "2017 low-volatility bull market", "start": "2017-01-03", "end": "2017-12-29", "type": "bull market"},
    "choppy_2018": {"name": "2018 volatility spike and Q4 selloff (sideways/round trip)", "start": "2018-01-26", "end": "2019-01-31",
                    "type": "sideways / failed breakouts"},
    "covid_crash_2020": {"name": "Feb-Mar 2020 COVID crash", "start": "2020-02-19", "end": "2020-04-30",
                         "type": "high-volatility selloff / crash"},
    "covid_rebound_2020": {"name": "2020 V-shaped rebound", "start": "2020-03-23", "end": "2020-08-31", "type": "strong rally / trend reversal"},
    "bear_2022": {"name": "2022 rate-hike bear market", "start": "2022-01-03", "end": "2022-10-14", "type": "bear market"},
    "recovery_2023": {"name": "Late 2022-2023 recovery", "start": "2022-10-13", "end": "2023-07-31", "type": "bull market"},
    "vol_shock_2024": {"name": "Aug 2024 volatility shock", "start": "2024-07-10", "end": "2024-09-30", "type": "high-volatility selloff"},
    "tariff_selloff_2025": {"name": "Feb-May 2025 tariff selloff and rebound", "start": "2025-02-19", "end": "2025-05-30",
                            "type": "high-volatility selloff / reversal"},
}

WARMUP_DAYS = 420


async def fetch_history(md: MarketDataService, symbols: list[str], start: date, end: date) -> dict[str, list[Bar]]:
    s_dt = datetime.combine(start - timedelta(days=WARMUP_DAYS), time(0), tzinfo=ET).astimezone(timezone.utc)
    e_dt = datetime.combine(end, time(23, 59), tzinfo=ET).astimezone(timezone.utc)
    syms = sorted({x.upper() for x in symbols} | {BENCHMARK} | set(SECTOR_ETFS))
    return await md._call(md.provider.get_bars(syms, "1Day", s_dt, min(e_dt, datetime.now(timezone.utc)), adjustment="all"))


def _register_version(strategy_key: str, params: dict[str, Any]) -> str:
    strat = create_strategy(strategy_key, params)
    with session_scope() as s:
        from sqlalchemy import select

        row = s.execute(select(StrategyVersion).where(StrategyVersion.strategy_key == strategy_key,
                                                      StrategyVersion.version == strat.version)).scalar_one_or_none()
        if row is None:
            s.add(StrategyVersion(strategy_key=strategy_key, version=strat.version, params=strat.params,
                                  status="testing" if "+" in strat.version else "approved",
                                  parent_version=type(strat).version if "+" in strat.version else None,
                                  change_reason="Registered automatically on first use", created_by="system"))
    return strat.version


async def start_backtest(md: MarketDataService, strategy_key: str, params: dict[str, Any], universe: list[str],
                         start: date, end: date, risk: dict[str, Any] | None = None, execution: dict[str, Any] | None = None,
                         capital: float = 10_000.0, scenario: str | None = None) -> int:
    version = _register_version(strategy_key, params)
    with session_scope() as s:
        run = BacktestRun(strategy_key=strategy_key, strategy_version=version, params=params, universe=universe,
                          start=start.isoformat(), end=end.isoformat(), scenario=scenario,
                          data_source=f"{md.provider.name}:sip-history" if md.provider.name == "alpaca" else md.provider.name,
                          assumptions={}, segments={}, trades=[], equity_curve=[], status="running")
        s.add(run)
        s.flush()
        run_id = run.id
    asyncio.create_task(_execute(md, run_id, strategy_key, params, universe, start, end, risk, execution, capital))
    return run_id


async def _execute(md: MarketDataService, run_id: int, strategy_key: str, params: dict[str, Any], universe: list[str],
                   start: date, end: date, risk: dict[str, Any] | None, execution: dict[str, Any] | None, capital: float) -> None:
    try:
        bars = await fetch_history(md, universe, start, end)
        spy = bars.get(BENCHMARK, [])
        if not spy or spy[0].t.date() > start:
            raise ValueError(f"Insufficient benchmark history: data starts {spy[0].t.date() if spy else 'n/a'}, requested {start}")
        sectors = {k: v for k, v in bars.items() if k in SECTOR_ETFS}
        uni = {k: v for k, v in bars.items() if k in {u.upper() for u in universe}}
        out = await asyncio.to_thread(run_backtest, strategy_key, params, uni, spy, sectors, start, end, risk, execution, capital)
        res = out["result"]
        missing = sorted({u.upper() for u in universe} - {k for k, v in uni.items() if len(v) >= 60})
        if missing:
            res.warnings.append(f"No/insufficient history for: {', '.join(missing[:20])}")
        with session_scope() as s:
            run = s.get(BacktestRun, run_id)
            assert run is not None
            run.segments, run.trades = out["segments"], res.trades
            run.equity_curve = [{"date": d, "equity": v} for d, v in res.equity]
            run.assumptions, run.warnings, run.status = out["assumptions"], res.warnings, "complete"
    except Exception as e:
        log.exception("backtest %s failed", run_id)
        with session_scope() as s:
            run = s.get(BacktestRun, run_id)
            if run:
                run.status, run.error = "failed", f"{type(e).__name__}: {e}"[:1000]


async def run_optimization(md: MarketDataService, strategy_key: str, grid: dict[str, list[Any]], universe: list[str],
                           start: date, end: date, risk: dict[str, Any] | None = None) -> dict[str, Any]:
    bars = await fetch_history(md, universe, start, end)
    spy = bars.get(BENCHMARK, [])
    sectors = {k: v for k, v in bars.items() if k in SECTOR_ETFS}
    uni = {k: v for k, v in bars.items() if k in {u.upper() for u in universe}}
    return await asyncio.to_thread(optimize_on_train, strategy_key, grid, uni, spy, sectors, start, end, risk)


def backtest_to_dict(b: BacktestRun, full: bool = False) -> dict[str, Any]:
    d = {"id": b.id, "created_at": b.created_at.isoformat(), "strategy_key": b.strategy_key,
         "strategy_version": b.strategy_version, "params": b.params, "start": b.start, "end": b.end,
         "scenario": b.scenario, "data_source": b.data_source, "status": b.status, "error": b.error,
         "segments": b.segments, "warnings": b.warnings, "universe_size": len(b.universe or [])}
    if full:
        d.update({"universe": b.universe, "assumptions": b.assumptions, "trades": b.trades, "equity_curve": b.equity_curve})
    return d
