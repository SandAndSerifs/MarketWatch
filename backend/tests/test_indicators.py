import numpy as np
import pytest

from marketpilot.analysis import indicators as ind
from marketpilot.analysis.technicals import TechSeries, technical_profile

from .fakes import make_bars, random_walk, trading_days
from datetime import date


def test_sma_ema_known_values():
    x = [1, 2, 3, 4, 5, 6]
    assert np.allclose(ind.sma(x, 3)[2:], [2, 3, 4, 5])
    e = ind.ema(x, 3)
    assert np.isnan(e[1]) and e[2] == pytest.approx(2.0)
    assert e[3] == pytest.approx(0.5 * 4 + 0.5 * 2.0)


def test_rsi_extremes_and_reference():
    up = np.arange(1, 40, dtype=float)
    assert ind.rsi(up, 14)[-1] == pytest.approx(100.0)
    down = up[::-1]
    assert ind.rsi(down, 14)[-1] == pytest.approx(0.0)
    # independent reference implementation of Wilder RSI
    rng = np.random.default_rng(3)
    c = 100 + np.cumsum(rng.normal(0, 1, 120))
    d = np.diff(c)
    g, l = np.clip(d, 0, None), np.clip(-d, 0, None)  # noqa: E741
    ag, al = g[:14].mean(), l[:14].mean()
    for i in range(14, len(d)):
        ag, al = (ag * 13 + g[i]) / 14, (al * 13 + l[i]) / 14
    ref = 100 - 100 / (1 + ag / al)
    assert ind.rsi(c, 14)[-1] == pytest.approx(ref, rel=1e-9)


def test_atr_counts_gaps():
    h, l, c = [10, 12, 20], [9, 11, 19], [9.5, 11.5, 19.5]  # noqa: E741
    tr = ind.true_range(h, l, c)
    assert tr[2] == pytest.approx(20 - 11.5)


def test_bollinger_matches_population_std():
    x = np.arange(1, 25, dtype=float)
    mid, up, lo = ind.bollinger(x, 20, 2)
    assert up[-1] - mid[-1] == pytest.approx(2 * x[-20:].std(ddof=0))


@pytest.mark.parametrize("fn", [
    lambda c, h, l, v: ind.sma(c, 20), lambda c, h, l, v: ind.ema(c, 20), lambda c, h, l, v: ind.rsi(c, 14),
    lambda c, h, l, v: ind.macd(c)[2], lambda c, h, l, v: ind.bollinger(c)[1], lambda c, h, l, v: ind.atr(h, l, c),
    lambda c, h, l, v: ind.adx(h, l, c)[0], lambda c, h, l, v: ind.rolling_max_prior(h, 20),
    lambda c, h, l, v: ind.relative_volume(v), lambda c, h, l, v: ind.roc(c, 20),
])
def test_indicators_are_causal(fn):
    """Value at i must not change when future data is removed (no look-ahead)."""
    rng = np.random.default_rng(7)
    c = 50 + np.cumsum(rng.normal(0, 1, 260))
    h, l = c + rng.uniform(0.1, 1, 260), c - rng.uniform(0.1, 1, 260)  # noqa: E741
    v = rng.uniform(1e5, 1e6, 260)
    full = fn(c, h, l, v)
    for k in (60, 120, 200, 259):
        part = fn(c[: k + 1], h[: k + 1], l[: k + 1], v[: k + 1])
        a, b = full[: k + 1], part
        mask = ~np.isnan(b)
        assert np.allclose(a[mask], b[mask])
        assert np.array_equal(np.isnan(a), np.isnan(b))


def test_profile_at_equals_truncated_profile():
    days = trading_days(date(2026, 11, 17), 320)
    bars = make_bars(days, random_walk(days, seed=11))
    ser = TechSeries(bars)
    for i in (100, 250, 319):
        assert ser.profile_at(i) == technical_profile(bars[: i + 1])


def test_swing_levels_ignore_unconfirmed_recent_bars():
    h = [10, 11, 12, 11, 10, 11, 12, 13, 12, 11, 10, 9, 15]
    l = [x - 1 for x in h]  # noqa: E741
    c = [x - 0.5 for x in h]
    lv = ind.swing_levels(h, l, c, window=2)
    assert all(x["price"] != 15 for x in lv["resistance"])  # last bar cannot be a confirmed pivot


def test_profile_requires_history():
    days = trading_days(date(2026, 11, 17), 10)
    assert technical_profile(make_bars(days, [100.0] * 10))["ok"] is False
