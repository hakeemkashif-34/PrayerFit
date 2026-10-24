"""Find or create the user's "Prayers" calendar.

The app only ever writes to this one calendar, which it created itself.
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.google_calendar import GoogleCalendar
from app.google_errors import GoogleNotFound
from app.models import PrayerCalendar, PrayerEvent, User

CALENDAR_NAME = "Prayers"


def ensure_prayers_calendar(
    db: Session, calendar: GoogleCalendar, user_id: uuid.UUID, time_zone: str
) -> PrayerCalendar:
    """Return the user's Prayers calendar, creating it if it's missing.

    1. Never made one: create it and save its ID.
    2. Saved one still exists in Google: reuse it.
    3. The user deleted it in Google: create a new one, and mark their events
       as pending so they get written to the new calendar.
    """
    # Lock this user's row until the commit, so two requests at the same
    # time can't both decide there's no calendar and create two.
    db.execute(select(User.id).where(User.id == user_id).with_for_update())

    saved = db.scalars(select(PrayerCalendar).where(PrayerCalendar.user_id == user_id)).first()
    if saved is not None:
        try:
            calendar.get_calendar(saved.google_calendar_id)
            db.commit()  # releases the lock
            return saved
        except GoogleNotFound:
            pass  # deleted in Google, so make a new one below

    new_id = calendar.create_calendar(CALENDAR_NAME, time_zone)
    if saved is None:
        saved = PrayerCalendar(user_id=user_id, google_calendar_id=new_id, time_zone=time_zone)
        db.add(saved)
    else:
        db.execute(
            update(PrayerEvent)
            .where(
                PrayerEvent.user_id == user_id,
                PrayerEvent.google_calendar_id == saved.google_calendar_id,
            )
            .values(sync_status="pending")
        )
        saved.google_calendar_id = new_id
        saved.time_zone = time_zone
    db.commit()
    return saved
