from datetime import datetime, timezone

import pytest

from marketpilot.paper.execution import ExecutionConfig, ExecutionSimulator, QuoteView, regulatory_fees
from marketpilot.risk.manager import MarketState, PortfolioState, RiskConfig, RiskManager

NOW = datetime(2026, 11, 18, 17, 0, tzinfo=timezone.utc)  # Wed 12:00 ET, regular session


def pf(**kw):
    base = dict(starting_capital=10_000, cash=10_000, equity=10_000, day_start_equity=10_000, open_symbols=[])
    base.update(kw)
    return PortfolioState(**base)


def mk(**kw):
    base = dict(now=NOW, price=100.0, bid=99.99, ask=100.01, data_fresh=True, data_reason="ok",
                avg_dollar_volume=5e8, events=[])
    base.update(kw)
    return MarketState(**base)


def failed(v):
    return {c.rule for c in v.checks if c.blocking and not c.passed}


def test_forbidden_settings_rejected_and_ceilings_clamped():
    with pytest.raises(ValueError):
        RiskConfig.from_dict({"allow_short": True})
    with pytest.raises(ValueError):
        RiskConfig.from_dict({"leverage": 2})
    cfg = RiskConfig.from_dict({"max_position_pct": 90, "max_daily_loss_pct": 50, "risk_per_trade_pct": 10})
    assert cfg.max_position_pct == 20 and cfg.max_daily_loss_pct == 5 and cfg.risk_per_trade_pct == 2


def test_sizing_respects_notional_cap_and_risk():
    rm = RiskManager(RiskConfig())
    s = rm.size_position(100.0, 96.0, pf())
    # risk budget 50 -> 12.5 sh; cap 5% of 10k = 500 -> 5 sh; binding = cap
    assert s["qty"] == 5.0 and s["binding_constraint"] == "max_position_notional"
    s2 = rm.size_position(100.0, 99.5, pf(cash=300))
    assert s2["qty"] == pytest.approx(2.985) and s2["binding_constraint"] == "available_cash"


def test_whole_shares_when_fractional_disabled():
    rm = RiskManager(RiskConfig(allow_fractional=False))
    assert rm.size_position(333.0, 320.0, pf())["qty"] == 1.0


def test_approved_entry():
    v = RiskManager(RiskConfig()).evaluate_entry("AAPL", 100.0, 96.0, 108.0, "swing", pf(), mk())
    assert v.approved, v.reasons
    assert v.qty == 5.0 and v.notional == 500.0


@pytest.mark.parametrize("market_kw,pf_kw,args,rule", [
    ({"data_fresh": False, "data_reason": "stale"}, {}, (100, 96, 108), "fresh_data"),
    ({"now": datetime(2026, 11, 18, 23, 0, tzinfo=timezone.utc)}, {}, (100, 96, 108), "regular_session"),
    ({"now": datetime(2026, 11, 18, 14, 32, tzinfo=timezone.utc)}, {}, (100, 96, 108), "not_first_minutes"),
    ({"bid": 99.0, "ask": 101.0}, {}, (100, 96, 108), "spread"),
    ({}, {}, (100, 96, 101), "reward_risk"),
    ({}, {}, (100, 80, 160), "stop_distance"),
    ({"avg_dollar_volume": 1e6}, {}, (100, 96, 108), "liquidity"),
    ({}, {"open_symbols": ["AAPL"]}, (100, 96, 108), "no_duplicate"),
    ({}, {"open_symbols": ["A", "B", "C", "D", "E"]}, (100, 96, 108), "max_positions"),
    ({}, {"open_symbols": ["MSFT", "NVDA"]}, (100, 96, 108), "sector_concentration"),
    ({}, {"equity": 9_790}, (100, 96, 108), "daily_loss_limit"),
    ({"kill_switch": True}, {}, (100, 96, 108), "kill_switch"),
    ({}, {"halted": True, "halted_reason": "x"}, (100, 96, 108), "experiment_not_halted"),
    ({}, {}, (100, 101, 108), "long_only"),
])
def test_each_rule_can_veto(market_kw, pf_kw, args, rule):
    v = RiskManager(RiskConfig()).evaluate_entry("AAPL", *args, "swing", pf(**pf_kw), mk(**market_kw))
    assert not v.approved and rule in failed(v)
    assert v.qty == 0


