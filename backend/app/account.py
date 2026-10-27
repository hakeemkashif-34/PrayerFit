"""Delete my account: remove everything PrayerFit has about a user.

In order:
1. Delete the app's "Prayers" calendar from their Google account, so every
   prayer event goes with it. That's the only thing in their Google account
   the app ever touches. The calendar.app.created scope can't reach anything else.
2. Revoke the app's access to their Google account.
3. Delete the user row. Every table that holds their data points at it with
   ON DELETE CASCADE, so Postgres deletes the rest in the same step:
   sessions, Google tokens, settings, weekly prayers, the Prayers calendar
   row, prayer events, drive times, and every job. Masjids they typed in by
   address go too (created_by_user_id). Only that user can pick one of
   those, so no one else is using it.

If Google can't be reached, steps 1 and 2 are skipped, and everything
stored is still deleted. The website then tells them how to remove the
Prayers calendar themselves.

It holds the same per-user lock as calendar updates, so a 5-minute check
or the nightly job can't write to the calendar halfway through.
"""

import logging
import uuid
from dataclasses import dataclass

import httpx2
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.crypto import decrypt
from app.auth.google_oauth import revoke_token
from app.auth.tokens import get_access_token
from app.calendar_window import user_lock
from app.google_calendar import GoogleCalendar
from app.google_errors import (
    CalendarAccessMissing,
    GoogleError,
    GoogleNotFound,
    ReauthRequired,
)
from app.models import GoogleToken, PrayerCalendar, User
from app.stats import record_deletion

logger = logging.getLogger("app.account")


@dataclass(frozen=True)
class Deleted:
    # False when the Prayers calendar couldn't be deleted or the access couldn't be revoked.
    google_cleaned: bool


def _delete_prayers_calendar(db: Session, http: httpx2.Client, user_id: uuid.UUID) -> bool:
    row = db.scalars(select(PrayerCalendar).where(PrayerCalendar.user_id == user_id)).first()
    if row is None:
        return True
    calendar = GoogleCalendar(http, lambda force: get_access_token(db, http, user_id, force_refresh=force))
    try:
        calendar.delete_calendar(row.google_calendar_id)
    except GoogleNotFound:
        # They already deleted it themselves.
        return True
    except (ReauthRequired, CalendarAccessMissing, GoogleError):
        return False
    return True


def _revoke_access(db: Session, http: httpx2.Client, user_id: uuid.UUID) -> bool:
    row = db.scalars(select(GoogleToken).where(GoogleToken.user_id == user_id)).first()
    if row is None or row.refresh_token_encrypted is None:
        return True
    try:
        revoke_token(http, decrypt(row.refresh_token_encrypted))
    except GoogleError:
        return False
    return True


def delete_account(db: Session, http: httpx2.Client, user_id: uuid.UUID) -> Deleted:
    with user_lock(db, user_id):
        try:
            calendar_gone = _delete_prayers_calendar(db, http, user_id)
            access_revoked = _revoke_access(db, http, user_id)
        except Exception:  # noqa: BLE001 - a bug on Google's side must never stop the delete
            db.rollback()
            logger.exception("Cleaning up Google for user %s failed", user_id)
            calendar_gone = access_revoked = False
        db.execute(delete(User).where(User.id == user_id))
        # The /stats graph goes down by 1. Same commit, so it can't count a delete that didn't happen.
        record_deletion(db)
        db.commit()
    # Only the user ID and whether Google worked. Never anything else about them.
    logger.info("Deleted user %s (Google cleaned up: %s)", user_id, calendar_gone and access_revoked)
    return Deleted(google_cleaned=calendar_gone and access_revoked)
