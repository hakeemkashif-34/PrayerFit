"""Prayers moving around busy times, through the real calendar update.

KMA's made-up MAWAQIT page has, on Tuesday Oct 27, 2026: Asr adhan 3:36 pm
with iqamah 4:15 pm, Maghrib 6:01 pm, and Isha adhan 7:23 pm with iqamah
7:40 pm. The fake OpenRouteService says the drive is 10 minutes, and the
user arrives 5 minutes early. Asr and Isha are at KMA on Tuesdays.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.models import UserSettings, WeeklyMasjidPrayers
from tests.calendar_helpers import clock, fetch, google_events, on, refresh, rows, source, titled
from tests.masjid_helpers import add_user, link, masjid_id
from tests.mawaqit_pages import conf, set_day

TORONTO = ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 26, 8, 0, tzinfo=TORONTO)  # Monday
TUESDAY = date(2026, 10, 27)


def moved(after: str) -> str:
    return f"Moved because of an event in your calendar ({after})."


def busy(fake_google, *spans: tuple[str, str], day: str = "2026-10-27", offset: str = "-04:00") -> None:
    """Busy times in the user's primary calendar, like ("19:00", "20:30")."""
    fake_google.busy["user-a"] = [(f"{day}T{s}:00{offset}", f"{day}T{e}:00{offset}") for s, e in spans]


@pytest.fixture
def user(db, fake_google, fake_mawaqit, fake_ors, ors_key):
    uid = add_user(fake_google, db, "user-a", masjid_name="Kanata Muslim Association", short_name="KMA",
                   at_masjid={1: {"asr", "isha"}})
    data = set_day(
        conf(), 10, 27,
        times=["05:55", "07:25", "12:48", "15:36", "18:01", "19:23"],
        iqamah=["+20", "13:00", "16:15", "+5", "19:40"],
    )
    link(db, masjid_id(db, "Kanata Muslim Association"), "kma-kanata", fake_mawaqit, data=data)
    fake_ors.seconds = 10 * 60
    with Session(db) as session:
        session.query(UserSettings).filter_by(user_id=uid).one().arrive_early_minutes = 5
        session.commit()
    return uid


def run(db, http, user):
    fetch(db, http, NOW)
    return refresh(db, http, user, NOW)


def titles(fake_google, day=TUESDAY) -> list[str]:
    return [e["summary"] for e in on(google_events(fake_google), day)]


# ---- Scenario 1: Isha at KMA ----


def test_isha_with_class_until_7_35_is_prayed_at_iqamah_without_the_drive(db, http, user, fake_google):
    # Leaving at 7:25 clashes with the class, but 7:40 to 7:55 is free.
    busy(fake_google, ("18:30", "19:35"))
    run(db, http, user)
    isha = titled(google_events(fake_google), TUESDAY, "Isha")
    assert (clock(isha), clock(isha, end=True)) == ("19:40", "19:55")
    # Asr still has its drive block. Isha doesn't.
    assert titles(fake_google) == ["Fajr", "Dhuhr", "Drive to KMA", "Asr at KMA", "Maghrib", "Isha"]
    # 7:40 is 17 minutes after the adhan (7:23).
    assert isha["description"] == moved("17 minutes after Isha's start time")
    assert source(db, isha).startswith("KMA iqamah (MAWAQIT, updated ")


def test_isha_with_class_from_7_to_8_30_is_prayed_at_8_30(db, http, user, fake_google):
    busy(fake_google, ("19:00", "20:30"))
    run(db, http, user)
    isha = titled(google_events(fake_google), TUESDAY, "Isha")
    assert (clock(isha), clock(isha, end=True)) == ("20:30", "20:45")
    assert isha["description"] == moved("1 hour 7 minutes after Isha's start time")


