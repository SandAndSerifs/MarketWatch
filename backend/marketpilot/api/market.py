"""Market data, charts, search, stock analysis."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query

from ..analysis import indicators as ind
from ..data import calendar as cal
from ..data.models import TIMEFRAMES
from ..data.providers.base import NotSupported, ProviderError
from ..data.universe import INDEX_PROXIES, SECTOR_ETFS
from ..db import session_scope
from ..events.calendar import upcoming_events
from ..services.analysis import completed_daily_bars
from ..services.runtime import Runtime
from .deps import rt

router = APIRouter(prefix="/api/market", tags=["market"])

_DEFAULT_DAYS = {"1Min": 2, "5Min": 7, "15Min": 20, "1Hour": 90, "1Day": 550}


def _clean(a: np.ndarray) -> list[float | None]:
    return [None if np.isnan(x) else round(float(x), 4) for x in a]


@router.get("/status")
async def market_status() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    st = cal.market_status(now)
    d = cal.et_date(now)
    hol = []
    for y in (d.year, d.year + 1):
        hol += [{"date": k.isoformat(), "name": v} for k, v in sorted(cal.holidays(y).items()) if k >= d]
    st["upcoming_holidays"] = hol[:8]
    st["upcoming_early_closes"] = [{"date": k.isoformat(), "name": v} for y in (d.year, d.year + 1)
                                   for k, v in sorted(cal.early_closes(y).items()) if k >= d][:4]
    return st


@router.get("/overview")
async def overview(r: Runtime = Depends(rt)) -> dict[str, Any]:
    syms = list(INDEX_PROXIES) + list(SECTOR_ETFS)
    snaps = await r.md.get_snapshots(syms)
    out: dict[str, Any] = {
        "quality": r.md.provider.quality().to_dict(),
        "indices": [{"symbol": k, "label": v, **(snaps[k].to_dict() if k in snaps else {})} for k, v in INDEX_PROXIES.items()],
        "sectors": sorted([{"symbol": k, "name": v, **(snaps[k].to_dict() if k in snaps else {})} for k, v in SECTOR_ETFS.items()],
                          key=lambda x: -(x.get("change_pct") or -999)),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
    try:
        out["regime"] = await r.analysis.regime()
    except ProviderError as e:
        out["regime"] = {"ok": False, "error": str(e)}
    return out


@router.get("/movers")
async def movers(top: int = 10, r: Runtime = Depends(rt)) -> dict[str, Any]:
    res: dict[str, Any] = {"quality": r.md.provider.quality().to_dict()}
    try:
        mv = await r.md._call(r.md.provider.get_movers(top))
        res.update({"gainers": [m.to_dict() for m in mv["gainers"]], "losers": [m.to_dict() for m in mv["losers"]],
                    "as_of": mv.get("as_of")})
    except NotSupported as e:
        res["movers_error"] = str(e)
    try:
        act = await r.md._call(r.md.provider.get_most_active(20))
        res["most_active"] = [m.to_dict() for m in act]
    except (NotSupported, ProviderError) as e:
        res["most_active_error"] = str(e)
    return res


@router.get("/unusual")
async def unusual(r: Runtime = Depends(rt)) -> dict[str, Any]:
    """Unusual volume/volatility across the scanner universe (time-of-day adjusted relative volume)."""
    uni = r.scanner.universe()
    now = datetime.now(timezone.utc)
    snaps, daily = await asyncio.gather(r.md.get_snapshots(uni), r.analysis.daily_multi(uni, now))
    st = cal.session_times(cal.et_date(now))
    frac = 1.0
    if st and st.open < now < st.close:
        frac = max(0.05, (now - st.open).total_seconds() / (st.close - st.open).total_seconds())
    rows = []
    for sym, sn in snaps.items():
        bars = daily.get(sym) or []
        if len(bars) < 21 or not sn.day_volume:
            continue
        avg_v = float(np.mean([b.v for b in bars[-20:]]))
        rets = np.diff(np.log([b.c for b in bars[-21:]]))
        sd = float(rets.std(ddof=1)) * 100
        rvol = (sn.day_volume / frac) / avg_v if avg_v else None
        z = (sn.change_pct or 0) / sd if sd else None
        rows.append({"symbol": sym, "price": sn.last_price, "change_pct": sn.change_pct, "rvol_time_adjusted": round(rvol, 2) if rvol else None,
                     "move_zscore": round(z, 2) if z is not None else None, "feed": sn.feed})
    rows.sort(key=lambda x: -max(abs(x["move_zscore"] or 0), (x["rvol_time_adjusted"] or 0) - 1))
    return {"rows": rows[:30], "session_fraction": round(frac, 3),
            "caveats": ["Live volume on the IEX feed is single-venue while the 20-day average uses consolidated history; "
                        "relative volume is therefore understated on IEX. Treat as directional only.",
                        "Time-of-day adjustment is linear; real volume is U-shaped (heavier at open/close)."]
            if r.md.provider.quality().feed == "iex" else ["Time-of-day adjustment is linear."]}


@router.get("/quote/{symbol}")
async def quote(symbol: str, r: Runtime = Depends(rt)) -> dict[str, Any]:
    snaps = await r.md.get_snapshots([symbol.upper()])
    if symbol.upper() not in snaps:
        raise HTTPException(404, f"No snapshot for {symbol}")
    r.md.watch([symbol.upper()])
    return {"quality": r.md.provider.quality().to_dict(), "snapshot": snaps[symbol.upper()].to_dict()}


@router.get("/bars/{symbol}")
async def bars(symbol: str, timeframe: str = "1Day", days: int | None = None, r: Runtime = Depends(rt)) -> dict[str, Any]:
    if timeframe not in TIMEFRAMES:
        raise HTTPException(400, f"timeframe must be one of {TIMEFRAMES}")
    lookback = timedelta(days=days or _DEFAULT_DAYS[timeframe])
    data = await r.md.get_bars(symbol.upper(), timeframe, lookback)
    now = datetime.now(timezone.utc)
    partial = timeframe == "1Day" and len(completed_daily_bars(data, now)) < len(data)
    c = np.array([b.c for b in data], dtype=float)
    overlays: dict[str, Any] = {}
    if len(c):
        overlays = {"sma20": _clean(ind.sma(c, 20)), "sma50": _clean(ind.sma(c, 50)), "sma200": _clean(ind.sma(c, 200)),
                    "ema20": _clean(ind.ema(c, 20))}
        _, up, lo = ind.bollinger(c, 20, 2.0)
        overlays["bb_upper"], overlays["bb_lower"] = _clean(up), _clean(lo)
        overlays["rsi14"] = _clean(ind.rsi(c, 14))
        m, sgn, hist = ind.macd(c)
        overlays["macd"], overlays["macd_signal"], overlays["macd_hist"] = _clean(m), _clean(sgn), _clean(hist)
        if timeframe != "1Day":
            overlays["vwap"] = _clean(ind.session_vwap([b.t for b in data], [b.h for b in data], [b.l for b in data],
                                                       c, [b.v for b in data]))
    return {"symbol": symbol.upper(), "timeframe": timeframe, "bars": [b.to_dict() for b in data], "overlays": overlays,
            "last_bar_partial": partial,
            "source": "Alpaca consolidated (SIP) history, delayed >=15 min on free plan" if r.md.provider.name == "alpaca"
            else r.md.provider.quality().label}


@router.get("/search")
async def search(q: str = Query(..., min_length=1), r: Runtime = Depends(rt)) -> list[dict[str, Any]]:
    assets = await r.md._call(r.md.provider.list_assets())
    ql = q.upper().strip()
    exact = [a for a in assets if a.symbol == ql]
    starts = [a for a in assets if a.symbol.startswith(ql) and a.symbol != ql]
    names = [a for a in assets if ql.lower() in a.name.lower() and not a.symbol.startswith(ql)]
    return [a.to_dict() for a in (exact + sorted(starts, key=lambda a: len(a.symbol)) + names)[:20]]


@router.get("/news")
async def news(symbols: str | None = None, limit: int = 30, r: Runtime = Depends(rt)) -> dict[str, Any]:
    syms = [s.strip().upper() for s in symbols.split(",")] if symbols else None
    try:
        items = await r.md._call(r.md.provider.get_news(syms, limit))
    except NotSupported as e:
        return {"items": [], "error": str(e)}
    return {"items": [n.to_dict() for n in items], "source": r.md.provider.name}


@router.get("/analysis/{symbol}")
async def stock_analysis(symbol: str, r: Runtime = Depends(rt)) -> dict[str, Any]:
    from ..ai.tools import AnalystTools
    from ..analysis.technicals import technical_profile

    sym = symbol.upper()
    now = datetime.now(timezone.utc)
    daily = await r.analysis.daily(sym, now)
    snaps = await r.md.get_snapshots([sym])
    r.md.watch([sym])
    setups = await AnalystTools(r).t_evaluate_setups(sym)
    with session_scope() as s:
        events = upcoming_events(s, [sym], cal.et_date(now), 30)
    news_items = await r.analysis.news(sym)
    return {"symbol": sym, "quality": r.md.provider.quality().to_dict(),
            "snapshot": snaps[sym].to_dict() if sym in snaps else None,
            "technicals": technical_profile(daily), "regime": await r.analysis.regime(), "events": events,
            "news": [n.to_dict() for n in news_items], "setups": setups["results"]}
