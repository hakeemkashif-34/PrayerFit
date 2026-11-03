"""Masjid ar-Rahmah's times from mymasjid.ca, all the way to the calendar.

The site only shows today, so:
1. Today gets the masjid's times. Days that weren't read use calculated times.
2. The next day's read adds that day, and users' calendars update.
3. The 2 Jumuah times are saved for the coming Friday, as start times.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

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
