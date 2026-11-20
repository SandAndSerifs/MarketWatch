"""TEST-ONLY: boot the real API on synthetic, clearly-labelled fixture data for UI/E2E tests.

    python -m tests.e2e_fixture_server   (from backend/, with the venv active)

Every price served comes from tests/fakes.py and is labelled "TEST FIXTURE - synthetic
data". This is never used by the application itself.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import date, datetime, timedelta, timezone

DB = os.path.join(tempfile.gettempdir(), "marketpilot_e2e.db")
if os.path.exists(DB):
    os.remove(DB)
os.environ.update({"DATABASE_URL": f"sqlite:///{DB}", "RUN_ENGINE": "false", "MARKET_DATA_PROVIDER": "none",
                   "AI_PROVIDER": "none", "MARKETPILOT_ENV": "test"})

import uvicorn  # noqa: E402

from marketpilot.app import create_app, seed  # noqa: E402
from marketpilot.config import get_settings  # noqa: E402
from marketpilot.data.models import Mover, NewsItem, Snapshot  # noqa: E402
from marketpilot.data.service import MarketDataService  # noqa: E402
from marketpilot.data.universe import DEFAULT_UNIVERSE, SECTOR_ETFS  # noqa: E402
from marketpilot.db import Experiment, PendingSetup, init_engine, session_scope  # noqa: E402
from marketpilot.services.runtime import Runtime  # noqa: E402

from tests.fakes import FakeProvider, make_bars, random_walk, trading_days, uptrend_then_pullback  # noqa: E402

NOW = datetime(2026, 11, 18, 15, 30, tzinfo=timezone.utc)


class FixtureProvider(FakeProvider):
    async def get_movers(self, top=10):  # type: ignore[override]
        rows = sorted((s for s in self.snapshots.values() if s.change_pct is not None), key=lambda s: -(s.change_pct or 0))
        conv = [Mover(s.symbol, s.last_price, s.change, s.change_pct) for s in rows]
        return {"gainers": conv[:top], "losers": list(reversed(conv[-top:])), "as_of": NOW.isoformat()}

    async def get_most_active(self, top=20):  # type: ignore[override]
        return [Mover(s.symbol, None, None, None, s.day_volume) for s in list(self.snapshots.values())[:top]]

    async def get_news(self, symbols=None, limit=30):  # type: ignore[override]
        return [NewsItem("fx1", "TEST FIXTURE headline: synthetic news item for UI testing", "Synthetic.", None,
                         "test-fixture", ("AAA",), NOW)]

    async def list_assets(self):  # type: ignore[override]
        from marketpilot.data.models import Asset

        return [Asset(s, f"{s} (fixture)", "TEST") for s in self.bars]


def build() -> tuple[FixtureProvider, dict]:
    days = trading_days(date(2026, 11, 17), 900)
    bars = {"AAA": make_bars(days, uptrend_then_pullback(days, start=20, drift=0.0025))}
    for i, s in enumerate(DEFAULT_UNIVERSE[:30]):
        bars[s] = make_bars(days, random_walk(days, seed=i + 3, start=50 + i * 7, mu=0.0005))
    bars["SPY"] = make_bars(days, uptrend_then_pullback(days, start=300, drift=0.0008, pullback=0))
    for k in SECTOR_ETFS:
        bars[k] = make_bars(days, random_walk(days, seed=hash(k) % 97, start=80, mu=0.0004, sigma=0.01))
    snaps = {}
    for s, b in bars.items():
        last, prev = b[-1], b[-2]
        snaps[s] = Snapshot(s, last.c * 1.004, NOW, last.c * 1.0035, last.c * 1.0045, 10, 10, NOW, last.o, last.h, last.l,
                            last.v * 0.6, None, prev.c, "test-fixture")
    return FixtureProvider(bars, snaps), bars


async def prepare(rt: Runtime, provider: FixtureProvider) -> None:
    rt.engine.real_time = False
    await rt.md.get_snapshots(list(provider.snapshots))
    await rt.scanner.full_scan(NOW - timedelta(hours=16))
    with session_scope() as s:
        exp = Experiment(name="Fixture experiment (synthetic)", strategy_key="trend_pullback", strategy_version="1.0.0",
                         strategy_params={}, risk_config={"risk": {}, "execution": {}}, universe=["AAA"] + DEFAULT_UNIVERSE[:10],
                         starting_capital=10_000, cash=10_000, status="running", started_at=NOW - timedelta(days=1))
        s.add(exp)
        s.flush()
        exp_id = exp.id
    await rt.engine.generate_setups(exp_id, NOW - timedelta(hours=16))
    with session_scope() as s:
        ps = s.query(PendingSetup).filter_by(experiment_id=exp_id, symbol="AAA").first()
        trig, tgt = (ps.trigger_price, ps.target) if ps else (None, None)
    if trig:
        def quote(px: float, t: datetime) -> None:
            rt.md.quotes.update_from_snapshot(Snapshot("AAA", px, t, bid=px - 0.01, ask=px + 0.01, bid_size=10, ask_size=10,
                                                       quote_ts=t, feed="test-fixture"), t)
            spy = provider.snapshots["SPY"]
            rt.md.quotes.update_from_snapshot(Snapshot("SPY", spy.last_price, t, quote_ts=t, feed="test-fixture"), t)
            rt.md.health.last_success = t
        t1 = NOW + timedelta(minutes=1)
        quote(trig + 0.03, t1)
        await rt.engine.tick(t1)
        rt.engine.snapshot_equity(t1)
        t2 = t1 + timedelta(hours=2)
        quote(tgt + 0.1, t2)
        await rt.engine.tick(t2)
        rt.engine.snapshot_equity(t2)
    from marketpilot.backtest.engine import run_backtest
    from marketpilot.db import BacktestRun

    spy = provider.bars["SPY"]
    uni = {k: v for k, v in provider.bars.items() if k in DEFAULT_UNIVERSE[:12]}
    sectors = {k: v for k, v in provider.bars.items() if k in SECTOR_ETFS}
    d = [b.t.date() for b in spy]
    out = run_backtest("trend_pullback", {}, uni, spy, sectors, d[300], d[-1])
    with session_scope() as s:
        s.add(BacktestRun(strategy_key="trend_pullback", strategy_version="1.0.0", params={}, universe=list(uni),
                          start=d[300].isoformat(), end=d[-1].isoformat(), data_source="test-fixture (synthetic)",
                          assumptions=out["assumptions"], segments=out["segments"], trades=out["result"].trades,
                          equity_curve=[{"date": a, "equity": b} for a, b in out["result"].equity],
                          warnings=["TEST FIXTURE DATA - synthetic, for UI testing only"] + out["result"].warnings))


def main() -> None:
    provider, _ = build()
    init_engine(os.environ["DATABASE_URL"])
    with session_scope() as s:
        seed(s)
    rt = Runtime(get_settings(), MarketDataService(provider, get_settings()))
    asyncio.run(prepare(rt, provider))
    app = create_app(get_settings(), runtime=rt)
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("E2E_PORT", "8010")), log_level="warning")


if __name__ == "__main__":
    main()
