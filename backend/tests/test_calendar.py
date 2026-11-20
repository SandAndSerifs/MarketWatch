from datetime import date, datetime, timezone

from marketpilot.data import calendar as cal


def test_nyse_holidays_2026_match_published_schedule():
    expected = {date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
                date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25)}
    assert set(cal.holidays(2026)) == expected


def test_nyse_holidays_2025_include_carter_day_of_mourning():
    h = cal.holidays(2025)
    assert date(2025, 1, 9) in h
    assert date(2025, 4, 18) in h  # Good Friday
    assert date(2025, 7, 4) in h


def test_nyse_holidays_2027_weekend_observance():
    h = cal.holidays(2027)
    assert date(2027, 1, 1) in h          # Friday
    assert date(2027, 3, 26) in h         # Good Friday (Easter Mar 28)
    assert date(2027, 6, 18) in h         # Juneteenth Sat -> Fri
    assert date(2027, 7, 5) in h          # Independence Day Sun -> Mon
    assert date(2027, 12, 24) in h        # Christmas Sat -> Fri


def test_new_year_on_saturday_is_not_observed_on_friday():
    assert date(2021, 12, 31) not in cal.holidays(2021)
    assert cal.is_trading_day(date(2021, 12, 31))


def test_early_closes():
    assert set(cal.early_closes(2026)) == {date(2026, 11, 27), date(2026, 12, 24)}
    assert set(cal.early_closes(2025)) == {date(2025, 7, 3), date(2025, 11, 28), date(2025, 12, 24)}
    st = cal.session_times(date(2026, 11, 27))
    assert st and st.early_close and st.close == datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc)


def test_dst_transition_changes_utc_open():
    # US DST began 2026-03-08: open is 14:30Z before, 13:30Z after.
    assert cal.session_times(date(2026, 3, 6)).open == datetime(2026, 3, 6, 14, 30, tzinfo=timezone.utc)
    assert cal.session_times(date(2026, 3, 9)).open == datetime(2026, 3, 9, 13, 30, tzinfo=timezone.utc)
    # DST ended 2026-11-01
    assert cal.session_times(date(2026, 10, 30)).open == datetime(2026, 10, 30, 13, 30, tzinfo=timezone.utc)
    assert cal.session_times(date(2026, 11, 2)).open == datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)


def test_session_phases():
    d = date(2026, 11, 18)
    def at(h, m):
        return datetime(2026, 11, 18, h, m, tzinfo=timezone.utc)
    assert cal.session_phase(at(8, 0)) == "closed"        # 03:00 ET
    assert cal.session_phase(at(10, 0)) == "premarket"    # 05:00 ET
    assert cal.session_phase(at(14, 45)) == "opening"     # 09:45 ET
    assert cal.session_phase(at(17, 0)) == "intraday"     # 12:00 ET
    assert cal.session_phase(at(20, 30)) == "power_hour"  # 15:30 ET
    assert cal.session_phase(at(22, 0)) == "afterhours"   # 17:00 ET
    assert cal.session_phase(datetime(2026, 11, 26, 16, 0, tzinfo=timezone.utc)) == "closed"  # Thanksgiving
    assert cal.is_trading_day(d)


def test_next_and_previous_trading_day():
    assert cal.next_trading_day(date(2026, 11, 25)) == date(2026, 11, 27)
    assert cal.previous_trading_day(date(2026, 11, 30)) == date(2026, 11, 27)
