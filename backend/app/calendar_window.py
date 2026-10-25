"""Keep the next 14 days of prayers in the user's Prayers calendar.

1. Work out every prayer for today and the next 13 days from the saved setup.
2. Save each one in prayer_events. New rows are added. Future rows are
   updated. Rows that already started are left alone.
3. A row only goes back to "pending" if what Google would get changed
   (see event_hash). So Google only gets the events that changed.
4. Send the pending rows to Google, using the duplicate-proof code in
   prayer_sync.py.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.tokens import get_access_token
from app.google_calendar import GoogleCalendar
from app.locks import advisory_lock
from app.models import PrayerEvent
from app.prayer_sync import PRAYER_TITLES, PRAYERS, event_end, event_hash, send_to_google, source_description
from app.prayer_times import DailyPrayerTimes, calculate_prayer_times
from app.prayer_times.methods import METHODS
from app.prayers_calendar import ensure_prayers_calendar
from app.user_settings import Setup, load_setup

WINDOW_DAYS = 14
IQAMAH_NOTE = "Iqamah times not added yet, so this is the calculated prayer time."


class SetupIncomplete(Exception):
    """The user hasn't finished setup, so there's nothing to put in the calendar."""


def window_dates(first_day: date, days: int = WINDOW_DAYS) -> list[date]:
    # Adding days to a date moves the calendar date. It never adds 24 hours,
    # so a daylight saving change can't skip or repeat a day.
    return [first_day + timedelta(days=n) for n in range(days)]


def _clock(moment: datetime) -> str:
    """12:46:57 pm"""
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02}:{moment.second:02} {'am' if moment.hour < 12 else 'pm'}"


def dhuhr_note(day: DailyPrayerTimes) -> str:
    """Why Dhuhr is a minute or so after solar noon."""
    offset = METHODS[day.method].dhuhr_minutes_after_noon
    noon = (day.dhuhr.exact_time - timedelta(minutes=offset)).astimezone(ZoneInfo(day.timezone))
    if offset == 0:
        return f"Starts at solar noon ({_clock(noon)}), rounded up to the minute."
    return (
        f"Starts {offset} minute after solar noon ({_clock(noon)}), once the whole sun "
        "has passed overhead, then rounded up to the minute."
    )


def event_title(prayer: str, place: str, masjid_label: str | None) -> str:
    """"Fajr at home" or "Dhuhr at KMA"."""
    where = masjid_label if place == "masjid" else "home"
    return f"{PRAYER_TITLES[prayer]} at {where}"


@dataclass(frozen=True)
class PlannedEvent:
    local_date: date
    prayer: str
    starts_at: datetime
    ends_at: datetime
    time_zone: str
    source_description: str
    place: str
    masjid_id: uuid.UUID | None
    summary: str
    description: str

    def values(self) -> dict:
        return {
            "starts_at": self.starts_at,
            "ends_at": self.ends_at,
            "time_zone": self.time_zone,
            "source_description": self.source_description,
            "place": self.place,
            "masjid_id": self.masjid_id,
            "summary": self.summary,
            "description": self.description,
        }


def plan_day(setup: Setup, local_date: date) -> list[PlannedEvent]:
    """The 5 events for one day. Until iqamah times exist (milestone 5),
    every event uses the calculated time, even at the masjid."""
    day = calculate_prayer_times(
        setup.latitude, setup.longitude, local_date, setup.time_zone, setup.method, setup.asr_method
    )
    events = []
    for name in PRAYERS:
        prayer = getattr(day, name)
        place = setup.place_for(local_date.weekday(), name)
        lines = [source_description(prayer)]
        if place == "masjid":
            lines.append(IQAMAH_NOTE)
        if name == "dhuhr":
            lines.append(dhuhr_note(day))
        events.append(
            PlannedEvent(
                local_date=local_date,
                prayer=name,
                starts_at=prayer.time,
                ends_at=event_end(prayer.time),
                time_zone=day.timezone,
                source_description=source_description(prayer),
                place=place,
                masjid_id=setup.masjid.id if place == "masjid" else None,
                summary=event_title(name, place, setup.masjid_label),
                description="\n".join(lines),
            )
        )
    return events


def rows_for_dates(db: Session, user_id: uuid.UUID, dates: list[date]) -> list[PrayerEvent]:
    rows = db.scalars(
        select(PrayerEvent).where(PrayerEvent.user_id == user_id, PrayerEvent.local_date.in_(dates))
    ).all()
    return sorted(rows, key=lambda r: (r.local_date, PRAYERS.index(r.prayer)))


def save_window(
    db: Session, user_id: uuid.UUID, setup: Setup, dates: list[date], now: datetime
) -> None:
    """Save the planned events. Only changed future rows become pending. Commits."""
    existing = {(r.local_date, r.prayer): r for r in rows_for_dates(db, user_id, dates)}
    for local_date in dates:
        for planned in plan_day(setup, local_date):
            row = existing.get((local_date, planned.prayer))
            if row is None:
                # DO NOTHING: if another run added it a moment ago, keep theirs.
                db.execute(
                    insert(PrayerEvent)
                    .values(
                        id=uuid.uuid4(),
                        user_id=user_id,
                        local_date=local_date,
                        prayer=planned.prayer,
                        sync_status="pending",
                        **planned.values(),
                    )
                    .on_conflict_do_nothing(index_elements=["user_id", "local_date", "prayer"])
                )
                continue
            if row.starts_at <= now:
                continue  # already started, so it's the past. Leave it alone.
            for key, value in planned.values().items():
                setattr(row, key, value)
            if event_hash(row) != row.synced_hash:
                row.sync_status = "pending"
    db.commit()


def user_lock(db: Session, user_id: uuid.UUID):
    """Only one calendar update per user at a time.

    The website and the nightly job could both update the same user at
    once. The advisory lock makes the second one wait.
    """
    return advisory_lock(db, f"calendar:{user_id}")


@dataclass
class RefreshResult:
    rows: list[PrayerEvent]  # every row in the window
    sent: int  # how many went to Google


def refresh_calendar(
    db: Session,
    http: httpx2.Client,
    user_id: uuid.UUID,
    now: datetime,
    days: int = WINDOW_DAYS,
    first_day: date | None = None,
) -> RefreshResult:
    """Bring the user's calendar up to date for today plus days - 1.

    Raises SetupIncomplete, ReauthRequired, CalendarAccessMissing, or
    SyncIncomplete (Google failed partway; the rest stay pending).
    """
    with user_lock(db, user_id):
        setup = load_setup(db, user_id)
        if setup is None:
            raise SetupIncomplete()
        if first_day is None:
            first_day = now.astimezone(ZoneInfo(setup.time_zone)).date()
        dates = window_dates(first_day, days)
        save_window(db, user_id, setup, dates, now)

        # Get (or refresh) the token first, so a dead sign-in is reported
        # before any Google call. The rows above stay saved either way.
        get_access_token(db, http, user_id)
        calendar = GoogleCalendar(http, lambda force: get_access_token(db, http, user_id, force))
        prayers_calendar = ensure_prayers_calendar(db, calendar, user_id, setup.time_zone)

        # Read again: a recreated calendar marks every row pending.
        rows = rows_for_dates(db, user_id, dates)
        pending = [r for r in rows if r.sync_status == "pending"]
        send_to_google(db, calendar, prayers_calendar.google_calendar_id, pending)
        return RefreshResult(rows=rows, sent=len(pending))
