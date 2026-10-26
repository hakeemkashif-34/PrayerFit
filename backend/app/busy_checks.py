"""Check each user's busy times every 15 minutes, for today and tomorrow.

The nightly job covers all 14 days, but an event added at noon should move
that evening's Isha before Isha, not the next night. So every 15 minutes
the worker updates today and tomorrow for each user who allowed free/busy,
and Google only gets the events that changed.

How it avoids duplicate work:
1. Each check is saved before it runs, with the ID
   "busy:{user_id}:{15-minute block in UTC}". Saving it again does nothing.
2. It's claimed by switching it from "pending" to "running" in one UPDATE,
   so only one worker runs it.
3. The calendar update itself never duplicates events (see calendar_window.py).

If free/busy doesn't answer, the check stops and changes nothing. The next
block tries again.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx2
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.google_oauth import has_freebusy_scope
from app.calendar_window import SetupIncomplete, refresh_calendar
from app.google_errors import CalendarAccessMissing, GoogleError, ReauthRequired
from app.models import BusyCheckJob, GoogleToken, User, UserSettings
from app.prayer_sync import SyncIncomplete

logger = logging.getLogger("app.busy_checks")

CHECK_EVERY_MINUTES = 15
# Today and tomorrow.
CHECK_DAYS = 2
# Old check rows are deleted after this, so the table stays small.
KEEP_CHECKS_FOR = timedelta(days=2)


def block_start(now: datetime) -> datetime:
    """The start of the 15 minutes (in UTC) that now falls in."""
    utc = now.astimezone(UTC)
    return utc.replace(minute=utc.minute - utc.minute % CHECK_EVERY_MINUTES, second=0, microsecond=0)


def check_id(user_id: uuid.UUID, now: datetime) -> str:
    return f"busy:{user_id}:{block_start(now):%Y-%m-%dT%H:%M}"


@dataclass
class CheckResult:
    job_id: str
    status: str
    events_sent: int = 0


def users_to_check(db: Session) -> list[uuid.UUID]:
    """Users who finished setup, allowed free/busy, and have a working sign-in."""
    found = db.execute(
        select(UserSettings.user_id, GoogleToken.scopes)
        .join(User, User.id == UserSettings.user_id)
        .join(GoogleToken, GoogleToken.user_id == UserSettings.user_id)
        .where(
            UserSettings.setup_completed_at.isnot(None),
            UserSettings.time_zone.isnot(None),
            GoogleToken.needs_reauth.is_(False),
        )
        .order_by(User.created_at)
    )
    return [user_id for user_id, scopes in found if has_freebusy_scope(scopes)]


def save_check(db: Session, user_id: uuid.UUID, now: datetime) -> BusyCheckJob:
    """Save the check before running it. Saving the same one again changes nothing."""
    db.execute(
        insert(BusyCheckJob)
        .values(
            id=check_id(user_id, now), user_id=user_id, block_start=block_start(now), status="pending", events_sent=0
        )
        .on_conflict_do_nothing()
    )
    db.commit()
    return db.get(BusyCheckJob, check_id(user_id, now), populate_existing=True)


def claim(db: Session, job_id: str, now: datetime) -> bool:
    """Switch the check from pending to running. False if someone else got it first."""
    claimed = db.execute(
        update(BusyCheckJob)
        .where(BusyCheckJob.id == job_id, BusyCheckJob.status == "pending")
        .values(status="running", started_at=now)
        .returning(BusyCheckJob.id)
    ).first()
    db.commit()
    return claimed is not None


def _finish(db: Session, job_id: str, status: str, now: datetime, sent: int = 0, error: str | None = None) -> CheckResult:
    job = db.get(BusyCheckJob, job_id, populate_existing=True)
    job.status, job.events_sent, job.finished_at, job.error = status, sent, now, error
    db.commit()
    if sent or status != "done":
        logger.info("%s %s, %d events sent", job_id, status, sent)
    return CheckResult(job_id, status, sent)


def run_check(db: Session, http: httpx2.Client, user_id: uuid.UUID, job_id: str, now: datetime) -> CheckResult:
    """Update today and tomorrow for one user. Every error is caught, so one user can't stop the rest."""
    try:
        result = refresh_calendar(db, http, user_id, now, days=CHECK_DAYS, busy_check=True)
    except SetupIncomplete:
        return _finish(db, job_id, "skipped", now, error="Setup isn't finished.")
    except (ReauthRequired, CalendarAccessMissing):
        return _finish(db, job_id, "needs_sign_in", now, error="Google sign-in expired.")
    except SyncIncomplete as incomplete:
        db.rollback()
        return _finish(db, job_id, "failed", now, len(incomplete.saved), str(incomplete.error))
    except GoogleError as error:
        db.rollback()
        return _finish(db, job_id, "failed", now, error=str(error))
    except Exception as error:  # noqa: BLE001 - a bug for one user must not stop everyone else
        db.rollback()
        logger.exception("%s crashed", job_id)
        return _finish(db, job_id, "failed", now, error=f"{type(error).__name__}: {error}")
    if result.busy_unknown:
        # Nothing was changed. The next block tries again.
        return _finish(db, job_id, "failed", now, error="Free/busy didn't answer, so nothing was changed.")
    return _finish(db, job_id, "done", now, result.sent)


def run_due_checks(engine: Engine, http: httpx2.Client, now: datetime) -> list[CheckResult]:
    """Run this block's check for every user who hasn't had one yet. The worker calls this every minute."""
    results = []
    with Session(engine, expire_on_commit=False) as db:
        db.execute(delete(BusyCheckJob).where(BusyCheckJob.block_start < block_start(now) - KEEP_CHECKS_FOR))
        db.commit()
        for user_id in users_to_check(db):
            job = save_check(db, user_id, now)
            if job.status == "pending" and claim(db, job.id, now):
                results.append(run_check(db, http, user_id, job.id, now))
    return results