def test_earnings_and_macro_blackouts():
    ev = [{"kind": "earnings", "symbol": "AAPL", "date": "2026-11-19", "time_et": "amc"}]
    v = RiskManager(RiskConfig()).evaluate_entry("AAPL", 100, 96, 108, "swing", pf(), mk(events=ev))
    assert "earnings_blackout" in failed(v)
    # intraday strategies are exempt from the overnight earnings rule
    v2 = RiskManager(RiskConfig()).evaluate_entry("AAPL", 100, 96, 108, "intraday", pf(), mk(events=ev))
    assert "earnings_blackout" not in failed(v2)
    macro = [{"kind": "macro", "importance": "high", "date": "2026-11-18", "time_et": "12:30", "name": "Test release"}]
    v3 = RiskManager(RiskConfig()).evaluate_entry("AAPL", 100, 96, 108, "swing", pf(), mk(events=macro))
    assert "macro_blackout" in failed(v3)


def test_unverified_earnings_is_warning_not_veto():
    v = RiskManager(RiskConfig()).evaluate_entry("AAPL", 100, 96, 108, "swing", pf(), mk(earnings_checked=False))
    chk = next(c for c in v.checks if c.rule == "earnings_data_verified")
    assert not chk.passed and not chk.blocking and v.approved


# ----------------------------------------------------------------- execution
def q(**kw):
    base = dict(price=100.0, bid=99.98, ask=100.02, bid_size=5, ask_size=5, ts=NOW, fresh=True)
    base.update(kw)
    return QuoteView(**base)


def test_market_buy_pays_ask_plus_slippage_and_sell_hits_bid():
    sim = ExecutionSimulator(ExecutionConfig(slippage_bps=2))
    b = sim.simulate("buy", 10, "market", q())
    assert b.status == "filled" and b.price == pytest.approx(100.02 * 1.0002, abs=1e-4) and b.fees == 0
    s = sim.simulate("sell", 10, "market", q())
    assert s.price == pytest.approx(99.98 * 0.9998, abs=1e-4) and s.fees > 0


def test_no_quote_or_stale_quote_rejects():
    sim = ExecutionSimulator()
    assert sim.simulate("buy", 1, "market", q(fresh=False, fresh_reason="stale")).status == "rejected"
    assert sim.simulate("buy", 1, "market", q(price=None)).status == "rejected"


def test_wide_spread_rejects_and_one_sided_quote_uses_assumed_spread():
    sim = ExecutionSimulator(ExecutionConfig(max_spread_bps=50))
    assert sim.simulate("buy", 1, "market", q(bid=99, ask=101)).status == "rejected"
    r = sim.simulate("buy", 1, "market", q(bid=None, ask=None))
    assert r.status == "filled" and r.model["assumed_half_spread_bps"] == 3.0


def test_limit_orders_and_partial_fills():
    sim = ExecutionSimulator(ExecutionConfig(slippage_bps=0))
    assert sim.simulate("buy", 1, "limit", q(), limit_price=99.0).status == "not_marketable"
    r = sim.simulate("sell", 1, "limit", q(), limit_price=99.5)
    assert r.status == "filled" and r.price == pytest.approx(99.98)
    p = sim.simulate("buy", 800, "market", q(ask_size=2))
    assert p.status == "partial" and p.qty == 200


def test_regulatory_fees():
    cfg = ExecutionConfig()
    # $10,000 sold, 100 shares: SEC 0.206 -> 0.21, TAF 0.0195 -> 0.02
    assert regulatory_fees("sell", 100, 100.0, cfg) == pytest.approx(0.23)
    assert regulatory_fees("buy", 100, 100.0, cfg) == 0.0
    # TAF cap
    assert regulatory_fees("sell", 1_000_000, 0.01, cfg) == pytest.approx(0.21 + 9.79)
