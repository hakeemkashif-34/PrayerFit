"""KMA's real MAWAQIT page from November 3, 2026, after it fixed Isha at 19:40.

From October 31 every read of this page failed with "2026-11-05 isha
iqamah is more than 90 minutes after adhan", so Settings said KMA's
times couldn't be confirmed. The expected times below were read off the
saved page by hand. It covers the week the clocks fell back (November 1).
"""

from datetime import date, time
from pathlib import Path

from app.masjid_times.mawaqit import conf_data, days_from

PAGE = (Path(__file__).parent / "fixtures" / "mawaqit" / "kma_page_2026-11-03.html").read_text(encoding="utf-8")
DATA = conf_data(PAGE)


def day(local_date: date):
    return days_from(DATA, local_date, 1)[0]


def test_every_day_from_october_25_reads_through_the_clock_change():
    # The 30 days a read saves, starting the Sunday before the clocks fell back.
    days = days_from(DATA, date(2026, 10, 25), 30)
    assert [d.local_date for d in days] == [date(2026, 10, 25 + n) for n in range(7)] + [
        date(2026, 11, n) for n in range(1, 24)
    ]


def test_saturday_before_the_clocks_fall_back():
    saturday = day(date(2026, 10, 31))
    assert saturday.adhan["isha"] == time(19, 15)
    assert saturday.iqamah["isha"] == time(20, 40)


def test_sunday_the_clocks_fall_back():
    sunday = day(date(2026, 11, 1))
    assert sunday.adhan == {
        "fajr": time(5, 20), "dhuhr": time(11, 47), "asr": time(14, 27), "maghrib": time(16, 51), "isha": time(18, 14),
    }
    assert sunday.iqamah == {
        "fajr": time(5, 50), "dhuhr": time(12, 30), "asr": time(15, 15), "maghrib": time(16, 56), "isha": time(19, 40),
    }


def test_november_5_isha_is_91_minutes_after_adhan():
    thursday = day(date(2026, 11, 5))
    assert thursday.adhan["isha"] == time(18, 9)
    assert thursday.iqamah["isha"] == time(19, 40)


def test_the_widest_isha_gap_this_year_is_under_150_minutes():
    # Every day of the year passes, so the read won't break again this winter.
    days = days_from(DATA, date(2026, 1, 1), 365)
    assert len(days) == 365
    widest = max(
        d.iqamah["isha"].hour * 60 + d.iqamah["isha"].minute - d.adhan["isha"].hour * 60 - d.adhan["isha"].minute
        for d in days
        if d.iqamah["isha"] is not None
    )
    assert 90 < widest <= 150
