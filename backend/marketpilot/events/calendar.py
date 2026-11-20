"""Economic-release and earnings calendar.

Macro dates below were checked against the official publishers on 2026-11-20:
  * FOMC: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm (page fetched directly;
    2027 schedule as revised on 2026-11-12). Decisions are announced 14:00 ET on the second day.
    The Oct 26-27 2027 meeting is a strategy-only meeting with no policy decision.
  * CPI / Employment Situation: BLS release schedules (https://www.bls.gov/schedule/), 08:30 ET.
Only dates that were verified are seeded; add others in the UI (Settings > Events) or via
POST /api/events, always with a source. Earnings dates come from Finnhub when FINNHUB_API_KEY
is set; without it, earnings dates are reported as *unverified* in every checklist.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import AppSetting, MarketEvent

log = logging.getLogger(__name__)

FED = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_CPI = "https://www.bls.gov/schedule/news_release/cpi.htm"
BLS_EMP = "https://www.bls.gov/schedule/news_release/empsit.htm"
VERIFIED = "2026-11-20"

SEED_MACRO: list[dict[str, Any]] = [
    # FOMC decisions (second meeting day)
    *[{"name": "FOMC rate decision", "date": d, "time_et": "14:00", "importance": "high", "source": "Federal Reserve",
       "source_url": FED} for d in ("2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
                                     "2027-07-28", "2027-09-15", "2027-11-17")],
    {"name": "FOMC strategy meeting (no policy decision scheduled)", "date": "2027-10-27", "time_et": None,
     "importance": "medium", "source": "Federal Reserve", "source_url": FED},
    # CPI
    *[{"name": f"CPI ({ref})", "date": d, "time_et": "08:30", "importance": "high", "source": "BLS", "source_url": BLS_CPI}
      for d, ref in (("2026-12-10", "Nov 2026"), ("2027-01-13", "Dec 2026"), ("2027-02-11", "Jan 2027"))],
    # Employment Situation (nonfarm payrolls)
    *[{"name": f"Employment Situation / NFP ({ref})", "date": d, "time_et": "08:30", "importance": "high", "source": "BLS",
       "source_url": BLS_EMP} for d, ref in (("2026-12-04", "Nov 2026"), ("2027-01-08", "Dec 2026"),
                                              ("2027-04-02", "Mar 2027"), ("2027-07-02", "Jun 2027"))],
]


def seed_macro_events(s: Session) -> int:
    n = 0
    for ev in SEED_MACRO:
        exists = s.execute(select(MarketEvent).where(MarketEvent.kind == "macro", MarketEvent.name == ev["name"],
                                                     MarketEvent.date == ev["date"])).scalar_one_or_none()
        if exists is None:
            s.add(MarketEvent(kind="macro", symbol="*", verified_at=VERIFIED, **ev))
            n += 1
    return n


def event_to_dict(e: MarketEvent) -> dict[str, Any]:
    return {"id": e.id, "kind": e.kind, "symbol": e.symbol, "name": e.name, "date": e.date, "time_et": e.time_et,
            "importance": e.importance, "source": e.source, "source_url": e.source_url, "verified_at": e.verified_at,
            "details": e.details}


def upcoming_events(s: Session, symbols: list[str] | None, start: date, days: int = 14) -> list[dict[str, Any]]:
    end = start + timedelta(days=days)
    q = select(MarketEvent).where(MarketEvent.date >= start.isoformat(), MarketEvent.date <= end.isoformat())
    rows = s.execute(q.order_by(MarketEvent.date, MarketEvent.time_et)).scalars().all()
    syms = {x.upper() for x in symbols} if symbols else None
    return [event_to_dict(e) for e in rows if e.kind == "macro" or syms is None or e.symbol in syms]


def earnings_coverage_ok(s: Session) -> bool:
    row = s.get(AppSetting, "earnings_refresh")
    if not row:
        return False
    last = datetime.fromisoformat(row.value.get("last_success", "1970-01-01T00:00:00+00:00"))
    return datetime.now(timezone.utc) - last < timedelta(hours=36)


async def refresh_earnings_finnhub(s: Session, api_key: str, symbols: list[str], days: int = 30,
                                   client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Pull the earnings calendar for the next `days` and upsert events for `symbols`."""
    today = datetime.now(timezone.utc).date()
    params = {"from": today.isoformat(), "to": (today + timedelta(days=days)).isoformat(), "token": api_key}
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        r = await client.get("https://finnhub.io/api/v1/calendar/earnings", params=params)
        r.raise_for_status()
        rows = r.json().get("earningsCalendar") or []
    finally:
        if own:
            await client.aclose()
    wanted = {x.upper() for x in symbols}
    n = 0
    hour_map = {"bmo": "bmo", "amc": "amc", "dmh": "dmh"}
    for row in rows:
        sym = (row.get("symbol") or "").upper()
        if sym not in wanted or not row.get("date"):
            continue
        name = f"Earnings Q{row.get('quarter')} {row.get('year')}"
        ev = s.execute(select(MarketEvent).where(MarketEvent.kind == "earnings", MarketEvent.symbol == sym,
                                                 MarketEvent.name == name)).scalar_one_or_none()
        details = {"eps_estimate": row.get("epsEstimate"), "revenue_estimate": row.get("revenueEstimate"),
                   "eps_actual": row.get("epsActual")}
        if ev is None:
            s.add(MarketEvent(kind="earnings", symbol=sym, name=name, date=row["date"],
                              time_et=hour_map.get(row.get("hour") or "", None), importance="high", source="Finnhub",
                              source_url="https://finnhub.io/docs/api/earnings-calendar", verified_at=today.isoformat(),
                              details=details))
            n += 1
        else:
            ev.date, ev.time_et, ev.details, ev.verified_at = row["date"], hour_map.get(row.get("hour") or "", None), details, today.isoformat()
    setting = s.get(AppSetting, "earnings_refresh") or AppSetting(key="earnings_refresh", value={})
    setting.value = {"last_success": datetime.now(timezone.utc).isoformat(), "rows": len(rows), "upserted": n}
    s.merge(setting)
    return {"fetched": len(rows), "new": n}
