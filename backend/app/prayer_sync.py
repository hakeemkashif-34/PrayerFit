"""Turn calculated prayer times into events, save them, and send them to Google.

How duplicates are prevented:
1. Each prayer on each day has one row (unique on user, date, prayer), so
   running again updates the row instead of adding one.
2. The row is saved before anything is sent to Google.
3. The row's UUID, as 32 hex characters, is also the Google event ID. Google
   lets apps pick their own event IDs, and refuses a second event with the
   same ID (409). So even if a request timed out after Google saved the
   event, the retry can't make a copy. It gets a 409 and updates instead.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.google_calendar import GoogleCalendar
from app.google_errors import GoogleConflict, GoogleError, GoogleNotFound
from app.models import PrayerEvent
from app.prayer_times import AsrMethod, CalculationMethod, DailyPrayerTimes, PrayerTime

# Sunrise isn't a prayer. It's when Fajr ends, so it doesn't get an event.
PRAYERS = ("fajr", "dhuhr", "asr", "maghrib", "isha")
PRAYER_TITLES = {"fajr": "Fajr", "dhuhr": "Dhuhr", "asr": "Asr", "maghrib": "Maghrib", "isha": "Isha"}
EVENT_LENGTH = timedelta(minutes=15)

METHOD_NAMES = {
    CalculationMethod.ISNA: "ISNA",
    CalculationMethod.MWL: "MWL",
    CalculationMethod.EGYPTIAN: "Egyptian",
    CalculationMethod.KARACHI: "Karachi",
    CalculationMethod.UMM_AL_QURA: "Umm al-Qura",
}
ASR_NAMES = {AsrMethod.STANDARD: "standard Asr", AsrMethod.HANAFI: "Hanafi Asr"}


def source_description(prayer: PrayerTime) -> str:
    """Where the time came from, like "Calculated (ISNA, standard Asr)"."""
    parts = [METHOD_NAMES[prayer.method], ASR_NAMES[prayer.asr_method]]
    if prayer.high_latitude_rule:
        parts.append(prayer.high_latitude_rule.value.replace("_", " ") + " rule")
    return f"{prayer.source.capitalize()} ({', '.join(parts)})"


def event_end(start: datetime, length: timedelta = EVENT_LENGTH) -> datetime:
    """15 minutes after start (or length), counted in UTC so a clock change can't stretch it."""
    return (start.astimezone(UTC) + length).astimezone(start.tzinfo)


def save_day(db: Session, user_id: uuid.UUID, day: DailyPrayerTimes) -> list[PrayerEvent]:
    """Save (or update) one row per prayer, all marked pending, and commit.

    INSERT ... ON CONFLICT DO UPDATE does it in one step, so two requests at
    the same time still end up with one row per prayer.
    """
    for name in PRAYERS:
        prayer: PrayerTime = getattr(day, name)
        values = {
            "starts_at": prayer.time,
            "ends_at": event_end(prayer.time),
            "time_zone": day.timezone,
            "source_description": source_description(prayer),
            "sync_status": "pending",
        }
        db.execute(
            insert(PrayerEvent)
            .values(id=uuid.uuid4(), user_id=user_id, local_date=day.date, prayer=name, kind="prayer", **values)
            .on_conflict_do_update(
                index_elements=["user_id", "local_date", "prayer", "kind"], set_=values
            )
        )
    db.commit()
    return events_for_day(db, user_id, day.date)


def events_for_day(db: Session, user_id: uuid.UUID, local_date) -> list[PrayerEvent]:
    """One user's events for one day, Fajr first."""
    rows = db.scalars(
        select(PrayerEvent).where(PrayerEvent.user_id == user_id, PrayerEvent.local_date == local_date)
    ).all()
    return sorted(rows, key=lambda row: PRAYERS.index(row.prayer))


def google_event_id(row: PrayerEvent) -> str:
    # Google event IDs use 0-9 and a-v. Hex (0-9, a-f) fits inside that.
    return row.id.hex


