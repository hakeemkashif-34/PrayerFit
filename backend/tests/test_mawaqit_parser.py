"""Reading times from a MAWAQIT page's data, with made-up pages.

test_mawaqit_kma.py checks the same code against KMA's real saved page.
"""

from datetime import date, time

import pytest

from app.masjid_times.mawaqit import conf_data, days_from
from app.masjid_times.source import JumuahTime, SourceInvalid, next_friday
from tests.mawaqit_pages import conf, page, set_day

FRIDAY = date(2026, 10, 30)
SATURDAY = date(2026, 10, 31)


def read(data: dict, today: date = date(2026, 10, 25), days: int = 14):
    return days_from(conf_data(page(data)), today, days)


def test_reads_adhan_iqamah_and_jumuah():
    days = read(conf())
    assert len(days) == 14
    first = days[0]
    assert first.local_date == date(2026, 10, 25)
    assert first.adhan == {
        "fajr": time(5, 30), "dhuhr": time(12, 30), "asr": time(15, 30), "maghrib": time(18, 0), "isha": time(19, 30),
    }
    assert first.iqamah["isha"] == time(20, 15)  # a clock time
    assert first.iqamah["fajr"] == time(5, 50)  # "+20" after 05:30
    assert first.iqamah["dhuhr"] == time(13, 0)
    assert first.jumuah == ()  # Sunday
    friday = next(d for d in days if d.local_date == FRIDAY)
    assert friday.jumuah == (JumuahTime(1, time(13, 30)), JumuahTime(2, time(14, 30)))


def test_iqamah_as_minutes_after_adhan_uses_that_days_adhan():
    data = set_day(conf(), 10, 26, times=["05:31", "07:01", "12:30", "15:28", "17:58", "19:29"],
                   iqamah=["+15", "+10", "+10", "+10", "+10"])
    monday = read(data)[1]
    assert monday.iqamah == {
        "fajr": time(5, 46), "dhuhr": time(12, 40), "asr": time(15, 38), "maghrib": time(18, 8), "isha": time(19, 39),
    }


def test_missing_iqamah_stays_missing():
    data = set_day(conf(), 10, 25, iqamah=["", "13:00", "+10", "-", "20:15"])
    first = read(data)[0]
    assert first.iqamah["fajr"] is None
    assert first.iqamah["maghrib"] is None
    assert first.iqamah["dhuhr"] == time(13, 0)


def test_no_published_iqamah_means_none_at_all():
    days = read(conf(iqamaEnabled=False))
    assert all(v is None for d in days for v in d.iqamah.values())


def test_a_masjid_with_no_jumuah():
    days = read(conf(jumua=None, jumua2=None))
    assert all(d.jumuah == () for d in days)


def test_months_and_dates_come_from_local_dates():
    data = set_day(conf(), 11, 1, times=["06:31", "07:40", "11:52", "14:30", "16:56", "18:20"],
                   iqamah=["+20", "+10", "+10", "+10", "+10"])
    days = read(data, today=date(2026, 10, 31), days=2)
    assert [d.local_date for d in days] == [SATURDAY, date(2026, 11, 1)]
    assert days[1].adhan["maghrib"] == time(16, 56)


@pytest.mark.parametrize(
    "times, iqamah, reason",
    [
        (["25:00", "07:00", "12:30", "15:30", "18:00", "19:30"], None, "isn't a clock time"),
        (["5:3", "07:00", "12:30", "15:30", "18:00", "19:30"], None, "isn't a clock time"),
        (["05:30", "07:00", "12:30", "15:30", "18:00"], None, "no times"),  # Isha missing
        (["05:30", "07:00", "12:30", "15:30", "18:00", None], None, "isn't a clock time"),
        (["05:30", "07:00", "12:30", "11:00", "18:00", "19:30"], None, "out of order"),
        (None, ["+20", "12:00", "+10", "+5", "20:15"], "before adhan"),
        (None, ["+20", "13:00", "+10", "+5", "21:15"], "more than 90 minutes"),
        (None, ["+91", "13:00", "+10", "+5", "20:15"], "more than 90 minutes"),
        (None, ["+20", "13:00", "+10", "+5"], "isn't 5 values"),
        (None, ["soon", "13:00", "+10", "+5", "20:15"], "isn't a clock time"),
    ],
)
def test_impossible_times_reject_the_whole_page(times, iqamah, reason):
    data = set_day(conf(), 10, 27, times=times, iqamah=iqamah)
    with pytest.raises(SourceInvalid, match=reason):
        read(data)


