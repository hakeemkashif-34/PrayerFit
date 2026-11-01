"""The parser against BIC's real MAWAQIT page, saved on November 1, 2026.

fixtures/mawaqit/bic_page.html is the real page (https://mawaqit.net/en/id/17559)
trimmed to its timetable data. Tests only read this saved copy, never the
real site. The expected times below were read off the saved page.

BIC publishes 2 Jumuah times: 1:00 pm and 2:30 pm.
"""

from datetime import date, time
from pathlib import Path

from app.masjid_times.mawaqit import conf_data, days_from, external_id_from_link
from app.masjid_times.source import JumuahTime
from app.masjid_times.validate import check_day

PAGE = (Path(__file__).parent / "fixtures" / "mawaqit" / "bic_page.html").read_text(encoding="utf-8")
DATA = conf_data(PAGE)


def day(local_date: date):
    return days_from(DATA, local_date, 1)[0]


def test_bics_share_link():
    assert external_id_from_link("https://mawaqit.net/en/id/17559") == "id/17559"
    assert DATA["name"] == "Barrhaven Islamic Centre"
    assert DATA["timezone"] == "America/Toronto"


def test_adhan_and_iqamah_on_november_1_the_day_the_clocks_go_back():
    sunday = day(date(2026, 11, 1))
    assert sunday.adhan == {
        "fajr": time(5, 19), "dhuhr": time(11, 46), "asr": time(14, 26), "maghrib": time(16, 50), "isha": time(18, 13),
    }
    # Maghrib's "+5" is 5 minutes after adhan. The rest are clock times.
    assert sunday.iqamah == {
        "fajr": time(6, 0), "dhuhr": time(12, 30), "asr": time(15, 0), "maghrib": time(16, 55), "isha": time(19, 0),
    }
    assert sunday.jumuah == ()


def test_the_page_has_the_clocks_going_back():
    # Clock times as the masjid publishes them. Dhuhr is an hour earlier on Nov 1 than on Oct 30.
    assert day(date(2026, 10, 30)).adhan["dhuhr"] == time(12, 47)
    assert day(date(2026, 11, 1)).adhan["dhuhr"] == time(11, 46)
    assert day(date(2026, 3, 8)).adhan["dhuhr"] == time(13, 14)


def test_both_jumuah_times_are_read():
    # jumua3 is empty on BIC's page, so there are 2 slots, numbered 1 and 2.
    friday = day(date(2026, 11, 6))
    assert friday.jumuah == (JumuahTime(1, time(13, 0)), JumuahTime(2, time(14, 30)))
    assert friday.adhan["dhuhr"] == time(11, 47)


def test_every_day_of_the_year_passes_the_checks():
    # One bad value would reject the whole read, so the saved page must have none.
    for each in days_from(DATA, date(2026, 1, 1), 365):
        check_day(each)
