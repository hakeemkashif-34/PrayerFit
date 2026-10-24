"""Tests for creating, reusing, and recreating the Prayers calendar."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import PrayerCalendar
from tests.conftest import sign_in

OTTAWA = {"latitude": 45.4215, "longitude": -75.6972, "timezone": "America/Toronto"}


def _saved_calendar_ids(db) -> list[str]:
    with DbSession(db) as session:
        return session.scalars(select(PrayerCalendar.google_calendar_id)).all()


def test_calendar_is_created_once_and_reused(client, fake_google, set_today, db):
    sign_in(client, fake_google)
    set_today(date(2026, 10, 24))

    client.post("/prayers/today", json=OTTAWA)
    client.post("/prayers/today", json=OTTAWA)
    set_today(date(2026, 10, 25))
    client.post("/prayers/today", json=OTTAWA)

    calendars = fake_google.calendars_of("user-a")
    assert len(calendars) == 1
    assert calendars[0].summary == "Prayers"
    assert _saved_calendar_ids(db) == [calendars[0].id]
    creates = [w for w in fake_google.writes() if w.path == "/calendar/v3/calendars"]
    assert len(creates) == 1


def test_deleted_calendar_is_recreated_with_all_five_prayers(client, fake_google, set_today, db):
    sign_in(client, fake_google)
    set_today(date(2026, 10, 24))
    client.post("/prayers/today", json=OTTAWA)
    old_id = _saved_calendar_ids(db)[0]

    fake_google.delete_calendar(old_id)  # the user deletes it in Google Calendar
    response = client.post("/prayers/today", json=OTTAWA)

    assert response.status_code == 200
    calendars = fake_google.calendars_of("user-a")
    assert len(calendars) == 1
    new_id = calendars[0].id
    assert new_id != old_id
    assert _saved_calendar_ids(db) == [new_id]
    events = fake_google.live_events(new_id)
    assert sorted(e["summary"] for e in events) == ["Asr", "Dhuhr", "Fajr", "Isha", "Maghrib"]


def test_calendar_is_created_in_the_given_time_zone(client, fake_google, set_today):
    sign_in(client, fake_google)
    set_today(date(2026, 10, 24), "America/Vancouver")

    client.post(
        "/prayers/today",
        json={"latitude": 49.2827, "longitude": -123.1207, "timezone": "America/Vancouver"},
    )

    assert fake_google.calendars_of("user-a")[0].time_zone == "America/Vancouver"
