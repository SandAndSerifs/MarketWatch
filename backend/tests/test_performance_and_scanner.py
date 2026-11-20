from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from marketpilot.analysis.performance import return_stats, risk_adjusted_score, summarize, trade_stats
from marketpilot.config import get_settings
from marketpilot.data.service import MarketDataService
from marketpilot.data.universe import SECTOR_ETFS
from marketpilot.db import Alert, AppSetting, Signal, session_scope
from marketpilot.services.runtime import Runtime, last_completed_session

from .fakes import FakeProvider, make_bars, trading_days, uptrend_then_pullback


def test_trade_stats_edge_cases():
    only_win = trade_stats([{"net_pnl": 35.0, "r_multiple": 2.0}])
    assert only_win["largest_loss"] is None and only_win["profit_factor"] is None
    assert only_win["profit_factor_note"] and only_win["sample_warning"]
    lo, hi = only_win["win_rate_ci95"]
    assert lo < 50 < hi  # one win says almost nothing
    mixed = trade_stats([{"net_pnl": 30, "r_multiple": 1.5}, {"net_pnl": -10, "r_multiple": -1.0}, {"net_pnl": -10, "r_multiple": -1.0}])
    assert mixed["profit_factor"] == pytest.approx(1.5) and mixed["win_rate"] == pytest.approx(33.33, abs=0.01)
    assert mixed["longest_losing_streak"] == 2


def test_ratios_require_enough_days():
    assert return_stats([100, 101, 102])["sharpe"] is None
    vals = [100 * (1.001 ** i) * (1 + 0.002 * (-1) ** i) for i in range(40)]
    assert return_stats(vals)["sharpe"] is not None


def test_score_does_not_reward_risk_or_luck():
    lucky = {"sharpe": 5.0, "max_drawdown_pct": -2, "trade_stats": {"trades": 3}}
    steady = {"sharpe": 1.2, "max_drawdown_pct": -6, "trade_stats": {"trades": 60}}
    reckless = {"sharpe": 1.5, "max_drawdown_pct": -35, "trade_stats": {"trades": 60}}
    s = {k: risk_adjusted_score(v)["score"] for k, v in {"lucky": lucky, "steady": steady, "reckless": reckless}.items()}
    assert s["steady"] > s["lucky"] and s["steady"] > s["reckless"]


def test_summarize_with_benchmark():
    t0 = datetime(2026, 10, 1, 20, tzinfo=timezone.utc)
    pts = [(t0 + timedelta(days=i), 10_000 + i * 10) for i in range(30)]
    bench = [(t0 + timedelta(days=i), 600 + i) for i in range(30)]
    out = summarize(pts, 10_000, [], bench)
    assert out["benchmark"]["return_pct"] > 0 and "excess_return_pct" in out["benchmark"]


def test_last_completed_session():
    assert last_completed_session(datetime(2026, 11, 18, 15, tzinfo=timezone.utc)) == "2026-11-17"
    assert last_completed_session(datetime(2026, 11, 18, 22, tzinfo=timezone.utc)) == "2026-11-18"
    assert last_completed_session(datetime(2026, 11, 27, 3, tzinfo=timezone.utc)) == "2026-11-25"  # Thanksgiving


@pytest.mark.asyncio
async def test_scanner_creates_signals_alerts_and_dedupes(db):
    days = trading_days(date(2026, 11, 17), 320)
    bars = {"SPY": make_bars(days, uptrend_then_pullback(days, start=300, drift=0.0015, pullback=0))}
    for etf in SECTOR_ETFS:
        bars[etf] = make_bars(days, uptrend_then_pullback(days, start=80, drift=0.001, pullback=0))
    bars["AAA"] = make_bars(days, uptrend_then_pullback(days))
    rt = Runtime(get_settings(), MarketDataService(FakeProvider(bars), get_settings()))
    with session_scope() as s:
        s.merge(AppSetting(key="scanner", value={"use_default_universe": False, "extra_symbols": ["AAA"],
                                                 "strategies": ["trend_pullback"]}))
        from marketpilot.db import WatchlistItem

        for w in s.execute(select(WatchlistItem)).scalars():
            s.delete(w)
    now = datetime(2026, 11, 17, 23, 30, tzinfo=timezone.utc)
    res = await rt.scanner.full_scan(now)
    assert res["new_signals"] >= 1
    again = await rt.scanner.full_scan(now)
    assert again["new_signals"] == 0  # same bar, same strategy -> deduplicated
    with session_scope() as s:
        sig = s.execute(select(Signal).where(Signal.symbol == "AAA")).scalars().first()
        assert sig.category == "BUY_CANDIDATE" and sig.decision_id and sig.stop < sig.entry < sig.target
        alerts = s.execute(select(Alert).where(Alert.kind == "signal")).scalars().all()
        assert len(alerts) == 1 and "Plan:" in alerts[0].body
