"""The parser against KMA's real MAWAQIT page, saved on October 25, 2026.

fixtures/mawaqit/kma_page.html is the real page trimmed to its timetable
data. The expected times below were read off that page by hand.
"""

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from app.masjid_times.mawaqit import conf_data, days_from, slug_from_link
from tests.calendar_helpers import clock, fetch, google_events, refresh, titled
from tests.masjid_helpers import add_user, link, masjid_id

PAGE = (Path(__file__).parent / "fixtures" / "mawaqit" / "kma_page.html").read_text(encoding="utf-8")
DATA = conf_data(PAGE)


def day(local_date: date):
    return days_from(DATA, local_date, 1)[0]


def test_kmas_link_and_widget_link():
    assert slug_from_link("https://mawaqit.net/en/kma-masjid-ottawa") == "kma-masjid-ottawa"
    assert slug_from_link("https://mawaqit.net/en/w/kma-masjid-ottawa") == "kma-masjid-ottawa"


def test_adhan_and_iqamah_on_october_25():
    sunday = day(date(2026, 10, 25))
    assert sunday.adhan == {
        "fajr": time(6, 11), "dhuhr": time(12, 48), "asr": time(15, 36), "maghrib": time(18, 1), "isha": time(19, 23),
    }
    # "+15" and "+5" are minutes after adhan. The rest are clock times.
    assert sunday.iqamah == {
        "fajr": time(6, 26), "dhuhr": time(13, 30), "asr": time(16, 15), "maghrib": time(18, 6), "isha": time(19, 40),
    }
    assert sunday.jumuah == ()


def test_jumuah_on_friday():
    assert day(date(2026, 10, 30)).jumuah == (time(12, 45), time(14, 0), time(14, 50))


def test_the_page_already_has_the_clocks_going_back():
    # Clock times as the masjid publishes them. Fajr jumps an hour earlier on November 1.
    assert day(date(2026, 11, 1)).adhan["fajr"] == time(5, 20)
    assert day(date(2026, 11, 1)).iqamah["fajr"] == time(5, 35)
    assert day(date(2026, 11, 1)).iqamah["dhuhr"] == time(12, 30)
    assert day(date(2026, 3, 8)).adhan["dhuhr"] == time(13, 14)


def test_plus_zero_months_have_no_iqamah():
    march = day(date(2026, 3, 8))
    assert march.iqamah["asr"] is None and march.iqamah["isha"] is None
    assert march.iqamah["dhuhr"] == time(13, 30)


def test_every_day_of_the_year_passes_the_checks():
    days = days_from(DATA, date(2026, 1, 1), 365)
    assert days[-1].local_date == date(2026, 12, 31)
    assert sum(1 for d in days if d.jumuah) == 52


def test_kma_in_the_calendar(db, http, fake_google, fake_mawaqit):
    now = datetime(2026, 10, 25, 8, 0, tzinfo=ZoneInfo("America/Toronto"))
    # Isha at KMA on weekdays, everything else at home.
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA",
                   at_masjid={d: {"isha"} for d in range(5)})
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-masjid-ottawa")
    fake_mawaqit.pages["kma-masjid-ottawa"] = PAGE
    fetch(db, http, now)
    refresh(db, http, uid, now)
    events = google_events(fake_google)
    monday = date(2026, 10, 26)
    isha = titled(events, monday, "Isha at KMA")
    assert clock(isha) == day(monday).iqamah["isha"].strftime("%H:%M")
    assert isha["description"] == "KMA iqamah (MAWAQIT, updated Oct 25, 2026)"
    fajr = titled(events, monday, "Fajr at home")
    assert clock(fajr) == day(monday).adhan["fajr"].strftime("%H:%M")
    assert fajr["description"] == "KMA adhan time (MAWAQIT)"