def test_isha_goes_before_a_meeting_when_that_is_earliest(db, http, user, fake_google):
    # The meeting runs 7:45 to 9:00. 7:23 to 7:38 is free, so Isha goes first.
    busy(fake_google, ("19:45", "21:00"))
    run(db, http, user)
    isha = titled(google_events(fake_google), TUESDAY, "Isha")
    assert clock(isha) == "19:23"
    assert isha["description"] == moved("at Isha's start time")


# ---- Scenario 2: Asr at KMA ----


def test_asr_with_class_from_3_to_6_30_is_a_clash_at_iqamah(db, http, user, fake_google):
    busy(fake_google, ("15:00", "18:30"))
    run(db, http, user)
    asr = titled(google_events(fake_google), TUESDAY, "Asr (clash)")
    assert (clock(asr), clock(asr, end=True)) == ("16:15", "16:25")
    assert asr["description"] == "Your event covers all of Asr's time today, so figure out a way to fit it in."


def test_asr_with_class_from_3_to_4_21_is_prayed_at_4_21(db, http, user, fake_google):
    busy(fake_google, ("15:00", "16:21"))
    run(db, http, user)
    asr = titled(google_events(fake_google), TUESDAY, "Asr")
    assert (clock(asr), clock(asr, end=True)) == ("16:21", "16:31")
    assert asr["description"] == moved("45 minutes after Asr's start time")


# ---- Drive blocks and the app's own events ----


def test_a_free_masjid_prayer_keeps_its_drive_and_title(db, http, user, fake_google):
    busy(fake_google, ("10:00", "11:00"))
    run(db, http, user)
    assert titles(fake_google) == [
        "Fajr", "Dhuhr", "Drive to KMA", "Asr at KMA", "Maghrib", "Drive to KMA", "Isha at KMA",
    ]
    assert clock(titled(google_events(fake_google), TUESDAY, "Isha at KMA")) == "19:40"


def test_a_masjid_prayer_that_moves_loses_its_drive_block(db, http, user, fake_google):
    run(db, http, user)
    assert titles(fake_google).count("Drive to KMA") == 2

    busy(fake_google, ("19:00", "20:30"))
    refresh(db, http, user, NOW.replace(hour=9))
    assert titles(fake_google) == ["Fajr", "Dhuhr", "Drive to KMA", "Asr at KMA", "Maghrib", "Isha"]
    [deleted] = fake_google.deletes()
    isha_drive = next(r for r in rows(db, user) if (r.local_date, r.prayer, r.kind) == (TUESDAY, "isha", "drive"))
    assert deleted.path.endswith(isha_drive.id.hex)
    # Only the Isha block changed, plus the drive block's delete.
    assert [r.fit for r in rows(db, user) if r.local_date == TUESDAY and r.prayer == "isha" and r.kind == "prayer"] == ["moved"]


def test_a_moved_prayer_never_lands_on_the_apps_own_drive_block(db, http, user, fake_google):
    # Maghrib at KMA too: its drive block is 5:51 to 6:01 pm.
    with Session(db) as session:
        session.query(WeeklyMasjidPrayers).filter_by(user_id=user, weekday=1).one().maghrib = True
        session.commit()
    # Busy until 5:45 pm. 5:45 to 6:01 is free in the calendar, but the drive block takes 5:51.
    busy(fake_google, ("15:00", "17:45"))
    run(db, http, user)
    assert "Asr (clash)" in titles(fake_google)
    assert clock(titled(google_events(fake_google), TUESDAY, "Maghrib at KMA")) == "18:06"


def test_without_busy_times_nothing_moves(db, http, user, fake_google):
    run(db, http, user)
    events = on(google_events(fake_google), TUESDAY)
    assert not any("description" in e or "clash" in e["summary"] for e in events)
    assert {r.fit for r in rows(db, user)} == {"normal"}


# ---- Daylight saving ----


