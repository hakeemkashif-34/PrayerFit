"""Read each linked masjid's times, at most once every 6 hours.

One job per masjid per 6-hour block, never one per user. The job ID is
"{source}:{masjid_id}:{block}", saved before it runs, so a second worker
or a retry finds the same job instead of fetching again.

After a 403, a 429, or 3 failures in a row, the masjid waits 24 hours.
A failed fetch never touches the saved times, so the last good ones
stay in use (see freshness.py for how long).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy import Engine, exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.geo.timezones import masjid_time_zone
from app.masjid_times.source import SourceBlocked, SourceError, get_source
from app.masjid_times.store import save_days
from app.models import Masjid, MasjidFetchJob, MasjidSource, UserSettings
from app.update_jobs import queue_update, users_of_masjid

logger = logging.getLogger("app.masjid_times")

BLOCK_HOURS = 6
WAIT_AFTER_BLOCK = timedelta(hours=24)
MAX_FAILURES_IN_A_ROW = 3
STUCK_AFTER = timedelta(minutes=15)
# How many days of times to save from each fetch. The calendar uses 14.
FETCH_DAYS = 30


def block_start(now: datetime) -> datetime:
    """The start of the 6-hour block (00:00, 06:00, 12:00, 18:00 UTC) that now is in."""
    utc = now.astimezone(UTC)
    return utc.replace(hour=utc.hour - utc.hour % BLOCK_HOURS, minute=0, second=0, microsecond=0)


def fetch_job_id(source: str, masjid_id: uuid.UUID, now: datetime) -> str:
    return f"{source}:{masjid_id}:{block_start(now):%Y-%m-%dT%H}"


@dataclass
class FetchResult:
    job_id: str
    status: str  # done, failed, blocked, or skipped
    changed: bool = False
    message: str = ""


def _has_users(masjid_id):
    # Someone's main masjid. Jumuah is at the main masjid too.
    return exists().where(UserSettings.main_masjid_choice == "masjid", UserSettings.main_masjid_id == masjid_id)


def due_masjids(db: Session, now: datetime) -> list[uuid.UUID]:
    """Linked masjids someone uses, that aren't waiting out a block."""
    return list(
        db.scalars(
            select(MasjidSource.masjid_id).where(
                or_(MasjidSource.retry_after.is_(None), MasjidSource.retry_after <= now),
                _has_users(MasjidSource.masjid_id),
            )
        )
    )


def _save_job(db: Session, job_id: str, masjid_id: uuid.UUID) -> MasjidFetchJob:
    db.execute(insert(MasjidFetchJob).values(id=job_id, masjid_id=masjid_id, status="pending").on_conflict_do_nothing())
    db.commit()
    return db.get(MasjidFetchJob, job_id, populate_existing=True)


def _claim(db: Session, job_id: str, now: datetime) -> bool:
    claimed = db.execute(
        update(MasjidFetchJob)
        .where(MasjidFetchJob.id == job_id, MasjidFetchJob.status == "pending")
        .values(status="running", started_at=now, error=None)
        .returning(MasjidFetchJob.id)
    ).first()
    db.commit()
    return claimed is not None


def _finish(db: Session, job_id: str, status: str, now: datetime, error: str | None = None) -> None:
    job = db.get(MasjidFetchJob, job_id, populate_existing=True)
    job.status, job.finished_at, job.error = status, now, error
    db.commit()


def run_fetch(db: Session, http: httpx2.Client, masjid_id: uuid.UUID, now: datetime, force: bool = False) -> FetchResult:
    """Fetch one masjid's times, if this block's job hasn't run yet.

    force runs it again in the same block, for the admin command. It still
    respects a 24-hour wait after a block.
    """
    source_row = db.get(MasjidSource, masjid_id)
    if source_row is None:
        return FetchResult("", "skipped", message="This masjid isn't linked to a source.")
    job_id = fetch_job_id(source_row.source, masjid_id, now)
    if source_row.retry_after is not None and source_row.retry_after > now:
        return FetchResult(job_id, "skipped", message=f"Waiting until {source_row.retry_after:%Y-%m-%d %H:%M} UTC.")
    job = _save_job(db, job_id, masjid_id)
    if force and job.status in ("done", "failed", "blocked"):
        db.execute(update(MasjidFetchJob).where(MasjidFetchJob.id == job_id).values(status="pending"))
        db.commit()
    if not _claim(db, job_id, now):
        return FetchResult(job_id, "skipped", message="Already fetched in this 6-hour block.")

    source = get_source(source_row.source)
    masjid = db.get(Masjid, masjid_id)
    today = now.astimezone(ZoneInfo(masjid_time_zone(masjid))).date()
    source_row = db.get(MasjidSource, masjid_id, populate_existing=True)
    source_row.last_attempt_at = now
    try:
        days = source.fetch(http, source_row.external_id, today, FETCH_DAYS)
    except SourceError as error:
        db.rollback()
        source_row = db.get(MasjidSource, masjid_id, populate_existing=True)
        source_row.last_attempt_at = now
        source_row.consecutive_failures += 1
        source_row.last_error = str(error)
        blocked = isinstance(error, SourceBlocked) or source_row.consecutive_failures >= MAX_FAILURES_IN_A_ROW
        if blocked:
            source_row.retry_after = now + WAIT_AFTER_BLOCK
        db.commit()
        # Only the masjid's ID and the reason. Never an address or anything about a user.
        logger.warning("%s fetch for masjid %s failed: %s", source.label, masjid_id, error)
        status = "blocked" if blocked else "failed"
        _finish(db, job_id, status, now, str(error))
        return FetchResult(job_id, status, message=str(error))

    changed = save_days(db, masjid_id, source.name, days, now)
    source_row.last_success_at = now
    source_row.consecutive_failures = 0
    source_row.retry_after = None
    source_row.last_error = None
    if changed:
        source_row.last_changed_at = now
        for user_id in users_of_masjid(db, masjid_id):
            queue_update(db, user_id, source.name, now)
    db.commit()
    _finish(db, job_id, "done", now)
    logger.info("%s fetch for masjid %s done, %s", source.label, masjid_id, "times changed" if changed else "no change")
    return FetchResult(job_id, "done", changed=changed)


def run_due_fetches(engine: Engine, http: httpx2.Client, now: datetime) -> list[FetchResult]:
    """Fetch every masjid that's due. The worker calls this every minute."""
    results = []
    with Session(engine, expire_on_commit=False) as db:
        # A crashed worker left a fetch running. Let it try again.
        db.execute(
            update(MasjidFetchJob)
            .where(MasjidFetchJob.status == "running", MasjidFetchJob.started_at < now - STUCK_AFTER)
            .values(status="pending")
        )
        db.commit()
        for masjid_id in due_masjids(db, now):
            result = run_fetch(db, http, masjid_id, now)
            if result.status != "skipped":
                results.append(result)
    return results
