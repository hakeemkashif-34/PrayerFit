"""Masjid ar-Rahmah's (AMA) timetable from mymasjid.ca.

fixtures/mymasjid/timetable_2026-11-03.html is the real table, saved on
November 3, 2026. The expected times below were read off it by hand. Other
tests change one cell of it, so they test the same layout.
"""

import logging
from datetime import date, time
from pathlib import Path

import pytest

from app.masjid_times.mymasjid import (
    EXTERNAL_ID,
    MyMasjidSource,
    download,
    name_key,
    read_table,
    twelve_hour,
)
from app.masjid_times.source import JumuahTime, SourceBlocked, SourceFailed, SourceInvalid, UpcomingJumuah

PAGE = (Path(__file__).parent / "fixtures" / "mymasjid" / "timetable_2026-11-03.html").read_text(encoding="utf-8")
TUESDAY = date(2026, 11, 3)
FRIDAY = date(2026, 11, 6)


def cell(old: str, new: str, page: str = PAGE) -> str:
    """The saved page with one cell changed, like "<td>07:30 PM</td>" to "<td></td>"."""
    assert page.count(old) == 1, old
    return page.replace(old, new)


def test_the_saved_page():
    fetched = read_table(PAGE, TUESDAY)
    [day] = fetched.days
    assert day.local_date == TUESDAY
    # "Zuhr" on the page is Dhuhr.
    assert day.adhan == {
        "fajr": time(5, 22), "dhuhr": time(11, 46), "asr": time(14, 23), "maghrib": time(16, 49), "isha": time(18, 10),
    }
    assert day.iqamah == {
        "fajr": time(5, 52), "dhuhr": time(12, 30), "asr": time(14, 45), "maghrib": time(16, 54), "isha": time(19, 30),
    }
    # Jumuah is never on the day row: it's saved for the coming Friday.
    assert day.jumuah == ()
    assert fetched.jumuah == UpcomingJumuah(FRIDAY, (JumuahTime(1, time(12, 0)), JumuahTime(2, time(13, 30))))
    assert fetched.skipped == []


def test_only_today_is_read():
    # The page has no date, so nothing is ever saved for another day.
    assert [d.local_date for d in read_table(PAGE, TUESDAY).days] == [TUESDAY]


def test_on_a_friday_jumuah_is_for_that_day():
    assert read_table(PAGE, FRIDAY).jumuah.friday == FRIDAY


def test_a_saturday_read_is_for_next_friday():
    assert read_table(PAGE, date(2026, 11, 7)).jumuah.friday == date(2026, 11, 13)


@pytest.mark.parametrize(
    "text, expected",
    [("05:22 AM", time(5, 22)), ("12:30 PM", time(12, 30)), ("01:30 PM", time(13, 30)), ("12:15 AM", time(0, 15)),
     ("7:05 pm", time(19, 5)), ("11:59 PM", time(23, 59))],
)
def test_twelve_hour_times(text, expected):
    assert twelve_hour(text, "test") == expected


@pytest.mark.parametrize("text", ["13:00 PM", "00:30 AM", "5:3 AM", "05:22", "noon", "05:60 AM"])
def test_bad_times_are_refused(text):
    with pytest.raises(SourceInvalid, match="isn't a clock time"):
        twelve_hour(text, "test")


def test_names_ignore_accents_and_spaces():
    assert name_key("Jumuʿah 2") == "jumuah2"
    assert name_key(" Zuhr ") == "zuhr"
    assert name_key("Salāh") == "salah"


def test_a_missing_iqamah_stays_missing():
    # Never made up: the calendar uses the calculated time for it.
    page = cell("<td>07:30 PM</td>", "<td></td>")
    assert read_table(page, TUESDAY).days[0].iqamah["isha"] is None


def test_a_missing_prayer_rejects_the_read():
    page = cell("<td>Asr</td>", "<td>Something else</td>")
    with pytest.raises(SourceInvalid, match="no asr time for 2026-11-03"):
        read_table(page, TUESDAY)


def test_a_repeated_prayer_rejects_the_read():
    page = cell("<td>Asr</td>", "<td>Zuhr</td>")
    with pytest.raises(SourceInvalid, match="dhuhr twice"):
        read_table(page, TUESDAY)


