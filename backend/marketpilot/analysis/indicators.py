"""Technical indicators.

Every function is *causal*: the value at index i depends only on inputs[0..i].
Warm-up periods are NaN. Tests verify causality by recomputing on truncated
inputs, which is the core guarantee against look-ahead bias in backtests.

Conventions follow the original definitions:
  RSI / ATR / ADX use Wilder's smoothing (alpha = 1/n), seeded with a simple mean.
  EMA uses alpha = 2/(n+1), seeded with the SMA of the first n values.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import numpy as np

from ..data.calendar import et_date

Arr = np.ndarray


def _a(x: Sequence[float] | Arr) -> Arr:
    return np.asarray(x, dtype=float)


def sma(x: Sequence[float] | Arr, n: int) -> Arr:
    x = _a(x)
    out = np.full(x.shape, np.nan)
    if n <= 0 or len(x) < n:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[n - 1 :] = (c[n:] - c[:-n]) / n
    return out


def ema(x: Sequence[float] | Arr, n: int) -> Arr:
    x = _a(x)
    out = np.full(x.shape, np.nan)
    if n <= 0 or len(x) < n:
        return out
    alpha = 2.0 / (n + 1)
    out[n - 1] = x[:n].mean()
    for i in range(n, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out


def wilder(x: Sequence[float] | Arr, n: int, start: int = 0) -> Arr:
    """Wilder smoothing of x beginning at index `start` (values before are ignored)."""
    x = _a(x)
    out = np.full(x.shape, np.nan)
    if len(x) - start < n:
        return out
    out[start + n - 1] = x[start : start + n].mean()
    for i in range(start + n, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def rsi(close: Sequence[float] | Arr, n: int = 14) -> Arr:
    c = _a(close)
    out = np.full(c.shape, np.nan)
    if len(c) <= n:
        return out
    d = np.diff(c)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    ag = wilder(gain, n)
    al = wilder(loss, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ag / al
        r = 100 - 100 / (1 + rs)
    r = np.where((al == 0) & (ag > 0), 100.0, r)
    r = np.where((al == 0) & (ag == 0), 50.0, r)
    out[1:] = r
    return out


def macd(close: Sequence[float] | Arr, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[Arr, Arr, Arr]:
    c = _a(close)
    line = ema(c, fast) - ema(c, slow)
    sig = np.full(c.shape, np.nan)
    valid = np.where(~np.isnan(line))[0]
    if len(valid) >= signal:
        start = valid[0]
        sig[start:] = ema(line[start:], signal)
    return line, sig, line - sig


def bollinger(close: Sequence[float] | Arr, n: int = 20, k: float = 2.0) -> tuple[Arr, Arr, Arr]:
    c = _a(close)
    mid = sma(c, n)
    sd = np.full(c.shape, np.nan)
    for i in range(n - 1, len(c)):
        sd[i] = c[i - n + 1 : i + 1].std(ddof=0)
    return mid, mid + k * sd, mid - k * sd


def true_range(high: Sequence[float] | Arr, low: Sequence[float] | Arr, close: Sequence[float] | Arr) -> Arr:
    h, l, c = _a(high), _a(low), _a(close)  # noqa: E741
    prev = np.concatenate([[np.nan], c[:-1]])
    tr = np.nanmax(np.vstack([h - l, np.abs(h - prev), np.abs(l - prev)]), axis=0)
    tr[0] = h[0] - l[0]
    return tr


def atr(high, low, close, n: int = 14) -> Arr:  # type: ignore[no-untyped-def]
    return wilder(true_range(high, low, close), n)


def adx(high, low, close, n: int = 14) -> tuple[Arr, Arr, Arr]:  # type: ignore[no-untyped-def]
    h, l, c = _a(high), _a(low), _a(close)  # noqa: E741
    up = np.diff(h, prepend=np.nan)
    dn = -np.diff(l, prepend=np.nan)
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    plus_dm[0] = minus_dm[0] = 0.0
    tr = true_range(h, l, c)
    atr_ = wilder(tr, n, start=1)
    pdi = 100 * wilder(plus_dm, n, start=1) / atr_
    mdi = 100 * wilder(minus_dm, n, start=1) / atr_
    with np.errstate(divide="ignore", invalid="ignore"):
        dx = 100 * np.abs(pdi - mdi) / (pdi + mdi)
    first = np.where(~np.isnan(dx))[0]
    adx_ = np.full(h.shape, np.nan)
    if len(first) and len(h) - first[0] >= n:
        adx_ = wilder(np.nan_to_num(dx, nan=0.0), n, start=first[0])
    return adx_, pdi, mdi


def roc(close: Sequence[float] | Arr, n: int) -> Arr:
    c = _a(close)
    out = np.full(c.shape, np.nan)
    if len(c) > n:
        out[n:] = (c[n:] / c[:-n] - 1) * 100
    return out


def rolling_max_prior(x: Sequence[float] | Arr, n: int) -> Arr:
    """Max of the n values *before* index i (excludes the current bar)."""
    x = _a(x)
    out = np.full(x.shape, np.nan)
    for i in range(n, len(x)):
        out[i] = x[i - n : i].max()
    return out


def rolling_min_prior(x: Sequence[float] | Arr, n: int) -> Arr:
    x = _a(x)
    out = np.full(x.shape, np.nan)
    for i in range(n, len(x)):
        out[i] = x[i - n : i].min()
    return out


def relative_volume(volume: Sequence[float] | Arr, n: int = 20) -> Arr:
    """Volume divided by the average of the previous n bars (current bar excluded)."""
    v = _a(volume)
    out = np.full(v.shape, np.nan)
    for i in range(n, len(v)):
        avg = v[i - n : i].mean()
        out[i] = v[i] / avg if avg > 0 else np.nan
    return out


def session_vwap(times: Sequence[datetime], high, low, close, volume) -> Arr:  # type: ignore[no-untyped-def]
    """VWAP anchored at each US/Eastern session start (intraday bars)."""
    h, l, c, v = _a(high), _a(low), _a(close), _a(volume)  # noqa: E741
    tp = (h + l + c) / 3
    out = np.full(c.shape, np.nan)
    cum_pv = cum_v = 0.0
    cur_day = None
    for i, t in enumerate(times):
        d = et_date(t)
        if d != cur_day:
            cur_day, cum_pv, cum_v = d, 0.0, 0.0
        cum_pv += tp[i] * v[i]
        cum_v += v[i]
        out[i] = cum_pv / cum_v if cum_v > 0 else tp[i]
    return out


def swing_levels(high, low, close, lookback: int = 120, window: int = 3, tolerance_pct: float = 1.0,  # type: ignore[no-untyped-def]
                 max_levels: int = 6) -> dict[str, list[dict[str, float]]]:
    """Support/resistance from confirmed swing pivots, clustered by price.

    A pivot at i is confirmed only once `window` bars after it exist, so the most
    recent `window` bars can never create a level (no look-ahead). Levels with
    more touches rank higher.
    """
    h, l, c = _a(high)[-lookback:], _a(low)[-lookback:], _a(close)[-lookback:]  # noqa: E741
    if len(c) < 2 * window + 1:
        return {"support": [], "resistance": []}
    pivots: list[float] = []
    for i in range(window, len(c) - window):
        if h[i] == h[i - window : i + window + 1].max():
            pivots.append(float(h[i]))
        if l[i] == l[i - window : i + window + 1].min():
            pivots.append(float(l[i]))
    pivots.sort()
    clusters: list[list[float]] = []
    for p in pivots:
        if clusters and abs(p - np.mean(clusters[-1])) / p * 100 <= tolerance_pct:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    last = float(c[-1])
    levels = [{"price": round(float(np.mean(cl)), 4), "touches": float(len(cl))} for cl in clusters]
    sup = sorted([lv for lv in levels if lv["price"] < last], key=lambda lv: (-lv["touches"], last - lv["price"]))
    res = sorted([lv for lv in levels if lv["price"] > last], key=lambda lv: (-lv["touches"], lv["price"] - last))
    return {
        "support": sorted(sup[:max_levels], key=lambda lv: -lv["price"]),
        "resistance": sorted(res[:max_levels], key=lambda lv: lv["price"]),
    }


def last(x: Arr) -> float | None:
    if len(x) == 0 or np.isnan(x[-1]):
        return None
    return float(x[-1])
