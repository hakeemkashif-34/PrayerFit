"""Running the calendar update directly and reading what reached the fake Google."""

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar_window import refresh_calendar
from app.masjid_times.scheduler import run_due_fetches
from app.models import PrayerEvent


def refresh(engine, http, user: uuid.UUID, now: datetime):
    with Session(engine, expire_on_commit=False) as db:
        return refresh_calendar(db, http, user, now)


def fetch(engine, http, now: datetime):
    return run_due_fetches(engine, http, now)


def google_events(fake_google, sub: str = "user-a") -> list[dict]:
    calendar = fake_google.calendars_of(sub)[0]
    return fake_google.live_events(calendar.id)


def on(events: list[dict], day: date) -> list[dict]:
    """Events that start on this local date, in start order."""
    found = [e for e in events if e["start"]["dateTime"].startswith(day.isoformat())]
    return sorted(found, key=lambda e: e["start"]["dateTime"])


def titled(events: list[dict], day: date, summary: str) -> dict:
    matches = [e for e in on(events, day) if e["summary"] == summary]
    assert len(matches) == 1, f"{summary} on {day}: {[e['summary'] for e in on(events, day)]}"
    return matches[0]


def rows(engine, user: uuid.UUID) -> list[PrayerEvent]:
    with Session(engine) as db:
        return list(db.scalars(select(PrayerEvent).where(PrayerEvent.user_id == user)))


def clock(event: dict, end: bool = False) -> str:
    """"20:15" from an event's start (or end)."""
    return event["end" if end else "start"]["dateTime"][11:16]


def source(engine, event: dict) -> str:
    """Where a Google event's time came from. Events don't say it any more, so it's read from the row."""
    row_id = uuid.UUID(event["extendedProperties"]["private"]["appEventId"])
    with Session(engine) as db:
        return db.get(PrayerEvent, row_id).source_description