@pytest.mark.parametrize(
    "old, new, reason",
    [
        ("<td>02:45 PM</td>", "<td>2:45</td>", "2026-11-03 asr iqamah isn't a clock time"),
        ("<td>05:22 AM</td>", "<td></td>", "2026-11-03 fajr adhan isn't a clock time"),
        ("<td>12:30 PM</td>", "<td>11:30 AM</td>", "2026-11-03 dhuhr iqamah is before adhan"),
        ("<td>04:54 PM</td>", "<td>06:30 PM</td>", "2026-11-03 maghrib iqamah is more than 90 minutes"),
        # Isha gets 150 minutes, so 8:41 pm (151 minutes after 6:10 pm) is too late.
        ("<td>07:30 PM</td>", "<td>08:41 PM</td>", "2026-11-03 isha iqamah is more than 150 minutes"),
    ],
)
def test_a_bad_day_rejects_the_read_and_says_which_prayer(old, new, reason):
    # It's the only day on the page, so the read fails and the last good times stay.
    with pytest.raises(SourceInvalid, match=reason):
        read_table(cell(old, new), TUESDAY)


def test_isha_up_to_150_minutes_after_adhan_is_fine():
    page = cell("<td>07:30 PM</td>", "<td>08:40 PM</td>")
    assert read_table(page, TUESDAY).days[0].iqamah["isha"] == time(20, 40)


def test_a_bad_jumuah_time_only_skips_jumuah():
    page = cell("<td>01:30 PM</td>", "<td>1:30</td>")
    fetched = read_table(page, TUESDAY)
    assert len(fetched.days) == 1
    # None means not read, so the last good Jumuah times stay saved.
    assert fetched.jumuah is None
    assert [s.reason for s in fetched.skipped] == ["2026-11-06 Jumuah 2 isn't a clock time"]


def test_no_jumuah_rows_means_no_jumuah_times():
    page = PAGE
    for row in ("Jumu&#703;ah</td>", "Jumu&#703;ah 2</td>"):
        page = page.replace(row, "Notice</td>")
    assert read_table(page, TUESDAY).jumuah == UpcomingJumuah(FRIDAY, ())


def test_a_third_jumuah_is_read_too():
    extra = "<tr><td>Jumu&#703;ah 3</td><td>02:45 PM</td><td></td><td></td></tr></tbody>"
    page = cell("</tbody>", extra)
    assert read_table(page, TUESDAY).jumuah.slots[-1] == JumuahTime(3, time(14, 45))


def test_script_text_is_never_read():
    page = cell("</body>", "<script>document.write('<td>Asr</td><td>09:00 AM</td>');</script></body>")
    assert read_table(page, TUESDAY).days[0].adhan["asr"] == time(14, 23)


@pytest.mark.parametrize(
    "html",
    ["<html><body>Maintenance</body></html>", "", "<table><tr><td>Fajr</td></tr></table>"],
)
def test_a_changed_page_is_rejected(html):
    with pytest.raises(SourceInvalid):
        read_table(html, TUESDAY)


# ---- Downloading ----


def test_it_reads_the_fixed_url(http, fake_mymasjid):
    html = download(http)
    assert "Iq&#257;mah" in html
    assert [str(r.url) for r in fake_mymasjid.requests] == ["https://app.mymasjid.ca/protected/public/timetable"]


@pytest.mark.parametrize(
    "failure, error, logged",
    [
        (403, SourceBlocked, "status 403 Forbidden"),
        (429, SourceBlocked, "status 429 Too Many Requests"),
        (500, SourceFailed, "status 500 Internal Server Error"),
        (302, SourceFailed, "status 302 Found"),
        ("timeout", SourceFailed, "timeout"),
        ("huge", SourceFailed, "page too big"),
    ],
)
def test_failures_are_logged_with_the_reason(http, fake_mymasjid, caplog, failure, error, logged):
    fake_mymasjid.failure = failure
    with caplog.at_level(logging.WARNING), pytest.raises(error):
        download(http)
    assert f"mymasjid.ca timetable failed: {logged}" in caplog.text
    assert "Fake failure" not in caplog.text


def test_a_redirect_is_never_followed(http, fake_mymasjid):
    fake_mymasjid.failure = 302
    with pytest.raises(SourceFailed):
        download(http)
    assert len(fake_mymasjid.requests) == 1


def test_the_source_reads_only_its_own_id(http, fake_mymasjid):
    with pytest.raises(SourceFailed, match="isn't valid"):
        MyMasjidSource().fetch(http, "https://evil.example", TUESDAY, 14)
    assert fake_mymasjid.requests == []


def test_a_missing_iqamah_is_logged(http, fake_mymasjid, caplog):
    fake_mymasjid.page = cell("<td>07:30 PM</td>", "<td></td>")
    with caplog.at_level(logging.INFO):
        fetched = MyMasjidSource().fetch(http, EXTERNAL_ID, TUESDAY, 14)
    assert fetched.days[0].iqamah["isha"] is None
    assert "mymasjid.ca has no isha iqamah for 2026-11-03, so the calculated time is used" in caplog.text
