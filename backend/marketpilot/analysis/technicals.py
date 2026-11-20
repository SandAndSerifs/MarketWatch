"""Technical profile and market regime built from verified bars.

Indicators are computed once over the whole series (`TechSeries`) and read at an
index with `profile_at(i)`. Because every indicator is causal, the profile at i is
identical to computing it on bars[:i+1] - this is what lets the backtester replay
history quickly without look-ahead (verified in tests).
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..data.models import Bar
from . import indicators as ind


def _f(x: Any, nd: int = 4) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if np.isnan(x) else round(x, nd)


class TechSeries:
    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.t = [b.t for b in bars]
        o = np.array([b.o for b in bars], dtype=float)
        h = np.array([b.h for b in bars], dtype=float)
        l = np.array([b.l for b in bars], dtype=float)  # noqa: E741
        c = np.array([b.c for b in bars], dtype=float)
        v = np.array([b.v for b in bars], dtype=float)
        self.o, self.h, self.l, self.c, self.v = o, h, l, c, v
        n = len(c)
        if n == 0:
            return
        self.sma20, self.sma50, self.sma200 = ind.sma(c, 20), ind.sma(c, 50), ind.sma(c, 200)
        self.ema9, self.ema20 = ind.ema(c, 9), ind.ema(c, 20)
        self.rsi14, self.rsi2 = ind.rsi(c, 14), ind.rsi(c, 2)
        self.macd, self.macd_sig, self.macd_hist = ind.macd(c)
        self.bb_mid, self.bb_up, self.bb_lo = ind.bollinger(c, 20, 2.0)
        self.atr14 = ind.atr(h, l, c, 14)
        self.adx14, self.pdi, self.mdi = ind.adx(h, l, c, 14)
        self.rvol = ind.relative_volume(v, 20)
        self.hi20, self.lo20 = ind.rolling_max_prior(h, 20), ind.rolling_min_prior(l, 20)
        self.hi55, self.lo10 = ind.rolling_max_prior(h, 55), ind.rolling_min_prior(l, 10)
        self.roc5, self.roc20, self.roc63, self.roc126 = (ind.roc(c, k) for k in (5, 20, 63, 126))
        with np.errstate(divide="ignore", invalid="ignore"):
            self.width = (self.bb_up - self.bb_lo) / self.bb_mid
        self.dollar_vol = c * v

    def __len__(self) -> int:
        return len(self.bars)

    def profile_at(self, i: int, with_levels: bool = True) -> dict[str, Any]:
        n = len(self.bars)
        if i < 0:
            i += n
        if i + 1 < 30:
            return {"ok": False, "reason": f"Only {i + 1} bars available; at least 30 needed", "bars": i + 1}
        c, h, l, o = self.c, self.h, self.l, self.o  # noqa: E741
        close = float(c[i])
        atr_v = _f(self.atr14[i])
        s50, s200 = _f(self.sma50[i]), _f(self.sma200[i])
        s50_prev = _f(self.sma50[i - 10]) if i >= 60 else None
        if s50 and s200:
            if close > s50 > s200 and (s50_prev is None or s50 > s50_prev):
                trend = "uptrend"
            elif close < s50 < s200:
                trend = "downtrend"
            else:
                trend = "mixed"
        elif s50:
            trend = "uptrend" if close > s50 else "downtrend"
        else:
            trend = "unknown"
        w = self.width[max(0, i - 119) : i + 1]
        w = w[~np.isnan(w)]
        width_pctile = float((w < self.width[i]).mean() * 100) if len(w) > 20 and not np.isnan(self.width[i]) else None
        adv20 = float(self.dollar_vol[max(0, i - 20) : i].mean()) if i >= 1 else float(self.dollar_vol[i])
        lo252 = max(0, i - 251)
        high252, low252 = float(h[lo252 : i + 1].max()), float(l[lo252 : i + 1].min())

        def cross_up(a: np.ndarray, b: np.ndarray) -> bool:
            return bool(i >= 1 and not np.isnan(a[i - 1]) and not np.isnan(b[i - 1]) and a[i - 1] <= b[i - 1] and a[i] > b[i])

        def cross_down(a: np.ndarray, b: np.ndarray) -> bool:
            return bool(i >= 1 and not np.isnan(a[i - 1]) and not np.isnan(b[i - 1]) and a[i - 1] >= b[i - 1] and a[i] < b[i])

        up, lo_ = self.bb_up[i], self.bb_lo[i]
        prof: dict[str, Any] = {
            "ok": True, "bars": i + 1, "as_of": self.t[i].isoformat(),
            "open": _f(o[i]), "high": _f(h[i]), "low": _f(l[i]), "close": _f(close), "prev_close": _f(c[i - 1]),
            "change_pct": _f((close / c[i - 1] - 1) * 100, 3), "volume": float(self.v[i]),
            "sma20": _f(self.sma20[i]), "sma50": s50, "sma200": s200, "ema9": _f(self.ema9[i]), "ema20": _f(self.ema20[i]),
            "rsi14": _f(self.rsi14[i], 2), "rsi2": _f(self.rsi2[i], 2), "rsi14_prev": _f(self.rsi14[i - 1], 2),
            "macd": _f(self.macd[i]), "macd_signal": _f(self.macd_sig[i]), "macd_hist": _f(self.macd_hist[i]),
            "macd_hist_prev": _f(self.macd_hist[i - 1]),
            "macd_cross_up": cross_up(self.macd, self.macd_sig), "macd_cross_down": cross_down(self.macd, self.macd_sig),
            "sma20_cross_up_sma50": cross_up(self.sma20, self.sma50),
            "sma20_cross_down_sma50": cross_down(self.sma20, self.sma50),
            "bb_mid": _f(self.bb_mid[i]), "bb_upper": _f(up), "bb_lower": _f(lo_),
            "pct_b": _f((close - lo_) / (up - lo_), 3) if not np.isnan(up) and up != lo_ else None,
            "bb_width_pctile": _f(width_pctile, 1),
            "atr14": atr_v, "atr_pct": _f(atr_v / close * 100, 3) if atr_v else None,
            "adx14": _f(self.adx14[i], 2), "plus_di": _f(self.pdi[i], 2), "minus_di": _f(self.mdi[i], 2),
            "rvol20": _f(self.rvol[i], 2), "avg_dollar_volume20": round(adv20, 0),
            "roc5": _f(self.roc5[i], 2), "roc20": _f(self.roc20[i], 2), "roc63": _f(self.roc63[i], 2),
            "roc126": _f(self.roc126[i], 2),
            "high20_prior": _f(self.hi20[i]), "low20_prior": _f(self.lo20[i]), "high55_prior": _f(self.hi55[i]),
            "low10_prior": _f(self.lo10[i]), "low5": _f(l[max(0, i - 4) : i + 1].min()),
            "high252": _f(high252), "low252": _f(low252), "pct_from_52w_high": _f((close / high252 - 1) * 100, 2),
            "extension_atr_from_sma50": _f((close - s50) / atr_v, 2) if s50 and atr_v else None,
            "trend": trend,
        }
        if with_levels:
            lv = ind.swing_levels(h[: i + 1], l[: i + 1], c[: i + 1])
            prof["support"], prof["resistance"] = lv["support"], lv["resistance"]
        else:
            prof["support"], prof["resistance"] = [], []
        return prof


def technical_profile(bars: list[Bar]) -> dict[str, Any]:
    """Latest-value technical snapshot for daily bars. Uses only the bars given."""
    if len(bars) < 30:
        return {"ok": False, "reason": f"Only {len(bars)} bars available; at least 30 needed", "bars": len(bars)}
    return TechSeries(bars).profile_at(len(bars) - 1)


_REGIME_DESCR = {
    "risk_on": "SPY above rising 50- and 200-day averages: trend-following longs have a tailwind.",
    "neutral": "Mixed signals: SPY trend is not clearly up or down. Be selective, size down.",
    "risk_off": "SPY below its 50- and 200-day averages: long setups face a headwind; capital preservation first.",
    "high_volatility": "Realized volatility is elevated: wider ranges, more gaps, stops hit more often.",
}


class RegimeSeries:
    """Market regime per SPY bar index, with sector relative strength aligned by date."""

    def __init__(self, spy_bars: list[Bar], sector_bars: dict[str, list[Bar]] | None = None) -> None:
        self.bars = spy_bars
        c = np.array([b.c for b in spy_bars], dtype=float)
        self.c = c
        h = np.array([b.h for b in spy_bars], dtype=float)
        l = np.array([b.l for b in spy_bars], dtype=float)  # noqa: E741
        self.sma50, self.sma200 = ind.sma(c, 50), ind.sma(c, 200)
        self.atr = ind.atr(h, l, c, 14) if len(c) else np.array([])
        rets = np.diff(np.log(c)) if len(c) > 1 else np.array([])
        self.rv20 = np.full(len(c), np.nan)
        for i in range(21, len(c)):
            self.rv20[i] = rets[i - 20 : i].std(ddof=1) * np.sqrt(252) * 100
        self.index_by_date = {b.t.date(): i for i, b in enumerate(spy_bars)}
        self.sectors: dict[str, dict[Any, tuple[float, float]]] = {}
        for sym, bars in (sector_bars or {}).items():
            sc = np.array([b.c for b in bars], dtype=float)
            r20, r1 = ind.roc(sc, 20), ind.roc(sc, 1)
            self.sectors[sym] = {b.t.date(): (float(r20[j]), float(r1[j])) for j, b in enumerate(bars)}
        self.roc20 = ind.roc(c, 20)

    def at(self, i: int) -> dict[str, Any]:
        n = len(self.bars)
        if i < 0:
            i += n
        if i + 1 < 60:
            return {"ok": False, "label": "unknown", "reason": "insufficient SPY history"}
        c = self.c
        close = float(c[i])
        s50, s200 = _f(self.sma50[i]), _f(self.sma200[i])
        rv20 = _f(self.rv20[i], 2)
        hist = self.rv20[max(0, i - 251) : i + 1]
        hist = hist[~np.isnan(hist)]
        rv_pctile = float((hist < self.rv20[i]).mean() * 100) if rv20 is not None and len(hist) > 40 else None
        dd = float((close / c[max(0, i - 251) : i + 1].max() - 1) * 100)
        above200, above50 = bool(s200 and close > s200), bool(s50 and close > s50)
        # Absolute AND relative: a high percentile of a calm period is not a high-volatility regime.
        if rv20 is not None and (rv20 > 28 or (rv_pctile is not None and rv_pctile > 90 and rv20 > 20)):
            label = "high_volatility"
        elif above200 and above50 and s50 and s200 and s50 > s200:
            label = "risk_on"
        elif not above200 and not above50:
            label = "risk_off"
        else:
            label = "neutral"
        d = self.bars[i].t.date()
        spy_r20 = _f(self.roc20[i], 2) or 0.0
        sectors = []
        for sym, by_date in self.sectors.items():
            v = by_date.get(d)
            if v and not np.isnan(v[0]):
                sectors.append({"symbol": sym, "roc20": round(v[0], 2), "change_pct": round(v[1], 2),
                                "rel_strength_vs_spy": round(v[0] - spy_r20, 2)})
        sectors.sort(key=lambda s: -s["rel_strength_vs_spy"])
        for k, s in enumerate(sectors):
            s["rank"] = k + 1
        atr = _f(self.atr[i]) if len(self.atr) else None
        return {"ok": True, "label": label, "description": _REGIME_DESCR[label], "as_of": self.bars[i].t.isoformat(),
                "spy_close": round(close, 2), "spy_sma50": _f(s50, 2), "spy_sma200": _f(s200, 2),
                "spy_above_200": above200, "spy_above_50": above50, "realized_vol20": rv20,
                "realized_vol_pctile_1y": _f(rv_pctile, 1), "drawdown_from_52w_high_pct": round(dd, 2),
                "spy_roc20": round(spy_r20, 2), "spy_atr_pct": _f(atr / close * 100, 3) if atr else None,
                "sectors": sectors}

    def at_date(self, d: Any) -> dict[str, Any]:
        i = self.index_by_date.get(d)
        if i is None:
            # last SPY bar on or before d
            prior = [k for k in self.index_by_date if k <= d]
            if not prior:
                return {"ok": False, "label": "unknown"}
            i = self.index_by_date[max(prior)]
        return self.at(i)


def market_regime(spy_bars: list[Bar], sector_bars: dict[str, list[Bar]] | None = None) -> dict[str, Any]:
    if len(spy_bars) < 60:
        return {"ok": False, "label": "unknown", "reason": "insufficient SPY history"}
    return RegimeSeries(spy_bars, sector_bars).at(len(spy_bars) - 1)

