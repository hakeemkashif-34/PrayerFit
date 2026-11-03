"""Masjid ar-Rahmah's times from mymasjid.ca, all the way to the calendar.

The site only shows today, so:
1. Today gets the masjid's times. Days that weren't read use calculated times.
2. The next day's read adds that day, and users' calendars update.
3. The 2 Jumuah times are saved for the coming Friday, as start times.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.event_plan import MasjidContext, jumuah_slots
from app.masjid_times.mymasjid import EXTERNAL_ID
from app.masjid_times.source import JumuahTime
from app.masjid_times.store import load_masjid_times
from app.models import Masjid, MasjidDayTimes, MasjidSource, UpdateJob
from tests.calendar_helpers import clock, fetch, google_events, refresh, source, titled
from tests.masjid_helpers import add_user, link, masjid_id

TORONTO = ZoneInfo("America/Toronto")
TUESDAY = date(2026, 11, 3)
WEDNESDAY = date(2026, 11, 4)
FRIDAY = date(2026, 11, 6)
# A whole day in 5-minute steps takes a few seconds, so these get more than the usual 10.
WHOLE_DAY = pytest.mark.timeout(30)


def at(day: date, hour: int) -> datetime:
    # A local date and clock time, never "plus 24 hours".
    return datetime.combine(day, time(hour, 0), tzinfo=TORONTO)


def ama_user(db, fake_google) -> tuple:
    """A user who prays Isha at Masjid ar-Rahmah on weekdays, linked to mymasjid.ca."""
    uid = add_user(fake_google, db, "user-a", masjid_name="Masjid ar-Rahmah", short_name="AMA",
                   at_masjid={d: {"isha"} for d in range(5)})
    ama = masjid_id(db, "Masjid ar-Rahmah")
    link(db, ama, EXTERNAL_ID, source="mymasjid")
    return uid, ama


def saved_dates(db, masjid) -> list[date]:
    with Session(db) as session:
        query = select(MasjidDayTimes.local_date).where(MasjidDayTimes.masjid_id == masjid)
        return sorted(session.scalars(query))


def test_today_gets_the_masjids_times_and_other_days_are_calculated(db, http, fake_google, fake_mymasjid):
    uid, ama = ama_user(db, fake_google)
    [result] = fetch(db, http, at(TUESDAY, 8))
    assert result.status == "done"
    # Only today is saved. Nothing is copied to other days.
    assert saved_dates(db, ama) == [TUESDAY]

    refresh(db, http, uid, at(TUESDAY, 8))
    events = google_events(fake_google)
    tuesday_isha = titled(events, TUESDAY, "Isha at AMA")
    assert clock(tuesday_isha) == "19:30"
    assert source(db, tuesday_isha) == "AMA iqamah (mymasjid.ca, updated Nov 3, 2026)"
    # Home prayers today use the masjid's adhan.
    assert source(db, titled(events, TUESDAY, "Maghrib")) == "AMA adhan time (mymasjid.ca)"
    assert clock(titled(events, TUESDAY, "Maghrib")) == "16:49"
    # Wednesday hasn't been read, so it's calculated, and no iqamah is made up.
    wednesday_isha = source(db, titled(events, WEDNESDAY, "Isha at AMA"))
    assert wednesday_isha.startswith("Calculated start time")
    assert wednesday_isha.endswith("AMA's iqamah time isn't available.")
    assert source(db, titled(events, WEDNESDAY, "Maghrib")).startswith("Calculated")


def test_the_next_days_read_adds_that_day_and_updates_calendars(db, http, fake_google, fake_mymasjid):
    uid, ama = ama_user(db, fake_google)
    fetch(db, http, at(TUESDAY, 8))
    with Session(db) as session:
        session.execute(UpdateJob.__table__.delete())
        session.commit()

    [result] = fetch(db, http, at(WEDNESDAY, 8))
    # A new day inside the calendar's 14 days is a change, so the user's calendar is updated.
    assert result.changed is True
    assert saved_dates(db, ama) == [TUESDAY, WEDNESDAY]
    with Session(db) as session:
        assert session.scalars(select(UpdateJob.user_id).where(UpdateJob.status == "pending")).all() == [uid]


def test_a_failed_read_leaves_that_day_calculated(db, http, fake_google, fake_mymasjid):
    uid, ama = ama_user(db, fake_google)
    fetch(db, http, at(TUESDAY, 8))
    fake_mymasjid.failure = 500
    [result] = fetch(db, http, at(WEDNESDAY, 8))
    assert result.status == "failed"
    assert saved_dates(db, ama) == [TUESDAY]
    refresh(db, http, uid, at(WEDNESDAY, 8))
    assert source(db, titled(google_events(fake_google), WEDNESDAY, "Isha at AMA")).startswith("Calculated start time")


def test_jumuah_start_times_are_saved_for_the_coming_friday(db, http, fake_google, fake_mymasjid):
    _, ama = ama_user(db, fake_google)
    fetch(db, http, at(TUESDAY, 8))
    with Session(db) as session:
        assert session.get(MasjidSource, ama).upcoming_jumuah == {
            "friday": "2026-11-06", "slots": [{"order": 1, "time": "12:00"}, {"order": 2, "time": "13:30"}],
        }
        times = load_masjid_times(session, [ama], [TUESDAY, FRIDAY], at(TUESDAY, 8))[ama]
        masjid = session.get(Masjid, ama)
    # Friday has no row yet, but its Jumuah times are known.
    assert times.usable_day(FRIDAY) is None
    assert times.jumuah_on(FRIDAY) == (JumuahTime(1, time(12, 0)), JumuahTime(2, time(13, 30)))
    # They're for this Friday only. A later Friday waits for its own week's read.
    assert times.jumuah_on(date(2026, 11, 13)) == ()

    context = MasjidContext(masjid=masjid, label="AMA", time_zone="America/Toronto", times=times, drive_seconds=None)
    slots = jumuah_slots([context], FRIDAY)
    assert [s.starts_at for s in slots] == [at(FRIDAY, 12), datetime(2026, 11, 6, 13, 30, tzinfo=TORONTO)]


def test_jumuah_in_the_calendar_uses_the_start_time(db, http, fake_google, fake_mymasjid):
    uid, _ = ama_user(db, fake_google)
    fetch(db, http, at(TUESDAY, 8))
    refresh(db, http, uid, at(TUESDAY, 8))
    jumuah = titled(google_events(fake_google), FRIDAY, "Jumuah at AMA")
    assert clock(jumuah) == "12:00"
    assert source(db, jumuah) == "AMA Jumuah (mymasjid.ca, updated Nov 3, 2026)"


def test_a_bad_jumuah_time_keeps_the_last_good_jumuah(db, http, fake_google, fake_mymasjid):
    _, ama = ama_user(db, fake_google)
    fetch(db, http, at(TUESDAY, 8))
    fake_mymasjid.page = fake_mymasjid.page.replace("<td>01:30 PM</td>", "<td>1:30</td>")
    [result] = fetch(db, http, at(WEDNESDAY, 8))
    # The 5 prayers were still read.
    assert result.status == "done"
    assert saved_dates(db, ama) == [TUESDAY, WEDNESDAY]
    with Session(db) as session:
        row = session.get(MasjidSource, ama)
        assert row.upcoming_jumuah["slots"][1] == {"order": 2, "time": "13:30"}
        assert row.last_error == "Skipped 1 day: 2026-11-06 Jumuah 2 isn't a clock time"


def read_times(db, http, fake_mymasjid, day: date) -> list[str]:
    """Run the worker every 5 minutes through one local day, like the real worker
    (it runs every minute). Returns the local clock time of each read."""
    times = []
    for minute in range(0, 24 * 60, 5):
        # Local clock times on that date, never "plus 24 hours".
        moment = datetime.combine(day, time(minute // 60, minute % 60), tzinfo=TORONTO)
        before = len(fake_mymasjid.requests)
        fetch(db, http, moment)
        if len(fake_mymasjid.requests) > before:
            times.append(f"{moment:%H:%M}")
    return times


@WHOLE_DAY
def test_read_times_across_a_winter_day(db, http, fake_google, fake_mymasjid):
    ama_user(db, fake_google)
    # Tuesday November 10, 2026: Eastern Standard Time. Fajr's iqamah is around 6 am.
    assert read_times(db, http, fake_mymasjid, date(2026, 11, 10)) == ["00:15", "12:00"]
    # The next day starts the same way, since the reads follow the local clock, not UTC blocks.
    assert read_times(db, http, fake_mymasjid, date(2026, 11, 11)) == ["00:15", "12:00"]


@WHOLE_DAY
def test_read_times_across_a_summer_day(db, http, fake_google, fake_mymasjid):
    ama_user(db, fake_google)
    # Tuesday July 14, 2026: Eastern Daylight Time. Fajr's adhan is around 3:30 am,
    # so the 12:15 am read is still more than 3 hours before it.
    assert read_times(db, http, fake_mymasjid, date(2026, 7, 14)) == ["00:15", "12:00"]


@WHOLE_DAY
def test_read_times_on_the_days_the_clocks_change(db, http, fake_google, fake_mymasjid):
    _, ama = ama_user(db, fake_google)
    # March 8, 2026 skips 2 am to 3 am, and November 1, 2026 has 1 am to 2 am twice.
    # Neither is near 12:15 am or noon, so the reads are the same.
    for day in (date(2026, 3, 8), date(2026, 11, 1)):
        assert read_times(db, http, fake_mymasjid, day) == ["00:15", "12:00"]
    assert saved_dates(db, ama) == [date(2026, 3, 8), date(2026, 11, 1)]


@WHOLE_DAY
def test_a_failed_first_read_is_tried_again_within_the_hour(db, http, fake_google, fake_mymasjid):
    _, ama = ama_user(db, fake_google)
    day = date(2026, 11, 10)
    fake_mymasjid.failure = 500
    assert fetch(db, http, datetime.combine(day, time(0, 15), tzinfo=TORONTO))[0].status == "failed"
    fake_mymasjid.failure = None
    # The rest of the day: the retry at 1 am works, then the midday read.
    times = read_times(db, http, fake_mymasjid, day)
    assert times == ["01:00", "12:00"]
    assert saved_dates(db, ama) == [day]


@WHOLE_DAY
def test_a_site_down_all_day_is_tried_at_noon_then_the_next_night(db, http, fake_google, fake_mymasjid):
    _, ama = ama_user(db, fake_google)
    fake_mymasjid.failure = 500
    # 3 tries an hour apart, then the 12:00 pm read. When that fails too, it waits
    # until midnight instead of 24 hours, so the next day's 12:15 am read still happens before Fajr.
    assert read_times(db, http, fake_mymasjid, date(2026, 11, 10)) == ["00:15", "01:00", "02:00", "12:00"]
    fake_mymasjid.failure = None
    assert read_times(db, http, fake_mymasjid, date(2026, 11, 11)) == ["00:15", "12:00"]
    assert saved_dates(db, ama) == [date(2026, 11, 11)]


@WHOLE_DAY
def test_a_site_down_overnight_but_back_by_noon_is_read_at_noon(db, http, fake_google, fake_mymasjid):
    _, ama = ama_user(db, fake_google)
    day = date(2026, 11, 10)
    # Down from 12:15 am to 3 am: the 3 overnight tries fail.
    fake_mymasjid.failure = 500
    for clock_time in (time(0, 15), time(1, 0), time(2, 0)):
        [result] = fetch(db, http, datetime.combine(day, clock_time, tzinfo=TORONTO))
        assert result.status in ("failed", "blocked")
    assert result.status == "blocked"
    # Back up by noon. Nothing is tried in the morning, then the 12:00 pm read saves the day.
    fake_mymasjid.failure = None
    before = len(fake_mymasjid.requests)
    times = []
    for minute in range(3 * 60, 24 * 60, 5):
        moment = datetime.combine(day, time(minute // 60, minute % 60), tzinfo=TORONTO)
        count = len(fake_mymasjid.requests)
        fetch(db, http, moment)
        if len(fake_mymasjid.requests) > count:
            times.append(f"{moment:%H:%M}")
    assert times == ["12:00"]
    assert len(fake_mymasjid.requests) == before + 1
    assert saved_dates(db, ama) == [day]
    with Session(db) as session:
        row = session.get(MasjidSource, ama)
        assert (row.consecutive_failures, row.retry_after) == (0, None)


@WHOLE_DAY
def test_a_403_still_waits_24_hours(db, http, fake_google, fake_mymasjid):
    _, ama = ama_user(db, fake_google)
    fake_mymasjid.failure = 403
    assert read_times(db, http, fake_mymasjid, date(2026, 11, 10)) == ["00:15"]
    with Session(db) as session:
        assert session.get(MasjidSource, ama).retry_after == datetime(2026, 11, 11, 0, 15, tzinfo=TORONTO)


def test_the_evening_is_never_read(db, http, fake_google, fake_mymasjid):
    ama_user(db, fake_google)
    # Nothing saved today yet, so it would try every hour, but not from 6:45 pm to 12:15 am.
    fake_mymasjid.failure = 500
    for clock_time in (time(18, 45), time(21, 0), time(23, 59), time(0, 14)):
        assert fetch(db, http, datetime.combine(date(2026, 11, 10), clock_time, tzinfo=TORONTO)) == []
    assert fake_mymasjid.requests == []
