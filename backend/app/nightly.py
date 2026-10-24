"""The nightly update: roll each user's 14-day window forward at 3:00 am.

How it avoids running twice or duplicating events:
1. Each job is saved before it runs, with the ID "nightly:{user_id}:{date}".
   Saving it again does nothing (INSERT ... ON CONFLICT DO NOTHING).
2. A job is claimed by switching it from "pending" to "running" in one
   UPDATE. Only one process can win that, even with two workers running.
3. The calendar update itself never duplicates (fixed event IDs, and
   unchanged events aren't sent), so even a retry after a crash is safe.

Why 3:00 am: on the spring daylight saving day, 2:00 to 2:59 am doesn't
exist in Toronto. 3:00 am always does there. A job is due once the local
clock reads 3:00 or later, so in a place where 3:00 itself is skipped
(Helsinki in spring), it runs at 4:00 instead of never.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.calendar_window import SetupIncomplete, refresh_calendar
from app.google_errors import CalendarAccessMissing, GoogleError, ReauthRequired
from app.models import GoogleToken, NightlyJob, User, UserSettings
from app.prayer_sync import SyncIncomplete

logger = logging.getLogger("app.nightly")

NIGHTLY_TIME = time(3, 0)
# A job "running" this long means its worker crashed or was stopped.
STUCK_AFTER = timedelta(minutes=15)
# Google errors are retried this long after, up to MAX_ATTEMPTS times a night.
RETRY_AFTER = timedelta(minutes=15)
MAX_ATTEMPTS = 5


def job_id(user_id: uuid.UUID, local_date: date) -> str:
    return f"nightly:{user_id}:{local_date.isoformat()}"


def due_date(now: datetime, time_zone: str) -> date:
    """The night whose job should have run by now, in the user's own time zone.

    Before 3:00 am it's still last night's job. From 3:00 am on, it's today's.
    """
    local = now.astimezone(ZoneInfo(time_zone))
    if local.time() >= NIGHTLY_TIME:
        return local.date()
    return local.date() - timedelta(days=1)


@dataclass
class JobResult:
    job_id: str
    status: str
    events_sent: int = 0
    message: str = ""


def save_job(db: Session, user_id: uuid.UUID, local_date: date) -> NightlyJob:
    """Save the job before running it. Saving the same job again changes nothing."""
    db.execute(
        insert(NightlyJob)
        .values(
            id=job_id(user_id, local_date),
            user_id=user_id,
            local_date=local_date,
            status="pending",
            attempts=0,
            events_sent=0,
        )
        .on_conflict_do_nothing()
    )
    db.commit()
    return db.get(NightlyJob, job_id(user_id, local_date), populate_existing=True)


def claim(db: Session, job: NightlyJob, now: datetime) -> bool:
    """Switch the job from pending to running. False if someone else got it first."""
    claimed = db.execute(
        update(NightlyJob)
        .where(NightlyJob.id == job.id, NightlyJob.status == "pending")
        .values(status="running", attempts=NightlyJob.attempts + 1, started_at=now, error=None)
        .returning(NightlyJob.id)
    ).first()
    db.commit()
    return claimed is not None


def _finish(db: Session, job_id_: str, status: str, now: datetime, sent: int = 0, error: str | None = None) -> JobResult:
    job = db.get(NightlyJob, job_id_, populate_existing=True)
    job.status = status
    job.events_sent = sent
    job.finished_at = now
    job.error = error
    job.retry_at = now + RETRY_AFTER if status == "failed" and job.attempts < MAX_ATTEMPTS else None
    db.commit()
    logger.info("%s %s, %d events sent", job.id, status, sent)
    return JobResult(job.id, status, sent, error or "")


def run_claimed_job(db: Session, http: httpx2.Client, job: NightlyJob, now: datetime) -> JobResult:
    """Update one user's calendar. Every error is caught, so one user can't stop the rest."""
    try:
        result = refresh_calendar(db, http, job.user_id, now)
    except SetupIncomplete:
        return _finish(db, job.id, "skipped", now, error="Setup isn't finished.")
    except (ReauthRequired, CalendarAccessMissing):
        # The token is already marked, so the website shows "Sign in again".
        return _finish(db, job.id, "needs_sign_in", now, error="Google sign-in expired.")
    except SyncIncomplete as incomplete:
        db.rollback()
        return _finish(db, job.id, "failed", now, len(incomplete.saved), str(incomplete.error))
    except GoogleError as error:
        db.rollback()
        return _finish(db, job.id, "failed", now, error=str(error))
    except Exception as error:  # noqa: BLE001 - a bug for one user must not stop everyone else
        db.rollback()
        logger.exception("%s crashed", job.id)
        return _finish(db, job.id, "failed", now, error=f"{type(error).__name__}: {error}")
    return _finish(db, job.id, "done", now, result.sent)


def _setup_users(db: Session, email: str | None = None) -> list[tuple[uuid.UUID, str, datetime]]:
    query = (
        select(UserSettings.user_id, UserSettings.time_zone, UserSettings.setup_completed_at)
        .join(User, User.id == UserSettings.user_id)
        .where(UserSettings.setup_completed_at.isnot(None), UserSettings.time_zone.isnot(None))
        .order_by(User.created_at)
    )
    if email is not None:
        query = query.where(User.email == email)
    return [tuple(row) for row in db.execute(query)]


def _make_retries_pending(db: Session, now: datetime) -> None:
    # A crashed worker left the job "running". Try it again.
    db.execute(
        update(NightlyJob)
        .where(NightlyJob.status == "running", NightlyJob.started_at < now - STUCK_AFTER)
        .values(status="pending")
    )
    # Google failed last time, and it's been long enough to try again.
    db.execute(
        update(NightlyJob)
        .where(
            NightlyJob.status == "failed",
            NightlyJob.retry_at.isnot(None),
            NightlyJob.retry_at <= now,
            NightlyJob.attempts < MAX_ATTEMPTS,
        )
        .values(status="pending")
    )
    # The user has signed in again since their job was skipped.
    signed_back_in = select(GoogleToken.user_id).where(GoogleToken.needs_reauth.is_(False))
    db.execute(
        update(NightlyJob)
        .where(NightlyJob.status == "needs_sign_in", NightlyJob.user_id.in_(signed_back_in))
        .values(status="pending")
    )
    db.commit()


def _skip_older_jobs(db: Session, user_id: uuid.UUID, newest: date) -> None:
    """A newer night covers everything an older unfinished one would have done."""
    db.execute(
        update(NightlyJob)
        .where(
            NightlyJob.user_id == user_id,
            NightlyJob.local_date < newest,
            NightlyJob.status.in_(("pending", "failed", "needs_sign_in")),
        )
        .values(status="skipped", error="Replaced by a newer night.", retry_at=None)
    )
    db.commit()


def run_due_jobs(engine: Engine, http: httpx2.Client, now: datetime) -> list[JobResult]:
    """Run every job that's due. The worker calls this every minute.

    Right after the worker starts, this is also the catch-up: if it's past
    3:00 am and today's job never ran (the server was off), it runs now.
    Only the newest night runs, since it rolls the whole window forward.
    """
    results = []
    with Session(engine, expire_on_commit=False) as db:
        _make_retries_pending(db, now)
        for user_id, time_zone, setup_completed_at in _setup_users(db):
            local_date = due_date(now, time_zone)
            if setup_completed_at >= datetime.combine(local_date, NIGHTLY_TIME, ZoneInfo(time_zone)):
                # That night was before setup. Finishing setup already filled the calendar.
                continue
            job = save_job(db, user_id, local_date)
            _skip_older_jobs(db, user_id, local_date)
            if job.status == "pending" and claim(db, job, now):
                results.append(run_claimed_job(db, http, job, now))
    return results


def run_now(
    engine: Engine, http: httpx2.Client, now: datetime, email: str | None = None, force: bool = False
) -> list[JobResult]:
    """Run today's job right away, for testing. Uses the same job IDs as the worker.

    Without force, a job that already ran today isn't run again. With force,
    it runs again, which is safe: unchanged events aren't sent.
    """
    results = []
    with Session(engine, expire_on_commit=False) as db:
        for user_id, time_zone, _ in _setup_users(db, email):
            local_date = now.astimezone(ZoneInfo(time_zone)).date()
            job = save_job(db, user_id, local_date)
            if job.status == "running":
                results.append(JobResult(job.id, "running", message="Already running."))
                continue
            if job.status != "pending":
                if not force:
                    results.append(
                        JobResult(job.id, job.status, job.events_sent, "Already ran today. Add --force to run it again.")
                    )
                    continue
                db.execute(update(NightlyJob).where(NightlyJob.id == job.id).values(status="pending"))
                db.commit()
            if claim(db, job, now):
                results.append(run_claimed_job(db, http, job, now))
            else:
                results.append(JobResult(job.id, "running", message="Another worker took it first."))
    return results
