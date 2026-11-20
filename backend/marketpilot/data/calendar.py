"""NYSE/Nasdaq exchange calendar: holidays, early closes, sessions and DST.

All exchange times are defined in America/New_York and converted with zoneinfo,
so daylight-saving transitions are handled by the tz database rather than by
hand-maintained offsets.

Rules implemented (NYSE Rule 7.2 holidays):
  New Year's Day (Sat -> not observed, Sun -> Mon), MLK Day, Washington's
  Birthday, Good Friday, Memorial Day, Juneteenth (from 2022), Independence
  Day, Labor Day, Thanksgiving, Christmas (Sat -> Fri, Sun -> Mon).
Early closes (13:00 ET): July 3 when it falls Mon-Thu, the day after
Thanksgiving, and Dec 24 when it falls Mon-Thu.
Unscheduled closures (national days of mourning, weather) are listed in
SPECIAL_CLOSURES and can be extended through `extra_closures`.
When an Alpaca key is configured, `services.market_clock` cross-checks this
calendar against Alpaca's /v2/calendar and logs any disagreement.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

PREMARKET_OPEN = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
AFTERHOURS_CLOSE = time(20, 0)

SPECIAL_CLOSURES: dict[date, str] = {
    date(2001, 9, 11): "September 11 attacks",
    date(2001, 9, 12): "September 11 attacks",
    date(2001, 9, 13): "September 11 attacks",
    date(2001, 9, 14): "September 11 attacks",
    date(2004, 6, 11): "National Day of Mourning (Reagan)",
    date(2007, 1, 2): "National Day of Mourning (Ford)",
    date(2012, 10, 29): "Hurricane Sandy",
    date(2012, 10, 30): "Hurricane Sandy",
    date(2018, 12, 5): "National Day of Mourning (G.H.W. Bush)",
    date(2025, 1, 9): "National Day of Mourning (Carter)",
}


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date, saturday_to_friday: bool = True) -> date | None:
    if d.weekday() == 5:
        return d - timedelta(days=1) if saturday_to_friday else None
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=64)
def holidays(year: int) -> dict[date, str]:
    out: dict[date, str] = {}

    def add(d: date | None, name: str) -> None:
        if d is not None and d.year == year:
            out[d] = name

    add(_observed(date(year, 1, 1), saturday_to_friday=False), "New Year's Day")
    if year >= 1998:
        add(_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day")
    add(_nth_weekday(year, 2, 0, 3), "Washington's Birthday")
    add(easter_sunday(year) - timedelta(days=2), "Good Friday")
    add(_last_weekday(year, 5, 0), "Memorial Day")
    if year >= 2022:
        add(_observed(date(year, 6, 19)), "Juneteenth")
    add(_observed(date(year, 7, 4)), "Independence Day")
    add(_nth_weekday(year, 9, 0, 1), "Labor Day")
    add(_nth_weekday(year, 11, 3, 4), "Thanksgiving Day")
    add(_observed(date(year, 12, 25)), "Christmas Day")
    for d, name in SPECIAL_CLOSURES.items():
        if d.year == year:
            out[d] = name
    return out


@lru_cache(maxsize=64)
def early_closes(year: int) -> dict[date, str]:
    out: dict[date, str] = {}
    hol = holidays(year)
    jul3 = date(year, 7, 3)
    if jul3.weekday() <= 3 and jul3 not in hol:
        out[jul3] = "Day before Independence Day"
    out[_nth_weekday(year, 11, 3, 4) + timedelta(days=1)] = "Day after Thanksgiving"
    dec24 = date(year, 12, 24)
    if dec24.weekday() <= 3 and dec24 not in hol:
        out[dec24] = "Christmas Eve"
    return out


extra_closures: dict[date, str] = {}


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year) and d not in extra_closures


def holiday_name(d: date) -> str | None:
    return holidays(d.year).get(d) or extra_closures.get(d)


def next_trading_day(d: date) -> date:
    n = d + timedelta(days=1)
    while not is_trading_day(n):
        n += timedelta(days=1)
    return n


def previous_trading_day(d: date) -> date:
    p = d - timedelta(days=1)
    while not is_trading_day(p):
        p -= timedelta(days=1)
    return p


def trading_days_between(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


@dataclass(frozen=True)
class SessionTimes:
    day: date
    premarket_open: datetime
    open: datetime
    close: datetime
    afterhours_close: datetime
    early_close: bool


def session_times(d: date) -> SessionTimes | None:
    if not is_trading_day(d):
        return None
    early = d in early_closes(d.year)
    close_t = EARLY_CLOSE if early else REGULAR_CLOSE
    ah_close = time(17, 0) if early else AFTERHOURS_CLOSE

    def at(t: time) -> datetime:
        return datetime.combine(d, t, tzinfo=ET).astimezone(UTC)

    return SessionTimes(d, at(PREMARKET_OPEN), at(REGULAR_OPEN), at(close_t), at(ah_close), early)


def to_et(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError("naive datetime")
    return ts.astimezone(ET)


def et_date(ts: datetime) -> date:
    return to_et(ts).date()


# Session phases used by the scheduler and alert system.
PHASES = ("closed", "premarket", "opening", "intraday", "power_hour", "afterhours")


def session_phase(now: datetime) -> str:
    st = session_times(et_date(now))
    if st is None:
        return "closed"
    if now < st.premarket_open:
        return "closed"
    if now < st.open:
        return "premarket"
    if now < st.open + timedelta(minutes=30):
        return "opening"
    if now < st.close - timedelta(hours=1):
        return "intraday"
    if now < st.close:
        return "power_hour"
    if now < st.afterhours_close:
        return "afterhours"
    return "closed"


def is_regular_session(now: datetime) -> bool:
    return session_phase(now) in ("opening", "intraday", "power_hour")


def market_status(now: datetime) -> dict[str, object]:
    d = et_date(now)
    st = session_times(d)
    phase = session_phase(now)
    nxt = st if (st and now < st.open) else session_times(next_trading_day(d))
    return {
        "now_utc": now.isoformat(),
        "now_et": to_et(now).isoformat(),
        "phase": phase,
        "is_open": phase in ("opening", "intraday", "power_hour"),
        "trading_day": st is not None,
        "holiday": holiday_name(d),
        "early_close": bool(st and st.early_close),
        "today_open": st.open.isoformat() if st else None,
        "today_close": st.close.isoformat() if st else None,
        "next_open": nxt.open.isoformat() if nxt else None,
    }
