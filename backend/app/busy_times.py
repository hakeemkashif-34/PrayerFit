"""When the user is busy on one day, from Google's free/busy.

Nothing is saved: busy times are asked for each time they're needed. Only
the user's primary calendar is checked, so the app's own Prayers calendar
never counts. Checking their other calendars would need another scope
(calendar.calendarlist.readonly, to find their IDs), which the app doesn't ask for.

Any problem (no free/busy access, a dead sign-in, a Google error) means no
busy times. The calendar update carries on as if the day were free.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.google_oauth import has_freebusy_scope
from app.auth.tokens import get_access_token
from app.google_calendar import GoogleCalendar
from app.google_errors import CalendarAccessMissing, GoogleError, ReauthRequired
from app.http_client import log_failure
from app.models import GoogleToken

logger = logging.getLogger("app.busy_times")


@dataclass(frozen=True)
class BusyTimes:
    # (start, end) pairs, time zone aware.
    busy: list[tuple[datetime, datetime]] = field(default_factory=list)
    # False when busy times couldn't be checked, so "free" means "unknown".
    checked: bool = False


def has_busy_access(db: Session, user_id: uuid.UUID) -> bool:
    row = db.scalars(select(GoogleToken).where(GoogleToken.user_id == user_id)).first()
    return row is not None and has_freebusy_scope(row.scopes)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def busy_on(db: Session, http: httpx2.Client, user_id: uuid.UUID, day: date, time_zone: str) -> BusyTimes:
    """Busy times on one local date, from midnight to midnight in the user's time zone."""
    if not has_busy_access(db, user_id):
        return BusyTimes()
    zone = ZoneInfo(time_zone)
    start = datetime.combine(day, datetime.min.time(), tzinfo=zone)
    # The next date's midnight, not 24 hours later, so a clock change can't shift it.
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=zone)
    started = time.monotonic()
    try:
        calendar = GoogleCalendar(http, lambda force: get_access_token(db, http, user_id, force))
        answer = calendar.free_busy(start.isoformat(), end.isoformat())
    except (GoogleError, ReauthRequired, CalendarAccessMissing) as error:
        # The calendar update reports a dead sign-in itself. Here it only means "not checked".
        log_failure("Google free/busy", type(error).__name__, started)
        return BusyTimes()
    primary = (answer.get("calendars") or {}).get("primary") or {}
    if primary.get("errors"):
        log_failure("Google free/busy", "errors for the primary calendar", started)
        return BusyTimes()
    try:
        busy = [(_parse(b["start"]).astimezone(zone), _parse(b["end"]).astimezone(zone)) for b in primary.get("busy", [])]
    except (KeyError, TypeError, ValueError):
        log_failure("Google free/busy", "answer couldn't be read", started)
        return BusyTimes()
    return BusyTimes(busy=busy, checked=True)
