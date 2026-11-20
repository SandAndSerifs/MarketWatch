"""End-to-end paper trading flow with TEST FIXTURE data and a controlled clock."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from marketpilot.alerts.service import AlertService
from marketpilot.config import get_settings
from marketpilot.data.models import Snapshot
from marketpilot.data.service import MarketDataService
from marketpilot.data.universe import SECTOR_ETFS
from marketpilot.db import Alert, Decision, Experiment, Order, PendingSetup, Position, Trade, session_scope
from marketpilot.paper.engine import PaperEngine
from marketpilot.services.analysis import AnalysisService

from .fakes import FakeProvider, make_bars, trading_days, uptrend_then_pullback

NOW = datetime(2026, 11, 18, 15, 30, tzinfo=timezone.utc)  # Wed 10:30 ET


@pytest.fixture()
def setup_engine(db):
    days = trading_days(date(2026, 11, 17), 320)
    bars = {"AAA": make_bars(days, uptrend_then_pullback(days)),
            "SPY": make_bars(days, uptrend_then_pullback(days, start=300, drift=0.0015, pullback=0))}
    for etf in SECTOR_ETFS:
        bars[etf] = make_bars(days, uptrend_then_pullback(days, start=80, drift=0.001, pullback=0))
    md = MarketDataService(FakeProvider(bars), get_settings())
    analysis = AnalysisService(md)
    engine = PaperEngine(md, analysis, AlertService(md.hub), real_time=False)
    with session_scope() as s:
        exp = Experiment(name="Fixture test", strategy_key="trend_pullback", strategy_version="1.0.0",
                         strategy_params={}, risk_config={"risk": {}, "execution": {"slippage_bps": 2}},
                         universe=["AAA"], starting_capital=10_000, cash=10_000, status="running", started_at=NOW)
        s.add(exp)
        s.flush()
        exp_id = exp.id
    return md, engine, exp_id, bars


def set_quote(md, sym, price, now):
    md.quotes.update_from_snapshot(Snapshot(sym, price, now, bid=round(price - 0.01, 2), ask=round(price + 0.01, 2),
                                            bid_size=10, ask_size=10, quote_ts=now, feed="test-fixture"), now)
    md.health.last_success = now


async def _arm(engine, exp_id):
    res = await engine.generate_setups(exp_id, NOW - timedelta(hours=16))
    assert res["evaluated"] == 1
    with session_scope() as s:
        ps = s.execute(select(PendingSetup).where(PendingSetup.experiment_id == exp_id)).scalar_one()
        dec = s.get(Decision, ps.decision_id)
        return ps.id, ps.trigger_price, ps.stop, ps.target, dec.record


@pytest.mark.asyncio
async def test_full_trade_lifecycle(setup_engine):
    md, engine, exp_id, _ = setup_engine
    setup_id, trigger, stop, target, record = await _arm(engine, exp_id)
    # The checklist is complete and argues against itself
    steps = record["steps"]
    assert set(steps) == {"1_market_conditions", "2_stock_analysis", "3_thesis", "4_evidence", "5_challenge",
                          "6_risk", "7_decision", "8_post_trade"}
    assert steps["5_challenge"]["what_would_prove_it_wrong"]
    assert steps["7_decision"]["category"] == "BUY_CANDIDATE"
    assert stop < trigger < target

    # price below trigger: nothing happens
    set_quote(md, "AAA", trigger - 0.5, NOW)
    set_quote(md, "SPY", 400, NOW)
    await engine.tick(NOW)
    with session_scope() as s:
        assert s.execute(select(Trade)).first() is None

    # trigger hit -> Risk Manager re-check -> simulated fill
    t1 = NOW + timedelta(minutes=1)
    set_quote(md, "AAA", trigger + 0.05, t1)
    set_quote(md, "SPY", 400, t1)
    await engine.tick(t1)
    with session_scope() as s:
        trade = s.execute(select(Trade)).scalar_one()
        exp = s.get(Experiment, exp_id)
        order = s.execute(select(Order).where(Order.purpose == "entry")).scalar_one()
        assert order.client_order_id == f"entry:{exp_id}:{setup_id}" and order.status == "filled"
        assert trade.status == "open" and trade.entry_price > trigger  # paid ask + slippage
        assert trade.qty * trade.entry_price <= 500.0 + 1e-6  # 5% notional cap
        assert exp.cash == pytest.approx(10_000 - trade.qty * trade.entry_price - trade.fees)
        trig_dec = s.get(Decision, trade.decision_id)
        assert trig_dec.record["trigger"]["setup_decision_id"] is not None
        assert trig_dec.record["steps"]["6_risk"]["verdict"]["approved"] is True

    # duplicate entry attempts are ignored
    await engine._enter(exp_id, setup_id, t1)
    with session_scope() as s:
        assert len(s.execute(select(Order).where(Order.purpose == "entry")).all()) == 1

    # target reached -> exit, post-trade review attached
    t2 = t1 + timedelta(minutes=30)
    set_quote(md, "AAA", target + 0.2, t2)
    set_quote(md, "SPY", 401, t2)
    await engine.tick(t2)
    with session_scope() as s:
        trade = s.execute(select(Trade)).scalar_one()
        exp = s.get(Experiment, exp_id)
        assert trade.status == "closed" and trade.exit_reason.startswith("Target")
        assert trade.net_pnl > 0 and trade.r_multiple > 1.5
        assert trade.review["exit_rule"] == "target" and trade.review["decision_quality"] == "Plan followed"
        assert s.execute(select(Position)).first() is None
        assert exp.cash == pytest.approx(10_000 + trade.net_pnl, abs=0.01)
        kinds = {a.kind for a in s.execute(select(Alert)).scalars()}
        assert "trade" in kinds


@pytest.mark.asyncio
async def test_stop_loss_exit_and_gap(setup_engine):
    md, engine, exp_id, _ = setup_engine
    setup_id, trigger, stop, target, _ = await _arm(engine, exp_id)
    t1 = NOW + timedelta(minutes=1)
    set_quote(md, "AAA", trigger + 0.02, t1)
    await engine.tick(t1)
    t2 = t1 + timedelta(minutes=5)
    gap_price = stop - 1.0  # trades through the stop
    set_quote(md, "AAA", gap_price, t2)
    await engine.tick(t2)
    with session_scope() as s:
        tr = s.execute(select(Trade)).scalar_one()
        assert tr.status == "closed" and tr.review["exit_rule"] == "stop"
        assert tr.exit_price < stop  # realistic: filled at the bid, not at the stop price
        assert tr.r_multiple < -1


@pytest.mark.asyncio
async def test_auto_pause_on_stale_data_and_resume(setup_engine):
    md, engine, exp_id, _ = setup_engine
    await _arm(engine, exp_id)
    set_quote(md, "AAA", 1.0, NOW)
    md.health.last_success = NOW - timedelta(minutes=10)  # feed silent for 10 minutes
    await engine.tick(NOW)
    assert exp_id in engine.auto_paused
    with session_scope() as s:
        assert s.execute(select(Alert).where(Alert.kind == "risk")).first() is not None
        assert s.execute(select(Order)).first() is None
    md.health.last_success = NOW
    await engine.tick(NOW)  # first healthy check: still paused (hysteresis)
    assert exp_id in engine.auto_paused
    await engine.tick(NOW + timedelta(seconds=20))
    assert exp_id not in engine.auto_paused


@pytest.mark.asyncio
async def test_daily_loss_limit_halts_experiment(setup_engine):
    md, engine, exp_id, _ = setup_engine
    with session_scope() as s:
        exp = s.get(Experiment, exp_id)
        exp.day_start_date = "2026-11-18"
        exp.day_start_equity = 10_300  # equity 10,000 => -300 < -200 limit
    set_quote(md, "SPY", 400, NOW)
    await engine.tick(NOW)
    with session_scope() as s:
        exp = s.get(Experiment, exp_id)
        assert exp.status == "halted" and exp.halted_reason.startswith("daily_loss")


@pytest.mark.asyncio
async def test_emergency_stop_halts_everything(setup_engine):
    md, engine, exp_id, _ = setup_engine
    await _arm(engine, exp_id)
    res = await engine.emergency_stop(flatten=False)
    assert res["halted_experiments"] == 1
    with session_scope() as s:
        assert s.get(Experiment, exp_id).status == "halted"
        assert s.execute(select(PendingSetup).where(PendingSetup.status == "armed")).first() is None
    set_quote(md, "AAA", 999, NOW)
    await engine.tick(NOW)
    with session_scope() as s:
        assert s.execute(select(Order)).first() is None
    engine.clear_emergency_stop()
    assert engine.status()["kill_switch"]["active"] is False


@pytest.mark.asyncio
async def test_no_entry_outside_regular_session(setup_engine):
    md, engine, exp_id, _ = setup_engine
    _, trigger, *_ = await _arm(engine, exp_id)
    after = datetime(2026, 11, 18, 22, 0, tzinfo=timezone.utc)  # 17:00 ET
    set_quote(md, "AAA", trigger + 1, after)
    await engine.tick(after)
    with session_scope() as s:
        assert s.execute(select(Order)).first() is None
