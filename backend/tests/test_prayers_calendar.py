"""Tests for creating, reusing, and recreating the Prayers calendar."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import PrayerCalendar
from tests.conftest import sign_in
from tests.setup_helpers import save_setup


def _saved_calendar_ids(db) -> list[str]:
    with DbSession(db) as session:
        return session.scalars(select(PrayerCalendar.google_calendar_id)).all()


def test_calendar_is_created_once_and_reused(client, fake_google, set_today, db):
    sign_in(client, fake_google)
    save_setup(db)
    set_today(date(2026, 10, 24))

    client.post("/prayers/today")
    client.post("/prayers/today")
    set_today(date(2026, 10, 25))
    client.post("/prayers/today")

    calendars = fake_google.calendars_of("user-a")
    assert len(calendars) == 1
    assert calendars[0].summary == "Prayers"
    assert _saved_calendar_ids(db) == [calendars[0].id]
    creates = [w for w in fake_google.writes() if w.path == "/calendar/v3/calendars"]
    assert len(creates) == 1


def test_deleted_calendar_is_recreated_with_all_five_prayers(client, fake_google, set_today, db):
    sign_in(client, fake_google)
    save_setup(db)
    set_today(date(2026, 10, 24))
    client.post("/prayers/today")
    old_id = _saved_calendar_ids(db)[0]

    fake_google.delete_calendar(old_id)  # the user deletes it in Google Calendar
    response = client.post("/prayers/today")

    assert response.status_code == 200
    calendars = fake_google.calendars_of("user-a")
    assert len(calendars) == 1
    new_id = calendars[0].id
    assert new_id != old_id
    assert _saved_calendar_ids(db) == [new_id]
    events = fake_google.live_events(new_id)
    assert sorted(e["summary"] for e in events) == [
        "Asr", "Dhuhr", "Fajr", "Isha", "Maghrib"
    ]


def test_calendar_is_created_in_the_saved_time_zone(client, fake_google, set_today, db):
    sign_in(client, fake_google)
    save_setup(db, location=(49.2827, -123.1207), time_zone="America/Vancouver")
    set_today(date(2026, 10, 24), "America/Vancouver")

    client.post("/prayers/today")

    assert fake_google.calendars_of("user-a")[0].time_zone == "America/Vancouver"


def test_moving_changes_the_calendar_time_zone(client, fake_google, set_today, db):
    sign_in(client, fake_google)
    save_setup(db)
    set_today(date(2026, 10, 24))
    client.post("/prayers/today")
    calendar_id = fake_google.calendars_of("user-a")[0].id

    # The user moves from Ottawa to Vancouver.
    save_setup(db, location=(49.2827, -123.1207), time_zone="America/Vancouver")
    client.post("/prayers/today")

    calendars = fake_google.calendars_of("user-a")
    assert [c.id for c in calendars] == [calendar_id]  # the same calendar, not a new one
    assert calendars[0].time_zone == "America/Vancouver"
    patches = [w for w in fake_google.writes() if w.method == "PATCH"]
    assert [p.body for p in patches] == [{"timeZone": "America/Vancouver"}]
    with DbSession(db) as session:
        assert session.scalars(select(PrayerCalendar.time_zone)).all() == ["America/Vancouver"]
