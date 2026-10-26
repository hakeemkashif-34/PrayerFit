"""Calendar updates queued outside the nightly run.

A settings change or a masjid time change queues one. How it avoids
duplicate work:
1. One row per user, with the ID "update:{user_id}". Queuing again while
   it's waiting changes nothing, so 5 masjid changes become 1 update.
2. A job is claimed by switching it from "pending" to "running" in one
   UPDATE, so only one process runs it.
3. Queued again while it's running? requested_at moves past started_at,
   and the job goes back to pending when it finishes, so the new change
   isn't lost.
4. The update itself only sends changed events (see calendar_window.py),
   so running it twice is safe.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx2
from sqlalchemy import Engine, case, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.calendar_window import RefreshResult, SetupIncomplete, refresh_calendar
from app.google_errors import CalendarAccessMissing, GoogleError, ReauthRequired
from app.models import UpdateJob, UserJumuahMasjid, UserSettings
from app.prayer_sync import SyncIncomplete

logger = logging.getLogger("app.update_jobs")

STUCK_AFTER = timedelta(minutes=15)
RETRY_AFTER = timedelta(minutes=15)
MAX_ATTEMPTS = 5


def update_job_id(user_id: uuid.UUID) -> str:
    return f"update:{user_id}"


def queue_update(db: Session, user_id: uuid.UUID, reason: str, now: datetime) -> None:
    """Ask for this user's calendar to be updated. Doesn't commit."""
    job = UpdateJob.__table__
    db.execute(
        insert(UpdateJob)
        .values(
            id=update_job_id(user_id), user_id=user_id, status="pending", reason=reason,
            requested_at=now, attempts=0, events_sent=0,
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "reason": reason,
                "requested_at": now,
                # A running job finishes first, then sees requested_at and runs again.
                "status": case((job.c.status == "running", "running"), else_="pending"),
                "attempts": case((job.c.status == "running", job.c.attempts), else_=0),
                "retry_at": None,
            },
        )
    )


def users_of_masjid(db: Session, masjid_id: uuid.UUID) -> list[uuid.UUID]:
    """Everyone with this masjid as their main masjid or a Jumuah masjid."""
    main = select(UserSettings.user_id).where(
        UserSettings.main_masjid_choice == "masjid", UserSettings.main_masjid_id == masjid_id
    )
    jumuah = select(UserJumuahMasjid.user_id).where(UserJumuahMasjid.masjid_id == masjid_id)
    return list(db.scalars(main.union(jumuah)))


def claim(db: Session, user_id: uuid.UUID, now: datetime) -> bool:
    claimed = db.execute(
        update(UpdateJob)
        .where(UpdateJob.id == update_job_id(user_id), UpdateJob.status == "pending")
        .values(status="running", attempts=UpdateJob.attempts + 1, started_at=now, error=None)
        .returning(UpdateJob.id)
    ).first()
    db.commit()
    return claimed is not None


def _finish(db: Session, user_id: uuid.UUID, status: str, now: datetime, sent: int = 0, error: str | None = None) -> None:
    job = db.get(UpdateJob, update_job_id(user_id), populate_existing=True)
    job.events_sent = sent
    job.finished_at = now
    job.error = error
    if job.requested_at > job.started_at:
        # Queued again while this run was going. Run it once more.
        job.status, job.attempts, job.retry_at = "pending", 0, None
    else:
        job.status = status
        job.retry_at = now + RETRY_AFTER if status == "failed" and job.attempts < MAX_ATTEMPTS else None
    db.commit()
    logger.info("%s %s, %d events sent", job.id, job.status, sent)


def run_update(db: Session, http: httpx2.Client, user_id: uuid.UUID, now: datetime) -> RefreshResult | None:
    """Claim and run this user's queued update.

    Returns None if another process is already running it. Errors are
    recorded on the job and then raised again, so the website can say what happened.
    """
    if not claim(db, user_id, now):
        return None
    try:
        result = refresh_calendar(db, http, user_id, now)
    except SetupIncomplete:
        _finish(db, user_id, "skipped", now, error="Setup isn't finished.")
        raise
    except (ReauthRequired, CalendarAccessMissing):
        _finish(db, user_id, "needs_sign_in", now, error="Google sign-in expired.")
        raise
    except SyncIncomplete as incomplete:
        db.rollback()
        _finish(db, user_id, "failed", now, len(incomplete.saved), str(incomplete.error))
        raise
    except Exception as error:
        db.rollback()
        if not isinstance(error, GoogleError):
            logger.exception("%s crashed", update_job_id(user_id))
        _finish(db, user_id, "failed", now, error=f"{type(error).__name__}: {error}")
        raise
    _finish(db, user_id, "done", now, result.sent)
    return result


@dataclass
class UpdateResult:
    job_id: str
    status: str


def run_due_updates(engine: Engine, http: httpx2.Client, now: datetime) -> list[UpdateResult]:
    """Run every pending update. The worker calls this every minute."""
    results = []
    with Session(engine, expire_on_commit=False) as db:
        db.execute(
            update(UpdateJob)
            .where(
                or_(
                    # A crashed worker left it running.
                    (UpdateJob.status == "running") & (UpdateJob.started_at < now - STUCK_AFTER),
                    # Google failed last time, and it's been long enough.
                    (UpdateJob.status == "failed")
                    & UpdateJob.retry_at.isnot(None)
                    & (UpdateJob.retry_at <= now)
                    & (UpdateJob.attempts < MAX_ATTEMPTS),
                )
            )
            .values(status="pending")
        )
        db.commit()
        pending = db.scalars(
            select(UpdateJob.user_id).where(UpdateJob.status == "pending").order_by(UpdateJob.requested_at)
        ).all()
        for user_id in pending:
            try:
                run_update(db, http, user_id, now)
            except Exception:  # noqa: BLE001 - already saved on the job. One user can't stop the rest.
                pass
            job = db.get(UpdateJob, update_job_id(user_id), populate_existing=True)
            results.append(UpdateResult(job.id, job.status))
    return results
