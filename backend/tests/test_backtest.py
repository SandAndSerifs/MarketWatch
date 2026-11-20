from dataclasses import replace
from datetime import date

from marketpilot.backtest.engine import Backtester, run_backtest, split_dates
from marketpilot.data.universe import SECTOR_ETFS
from marketpilot.risk.manager import RiskConfig
from marketpilot.strategies.base import ParamSpec, SetupProposal, Strategy
from marketpilot.strategies.library import create_strategy

from .fakes import make_bars, random_walk, trading_days


def _data(n=700, seeds=range(1, 9)):
    days = trading_days(date(2026, 11, 17), n)
    bars = {f"S{i}": make_bars(days, random_walk(days, seed=i, mu=0.0006)) for i in seeds}
    spy = make_bars(days, random_walk(days, seed=99, start=300, mu=0.0004, sigma=0.008))
    sectors = {k: make_bars(days, random_walk(days, seed=hash(k) % 1000, start=80)) for k in SECTOR_ETFS}
    return days, bars, spy, sectors


def test_split_dates_are_chronological_and_disjoint():
    days = trading_days(date(2026, 11, 17), 100)
    s = split_dates(days)
    assert s["train"][1] < s["validation"][0] <= s["validation"][1] < s["test"][0]
    assert s["test"][1] == days[-1]


def test_backtest_runs_and_reports_segments():
    days, bars, spy, sectors = _data()
    out = run_backtest("trend_pullback", {}, bars, spy, sectors, days[260], days[-1])
    seg = out["segments"]
    assert {"train", "validation", "test", "full", "by_regime"} <= set(seg)
    res = out["result"]
    assert any("survivorship" in w.lower() for w in res.warnings)
    for t in res.trades:
        assert t["entry_date"] <= t["exit_date"]
        assert t["fees"] >= 0
    assert res.equity and res.equity[0][1] > 0


def test_no_look_ahead_future_bars_do_not_change_past_trades():
    days, bars, spy, sectors = _data()
    cutoff = days[500]
    base = run_backtest("breakout", {}, bars, spy, sectors, days[260], days[-1])["result"]
    # Corrupt everything after the cutoff
    bars2 = {k: [b if b.t.date() <= cutoff else replace(b, o=b.o * 3, h=b.h * 3, l=b.l * 3, c=b.c * 3) for b in v]
             for k, v in bars.items()}
    alt = run_backtest("breakout", {}, bars2, spy, sectors, days[260], days[-1])["result"]
    done_before = [t for t in base.trades if t["exit_date"] < cutoff.isoformat()]
    done_before_alt = [t for t in alt.trades if t["exit_date"] < cutoff.isoformat()]
    assert done_before == done_before_alt
    eq_before = [e for e in base.equity if e[0] < cutoff.isoformat()]
    assert eq_before == [e for e in alt.equity if e[0] < cutoff.isoformat()]


class _AlwaysBuy(Strategy):
    key = "always"
    name = "Always (test)"
    param_specs = (ParamSpec("x", 1.0),)

    def evaluate(self, ctx):
        c = ctx.tech["close"]
        return SetupProposal(ctx.symbol, self.key, self.version, "t", [], "buy_stop", round(c * 1.001, 4),
                             round(c * 0.97, 4), round(c * 1.10, 4), ["x"], 50)


def test_pessimistic_intrabar_stop_on_entry_bar():
    days = trading_days(date(2026, 11, 17), 300)
    closes = [100.0] * 300
    bars = make_bars(days, closes, spread=0.001)
    # Day 280: range touches both the trigger (100.1) and the stop (97)
    b = bars[280]
    bars[280] = replace(b, h=101.0, l=96.0)
    spy = make_bars(days, [300 + i * 0.1 for i in range(300)])
    bt = Backtester(_AlwaysBuy(), {"X": bars}, spy, {}, RiskConfig(min_avg_dollar_volume=1_000_000), use_challenge=False)
    res = bt.run(days[279], days[299])
    first = res.trades[0]
    assert first["entry_date"] == days[280].isoformat() and first["exit_rule"] == "stop"
    assert first["exit_date"] == days[280].isoformat()


def test_gap_through_stop_fills_at_open():
    days = trading_days(date(2026, 11, 17), 300)
    bars = make_bars(days, [100.0] * 300, spread=0.001)
    bars[280] = replace(bars[280], o=100.0, h=100.5, l=99.95, c=100.4)   # entry day, no stop touch
    bars[281] = replace(bars[281], o=90.0, h=91.0, l=89.0, c=90.5)       # gap down through 97 stop
    spy = make_bars(days, [300 + i * 0.1 for i in range(300)])
    bt = Backtester(_AlwaysBuy(), {"X": bars}, spy, {}, RiskConfig(min_avg_dollar_volume=1_000_000), use_challenge=False)
    res = bt.run(days[279], days[299])
    t = res.trades[0]
    assert t["exit_rule"] == "stop" and t["exit_price"] < 90.0 and t["r_multiple"] < -3


def test_intraday_strategy_not_backtestable():
    import pytest

    days, bars, spy, sectors = _data(300, range(1, 2))
    with pytest.raises(ValueError):
        run_backtest("vwap_reclaim", {}, bars, spy, sectors, days[260], days[-1])
    assert create_strategy("vwap_reclaim").backtestable is False
