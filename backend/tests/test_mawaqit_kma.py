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
    from app.masjid_times.source import JumuahTime

    assert day(date(2026, 10, 30)).jumuah == (
        JumuahTime(1, time(12, 45)), JumuahTime(2, time(14, 0)), JumuahTime(3, time(14, 50)),
    )


def test_the_page_already_has_the_clocks_going_back():
    # Clock times as the masjid publishes them. Fajr jumps an hour earlier on November 1.
    assert day(date(2026, 11, 1)).adhan["fajr"] == time(5, 20)
    assert day(date(2026, 11, 1)).iqamah["fajr"] == time(5, 35)
    assert day(date(2026, 11, 1)).iqamah["dhuhr"] == time(12, 30)
    assert day(date(2026, 3, 8)).adhan["dhuhr"] == time(13, 14)


def test_plus_zero_days_are_iqamah_at_the_adhan_time():
    # KMA's page has "+0" for Asr and Isha on the days its set time would
    # come before the adhan. On those days the iqamah is at the adhan.
    march = day(date(2026, 3, 8))
    assert march.iqamah["asr"] == march.adhan["asr"]
    assert march.iqamah["isha"] == march.adhan["isha"]
    assert march.iqamah["dhuhr"] == time(13, 30)
    # Isha switches from "+0" to the set time, 7:40 pm, on October 15.
    october_14, october_15 = day(date(2026, 10, 14)), day(date(2026, 10, 15))
    assert october_14.iqamah["isha"] == october_14.adhan["isha"]
    assert october_14.adhan["isha"] > time(19, 40)
    assert october_15.iqamah["isha"] == time(19, 40)
    # Asr does the same on September 27, at 4:15 pm.
    assert day(date(2026, 9, 26)).iqamah["asr"] == day(date(2026, 9, 26)).adhan["asr"]
    assert day(date(2026, 9, 27)).iqamah["asr"] == time(16, 15)


def test_kmas_fajr_isnt_tied_to_sunrise():
    from app.masjid_times.mawaqit import fajr_tied_to_sunrise

    assert not fajr_tied_to_sunrise(DATA)
    assert day(date(2026, 10, 25)).iqamah["fajr"] == time(6, 26)


def test_every_day_of_the_year_passes_the_checks():
    days = days_from(DATA, date(2026, 1, 1), 365)
    assert days[-1].local_date == date(2026, 12, 31)
    # MAWAQIT only holds one week's Jumuah times, so only the first Friday has them.
    assert [d.local_date for d in days if d.jumuah] == [date(2026, 1, 2)]


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
    fajr = titled(events, monday, "Fajr")
    assert fajr["start"]["dateTime"].startswith("2026-10-26T06:13")
    assert clock(fajr) == day(monday).adhan["fajr"].strftime("%H:%M")
    assert fajr["description"] == "KMA adhan time (MAWAQIT)"


def test_a_plus_zero_day_is_labelled_as_kmas_iqamah(db, http, fake_google, fake_mawaqit):
    # October 13: Isha is "+0" on KMA's page, so the iqamah is at the adhan.
    now = datetime(2026, 10, 13, 8, 0, tzinfo=ZoneInfo("America/Toronto"))
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA",
                   at_masjid={d: {"isha"} for d in range(5)})
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-masjid-ottawa")
    fake_mawaqit.pages["kma-masjid-ottawa"] = PAGE
    fetch(db, http, now)
    refresh(db, http, uid, now)
    tuesday = date(2026, 10, 13)
    isha = titled(google_events(fake_google), tuesday, "Isha at KMA")
    assert clock(isha) == day(tuesday).adhan["isha"].strftime("%H:%M")
    assert isha["description"] == "KMA iqamah (MAWAQIT, updated Oct 13, 2026)"
