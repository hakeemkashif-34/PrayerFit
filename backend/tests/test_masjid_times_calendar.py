"""Which time each prayer uses, and where it says the time came from.

KMA is linked to MAWAQIT. Its made-up page has Fajr 05:30, Dhuhr 12:30
(iqamah 13:00), Asr 15:30, Maghrib 18:00, Isha 19:30 (iqamah 20:15), and
Jumuah at 13:30 and 14:30.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.models import MasjidSource
from app.nightly import run_now
from app.update_jobs import run_due_updates
from tests.calendar_helpers import clock, fetch, google_events, on, refresh, source, titled
from tests.masjid_helpers import add_user, link, masjid_id
from tests.mawaqit_pages import conf, page, set_day

TORONTO = ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 25, 8, 0, tzinfo=TORONTO)  # a Sunday
MONDAY = date(2026, 10, 26)
WEEKDAYS_AT_KMA = {day: {"dhuhr", "isha"} for day in range(5)}


@pytest.fixture
def user(db, fake_google, fake_mawaqit):
    """Prays Dhuhr and Isha at KMA on weekdays, everything else at home."""
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA",
                   at_masjid=WEEKDAYS_AT_KMA)
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit)
    return uid


def test_masjid_prayers_use_the_iqamah(db, http, user, fake_google):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    isha = titled(google_events(fake_google), MONDAY, "Isha at KMA")
    assert clock(isha) == "20:15" and clock(isha, end=True) == "20:30"
    assert source(db, isha) == "KMA iqamah (MAWAQIT, updated Oct 25, 2026)"
    dhuhr = titled(google_events(fake_google), MONDAY, "Dhuhr at KMA")
    assert clock(dhuhr) == "13:00"


def test_home_prayers_use_the_masjids_adhan(db, http, user, fake_google):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    fajr = titled(google_events(fake_google), MONDAY, "Fajr")
    assert clock(fajr) == "05:30"
    assert source(db, fajr) == "KMA adhan time (MAWAQIT)"
    # Sunday: every prayer at home, all from KMA's page.
    sunday = [e for e in on(google_events(fake_google), date(2026, 11, 1)) if " at " not in e["summary"]]
    assert [clock(e) for e in sunday] == ["05:30", "12:30", "15:30", "18:00", "19:30"]


def test_home_prayers_are_calculated_without_a_link(db, http, fake_google):
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA",
                   at_masjid=WEEKDAYS_AT_KMA)
    refresh(db, http, uid, NOW)
    fajr = titled(google_events(fake_google), MONDAY, "Fajr")
    assert source(db, fajr).startswith("Calculated (ISNA, standard Asr)")
    isha = titled(google_events(fake_google), MONDAY, "Isha at KMA")
    assert source(db, isha) == "Calculated start time (ISNA, standard Asr). KMA's iqamah time isn't available."


def test_a_missing_iqamah_uses_the_calculated_time_and_says_so(db, http, user, fake_google, fake_mawaqit):
    fake_mawaqit.pages["kma-kanata"] = page(set_day(conf(), 10, 26, iqamah=["+20", "13:00", "+10", "+5", ""]))
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    isha = titled(google_events(fake_google), MONDAY, "Isha at KMA")
    assert source(db, isha) == "Calculated start time (ISNA, standard Asr). KMA's iqamah time isn't available."
    assert clock(isha) != "20:15" and clock(isha) != "19:30"  # not the iqamah, and not KMA's adhan


def test_times_not_confirmed_for_24_hours_are_not_used(db, http, user, fake_google, fake_mawaqit):
    # The last good read was 24 hours ago. MAWAQIT blocks us after that.
    fetch(db, http, NOW - timedelta(hours=24))
    fake_mawaqit.failure = 403
    refresh(db, http, user, NOW)
    isha = titled(google_events(fake_google), MONDAY, "Isha at KMA")
    assert clock(isha) != "20:15"
    assert source(db, isha) == "Calculated start time (ISNA, standard Asr). KMA's iqamah time isn't available."
    fajr = titled(google_events(fake_google), MONDAY, "Fajr")
    assert source(db, fajr).startswith("Calculated (ISNA, standard Asr)")


def test_times_confirmed_under_24_hours_ago_are_used(db, http, user, fake_google, fake_mawaqit):
    fetch(db, http, NOW - timedelta(hours=23, minutes=59))
    fake_mawaqit.failure = 403
    refresh(db, http, user, NOW)
    assert clock(titled(google_events(fake_google), MONDAY, "Isha at KMA")) == "20:15"


def test_events_have_no_description(db, http, user, fake_google, ors_key):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    events = google_events(fake_google)
    assert {e["summary"] for e in events} >= {"Fajr", "Isha at KMA", "Drive to KMA", "Jumuah at KMA"}
    assert not any("description" in e for e in events)


@pytest.mark.parametrize(
    "day, utc_hour",
    [
        (date(2026, 10, 31), "09:30"),  # Saturday, still daylight time (UTC-4)
        (date(2026, 11, 1), "10:30"),  # the clocks went back at 2:00 am (UTC-5)
    ],
)
def test_fall_daylight_saving_keeps_the_masjids_clock_time(db, http, user, fake_google, day, utc_hour):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    fajr = titled(google_events(fake_google), day, "Fajr")
    start = datetime.fromisoformat(fajr["start"]["dateTime"])
    assert start.strftime("%H:%M") == "05:30"
    assert start.astimezone(ZoneInfo("UTC")).strftime("%H:%M") == utc_hour


def test_spring_daylight_saving_keeps_the_masjids_clock_time(db, http, user, fake_google):
    spring = datetime(2026, 3, 7, 8, 0, tzinfo=TORONTO)  # the clocks go forward on Sunday, March 8
    fetch(db, http, spring)
    refresh(db, http, user, spring)
    before = titled(google_events(fake_google), date(2026, 3, 7), "Fajr")
    after = titled(google_events(fake_google), date(2026, 3, 8), "Fajr")
    utc = ZoneInfo("UTC")
    assert datetime.fromisoformat(before["start"]["dateTime"]).astimezone(utc).strftime("%H:%M") == "10:30"
    assert datetime.fromisoformat(after["start"]["dateTime"]).astimezone(utc).strftime("%H:%M") == "09:30"
    assert clock(after) == "05:30"


def test_a_masjid_change_updates_only_linked_users_and_changed_events(db, http, user, fake_google, fake_mawaqit):
    other = add_user(fake_google, db, "user-b", masjid_name="Other Masjid", at_masjid=WEEKDAYS_AT_KMA)
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    refresh(db, http, other, NOW)
    run_due_updates(db, http, NOW)  # the first fetch queued an update; nothing is left to send
    before = len(fake_google.writes())

    # KMA moves Isha on Wednesday from 8:15 pm to 8:30 pm.
    fake_mawaqit.pages["kma-kanata"] = page(set_day(conf(), 10, 28, iqamah=["+20", "13:00", "+10", "+5", "20:30"]))
    later = NOW + timedelta(hours=6)
    fetch(db, http, later)
    results = run_due_updates(db, http, later)
    assert [r.job_id for r in results] == [f"update:{user}"]
    writes = fake_google.writes()[before:]
    assert len(writes) == 1
    assert writes[0].body["summary"] == "Isha at KMA"
    assert writes[0].body["start"]["dateTime"].startswith("2026-10-28T20:30")


def test_a_broken_page_sends_nothing_to_google(db, http, user, fake_google, fake_mawaqit):
    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    before = len(fake_google.writes())
    fake_mawaqit.pages["kma-kanata"] = page(set_day(conf(), 10, 28, times=["05:30", "07:00", "12:30", "15:30", "18:00", "99:99"]))
    later = NOW + timedelta(hours=6)
    fetch(db, http, later)
    run_due_updates(db, http, later)
    refresh(db, http, user, later)
    assert len(fake_google.writes()) == before
    assert clock(titled(google_events(fake_google), date(2026, 10, 28), "Isha at KMA")) == "20:15"


def test_rerunning_the_nightly_job_with_no_changes_sends_nothing(db, http, user, fake_google):
    fetch(db, http, NOW)
    run_now(db, http, NOW)
    before = len(fake_google.writes())
    assert before > 0
    run_now(db, http, NOW + timedelta(minutes=5), force=True)
    assert len(fake_google.writes()) == before


def test_unlinking_goes_back_to_calculated_times(db, http, user, fake_google):
    from app import admin

    fetch(db, http, NOW)
    refresh(db, http, user, NOW)
    with Session(db) as session:
        admin.unlink_mawaqit(session, str(masjid_id(db, "Kanata Muslim Association")), NOW)
        assert session.get(MasjidSource, masjid_id(db, "Kanata Muslim Association")) is None
    run_due_updates(db, http, NOW)
    isha = titled(google_events(fake_google), MONDAY, "Isha at KMA")
    assert source(db, isha).startswith("Calculated start time")