def google_event(row: PrayerEvent) -> dict:
    zone = ZoneInfo(row.time_zone)
    event = {
        "id": google_event_id(row),
        # Rows from before milestone 4 have no title or description saved.
        "summary": row.summary or PRAYER_TITLES[row.prayer],
        "description": row.description or row.source_description,
        "start": {"dateTime": row.starts_at.astimezone(zone).isoformat(), "timeZone": row.time_zone},
        "end": {"dateTime": row.ends_at.astimezone(zone).isoformat(), "timeZone": row.time_zone},
        # "confirmed" brings an event back if the user had deleted it.
        "status": "confirmed",
        # Private: people who can see the user's calendar see "Busy", not
        # the details. Users can change it for an event in Google Calendar.
        "visibility": "private",
        # Private: only this app can see it. Lets later milestones match
        # Google events back to rows even if the event ID ever differs.
        "extendedProperties": {"private": {"appEventId": str(row.id)}},
    }
    # Only added when set, so events from before milestone 5 hash the same
    # and aren't sent again.
    if row.color_id:
        event["colorId"] = row.color_id
    if row.reminder_minutes is not None:
        event["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": row.reminder_minutes}],
        }
    return event


def event_hash(row: PrayerEvent) -> str:
    """A fingerprint of exactly what Google would get for this row.

    If it matches the hash saved when Google last confirmed the event,
    nothing changed, so there's no need to send it again.
    """
    body = json.dumps(google_event(row), sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


@dataclass
class SyncIncomplete(Exception):
    """Google failed partway. Rows not sent yet stay pending for the next run."""

    error: GoogleError
    saved: list[str]
    waiting: list[str]


def _write_event(calendar: GoogleCalendar, calendar_id: str, row: PrayerEvent) -> None:
    body = google_event(row)
    event_id = google_event_id(row)
    if row.google_calendar_id == calendar_id:
        # Sent to this calendar before, so update it.
        try:
            calendar.update_event(calendar_id, event_id, body)
            return
        except GoogleNotFound:
            pass  # gone from Google completely, so add it again
    try:
        calendar.insert_event(calendar_id, body)
    except GoogleConflict:
        # Already there, for example a timed out insert that actually worked.
        calendar.update_event(calendar_id, event_id, body)


class NotADriveBlock(Exception):
    """Something asked to delete an event the app may not delete."""


def delete_drive_block(calendar: GoogleCalendar, calendar_id: str, row: PrayerEvent, now: datetime) -> None:
    """Delete one future drive block the app made. The only delete the app does.

    Prayer blocks, past events, and anything the app didn't make are never deleted.
    """
    if row.kind != "drive" or row.starts_at <= now:
        raise NotADriveBlock(f"Refused to delete {row.kind} event {row.id}")
    if row.google_calendar_id != calendar_id:
        return  # it was in a calendar that's gone, so there's nothing to delete
    try:
        calendar.delete_event(calendar_id, google_event_id(row))
    except GoogleNotFound:
        pass  # already gone, for example the user deleted it


def send_to_google(
    db: Session, calendar: GoogleCalendar, calendar_id: str, rows: list[PrayerEvent], now: datetime
) -> None:
    """Send each row to Google, committing after each one.

    Committing one at a time means a failure on the 3rd prayer still
    remembers that the first 2 were sent.
    """
    for index, row in enumerate(rows):
        try:
            if row.sync_status == "delete_pending":
                delete_drive_block(calendar, calendar_id, row, now)
            else:
                _write_event(calendar, calendar_id, row)
        except GoogleError as error:
            row.last_error = str(error)
            db.commit()
            raise SyncIncomplete(
                error=error,
                saved=[r.prayer for r in rows[:index]],
                waiting=[r.prayer for r in rows[index:]],
            ) from error
        if row.sync_status == "delete_pending":
            # Gone from Google. No hash, so if it's needed again it's sent again.
            row.sync_status = "deleted"
            row.synced_hash = None
        else:
            row.google_calendar_id = calendar_id
            row.synced_hash = event_hash(row)
            row.sync_status = "synced"
        row.synced_at = datetime.now(UTC)
        row.last_error = None
        db.commit()
