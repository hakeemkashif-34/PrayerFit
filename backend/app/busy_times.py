"""When the user is busy, from Google's free/busy.

One call covers every date a calendar update plans. Nothing is saved: busy
times are asked for each time they're needed. Only
the user's primary calendar is checked, so the app's own Prayers calendar
never counts. Checking their other calendars would need another scope
(calendar.calendarlist.readonly, to find their IDs), which the app doesn't ask for.

Any problem (a dead sign-in, a Google error) means the busy times are
unknown ("failed"). The calendar update never fails because of it, and it
never undoes a move because of it (see calendar_window.save_window).
Without free/busy access ("no_access"), nothing moves at all.
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
    # "checked", "no_access" (the user didn't allow free/busy), or "failed"
    # (Google didn't answer properly, so the busy times are unknown).
    status: str = "no_access"

    @property
    def checked(self) -> bool:
        return self.status == "checked"


def has_busy_access(db: Session, user_id: uuid.UUID) -> bool:
    row = db.scalars(select(GoogleToken).where(GoogleToken.user_id == user_id)).first()
    return row is not None and has_freebusy_scope(row.scopes)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def busy_between(
    db: Session, http: httpx2.Client, user_id: uuid.UUID, first_day: date, last_day: date, time_zone: str
) -> BusyTimes:
    """Busy times from first_day's midnight to the end of the day after last_day.

    The extra day covers Isha on the last day, which can end after midnight.
    Both ends are local midnights, never "plus 24 hours", so a clock change
    can't shift them.
    """
    if not has_busy_access(db, user_id):
        return BusyTimes()
    zone = ZoneInfo(time_zone)
    start = datetime.combine(first_day, datetime.min.time(), tzinfo=zone)
    end = datetime.combine(last_day + timedelta(days=2), datetime.min.time(), tzinfo=zone)
    started = time.monotonic()
    failed = BusyTimes(status="failed")
    try:
        calendar = GoogleCalendar(http, lambda force: get_access_token(db, http, user_id, force))
        answer = calendar.free_busy(start.isoformat(), end.isoformat())
    except (GoogleError, ReauthRequired, CalendarAccessMissing) as error:
        # The calendar update reports a dead sign-in itself. Here it only means "unknown".
        log_failure("Google free/busy", type(error).__name__, started)
        return failed
    primary = (answer.get("calendars") or {}).get("primary") or {}
    if primary.get("errors"):
        log_failure("Google free/busy", "errors for the primary calendar", started)
        return failed
    try:
        busy = [(_parse(b["start"]).astimezone(zone), _parse(b["end"]).astimezone(zone)) for b in primary.get("busy", [])]
    except (KeyError, TypeError, ValueError):
        log_failure("Google free/busy", "answer couldn't be read", started)
        return failed
    return BusyTimes(busy=busy, status="checked")