def test_a_prayer_moves_on_the_day_the_clocks_go_back(db, http, user, fake_google):
    # Sunday Nov 1, 2026: Dhuhr (KMA's adhan, 12:30) is covered by a 12:00 to 1:00 pm event.
    busy(fake_google, ("12:00", "13:00"), day="2026-11-01", offset="-05:00")
    run(db, http, user)
    dhuhr = titled(google_events(fake_google), date(2026, 11, 1), "Dhuhr")
    assert dhuhr["start"]["dateTime"] == "2026-11-01T13:00:00-05:00"
    assert dhuhr["end"]["dateTime"] == "2026-11-01T13:15:00-05:00"


def test_isha_midnight_counts_real_hours_on_the_night_the_clocks_go_back(db, http, user, fake_google):
    # Oct 31: Maghrib 6:00 pm EDT, Nov 1 Fajr 5:30 am EST. That's 12.5 real hours,
    # so midnight is 12:15 am, not the 11:45 pm a wall clock would give.
    busy(fake_google, ("19:00", "23:55"), day="2026-10-31")
    run(db, http, user)
    isha = titled(google_events(fake_google), date(2026, 10, 31), "Isha")
    assert (clock(isha), clock(isha, end=True)) == ("23:55", "00:10")


# ---- When busy times are unknown ----


def test_a_free_busy_failure_never_undoes_a_move(db, http, user, fake_google):
    busy(fake_google, ("19:00", "20:30"), ("15:00", "18:30"))
    run(db, http, user)
    writes = len(fake_google.writes())

    # The next update can't read busy times. Isha stays moved and Asr stays a clash.
    fake_google.freebusy_failure = 500
    refresh(db, http, user, NOW.replace(hour=9))
    assert len(fake_google.writes()) == writes
    events = google_events(fake_google)
    assert clock(titled(events, TUESDAY, "Isha")) == "20:30"
    assert clock(titled(events, TUESDAY, "Asr (clash)")) == "16:15"
    assert "Drive to KMA" not in titles(fake_google)


def test_a_free_busy_failure_still_applies_other_changes(db, http, user, fake_google):
    busy(fake_google, ("19:00", "20:30"))
    run(db, http, user)
    fake_google.freebusy_failure = 500
    # Asr moves home on Tuesdays. That still goes through, and Isha stays moved.
    with Session(db) as session:
        session.query(WeeklyMasjidPrayers).filter_by(user_id=user, weekday=1).one().asr = False
        session.commit()
    refresh(db, http, user, NOW.replace(hour=9))
    assert titles(fake_google) == ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
    assert clock(titled(google_events(fake_google), TUESDAY, "Isha")) == "20:30"


def test_without_free_busy_access_nothing_moves(db, http, user, fake_google):
    from app.models import GoogleToken
    from tests.fake_google import OLD_SCOPES

    with Session(db) as session:
        session.query(GoogleToken).filter_by(user_id=user).one().scopes = OLD_SCOPES
        session.commit()
    busy(fake_google, ("19:00", "20:30"), ("15:00", "18:30"))
    run(db, http, user)
    assert fake_google.freebusy_requests() == []
    assert titles(fake_google) == [
        "Fajr", "Dhuhr", "Drive to KMA", "Asr at KMA", "Maghrib", "Drive to KMA", "Isha at KMA",
    ]


def test_moved_descriptions_count_minutes_and_hours():
    from app.event_plan import duration_text, moved_text

    start = datetime(2026, 10, 27, 12, 48, tzinfo=TORONTO)
    assert moved_text("Dhuhr", start, start + timedelta(minutes=42)) == moved("42 minutes after Dhuhr's start time")
    assert moved_text("Dhuhr", start, start) == moved("at Dhuhr's start time")
    assert [duration_text(m) for m in (1, 59, 60, 61, 72, 120, 125)] == [
        "1 minute", "59 minutes", "1 hour", "1 hour 1 minute", "1 hour 12 minutes", "2 hours", "2 hours 5 minutes",
    ]