def test_a_missing_day_rejects_the_page():
    data = conf()
    del data["calendar"][9]["28"]
    with pytest.raises(SourceInvalid, match="no times"):
        read(data)


def test_missing_months_reject_the_page():
    data = conf()
    data["calendar"] = data["calendar"][:11]
    with pytest.raises(SourceInvalid, match="12 months"):
        read(data)


def test_bad_jumuah_rejects_the_page():
    with pytest.raises(SourceInvalid):
        read(conf(jumua="1:30 pm"))


def test_isha_iqamah_past_midnight_is_refused():
    data = set_day(conf(), 10, 25, times=["05:30", "07:00", "12:30", "15:30", "18:00", "23:50"],
                   iqamah=["+20", "13:00", "+10", "+5", "+15"])
    with pytest.raises(SourceInvalid, match="after midnight"):
        read(data)


@pytest.mark.parametrize(
    "html",
    [
        "<html><body>No data here</body></html>",
        "<script>var confData = {'calendar': []};</script>",  # JavaScript, not JSON
        "<script>var confData = [1, 2, 3];</script>",
        "<script>var confData = {\"calendar\": \"nope\"};</script>",
    ],
)
def test_a_changed_page_format_is_rejected(html):
    with pytest.raises(SourceInvalid):
        days_from(conf_data(html), date(2026, 10, 25), 14)


def test_the_page_script_is_only_read_as_data():
    # The made-up page has a script that would redirect if it were run.
    html = page(conf())
    assert "never-run" in html
    assert conf_data(html)["name"] == "Test Masjid"


def test_plus_zero_is_iqamah_at_the_adhan_time():
    data = set_day(conf(), 10, 25, iqamah=["+15", "13:00", "+0", "+5", "+0"])
    first = read(data)[0]
    assert first.iqamah["asr"] == first.adhan["asr"] == time(15, 30)
    assert first.iqamah["isha"] == first.adhan["isha"] == time(19, 30)
    assert first.iqamah["maghrib"] == time(18, 5)


@pytest.mark.parametrize("value", [0, 15, "15", True])
def test_fajr_tied_to_sunrise_means_no_fajr_iqamah(value):
    days = read(conf(fajrFixationComparedToShuruq=value))
    assert all(d.iqamah["fajr"] is None for d in days)
    # The other prayers keep their iqamah.
    assert days[0].iqamah["isha"] == time(20, 15)


@pytest.mark.parametrize("value", [None, "", False])
def test_fajr_tied_to_sunrise_off_keeps_fajr_iqamah(value):
    assert read(conf(fajrFixationComparedToShuruq=value))[0].iqamah["fajr"] == time(5, 50)


def test_fajr_tied_to_sunrise_is_logged(http, fake_mawaqit, caplog):
    import logging

    from app.masjid_times.mawaqit import MawaqitSource

    fake_mawaqit.pages["test-masjid"] = page(conf(fajrFixationComparedToShuruq=20))
    with caplog.at_level(logging.WARNING):
        days = MawaqitSource().fetch(http, "test-masjid", date(2026, 10, 25), 3)
    assert days[0].iqamah["fajr"] is None
    assert "MAWAQIT page test-masjid sets fajrFixationComparedToShuruq, so its Fajr iqamah isn't used" in caplog.text


def test_jumuah_at_dhuhr_time_has_no_set_slots():
    days = read(conf(jumuaAsDuhr=True))
    assert all(d.jumuah == () for d in days)


def test_jumuah_times_are_only_for_the_coming_friday():
    days = read(conf(), today=date(2026, 10, 25), days=14)
    assert [d.local_date for d in days if d.jumuah] == [FRIDAY]  # not Nov 6
    # Read on a Friday, they're for that same day.
    assert [d.local_date for d in read(conf(), today=FRIDAY, days=8) if d.jumuah] == [FRIDAY]


def test_jumuah_slots_keep_mawaqits_order_even_with_a_gap():
    days = read(conf(jumua="12:45", jumua2=None, jumua3="14:50"), today=FRIDAY, days=1)
    assert days[0].jumuah == (JumuahTime(1, time(12, 45)), JumuahTime(3, time(14, 50)))


def test_next_friday():
    assert next_friday(date(2026, 10, 25)) == FRIDAY  # Sunday
    assert next_friday(FRIDAY) == FRIDAY
    assert next_friday(SATURDAY) == date(2026, 11, 6)
