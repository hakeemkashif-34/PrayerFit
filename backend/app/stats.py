"""Usage stats: counts only, never emails, names, or any other user details.

1. Signed up: everyone who ever signed in.
2. Finished setup.
3. Active: the calendar was updated (the nightly job, a settings change,
   or a 5-minute check finished) in the last 2 days.
4. New this week: signed in for the first time in the last 7 days.

The worker saves these 4 numbers once a day (usage_stats), so there's a
history for the /stats page's graph.
"""

import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx2
from sqlalchemy import Engine, func, select, union
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import BusyCheckJob, NightlyJob, UpdateJob, UsageStats, User, UserSettings
from app.prayer_times import DEFAULT_TIMEZONE

ACTIVE_FOR = timedelta(days=2)
NEW_FOR = timedelta(days=7)
# Saved each day once the nightly jobs (3:00 am) are done, so "active" counts last night.
SAVE_AFTER = time(4, 0)


@dataclass(frozen=True)
class Counts:
    signed_up: int
    finished_setup: int
    active: int
    new_this_week: int


def active_user_ids(db: Session, now: datetime) -> set[uuid.UUID]:
    since = now - ACTIVE_FOR
    jobs = union(
        select(NightlyJob.user_id).where(NightlyJob.status == "done", NightlyJob.finished_at >= since),
        select(UpdateJob.user_id).where(UpdateJob.status == "done", UpdateJob.finished_at >= since),
        select(BusyCheckJob.user_id).where(BusyCheckJob.status == "done", BusyCheckJob.finished_at >= since),
    )
    return set(db.scalars(select(jobs.subquery().c.user_id)))


def counts(db: Session, now: datetime) -> Counts:
    return Counts(
        signed_up=db.scalar(select(func.count()).select_from(User)),
        finished_setup=db.scalar(
            select(func.count()).select_from(UserSettings).where(UserSettings.setup_completed_at.isnot(None))
        ),
        active=len(active_user_ids(db, now)),
        new_this_week=db.scalar(select(func.count()).select_from(User).where(User.created_at >= now - NEW_FOR)),
    )


def stats_lines(found: Counts) -> list[str]:
    """What `python -m app.admin stats` prints."""
    return [
        f"Signed up: {found.signed_up}",
        f"Finished setup: {found.finished_setup}",
        f"Active (calendar updated in the last 2 days): {found.active}",
        f"New this week: {found.new_this_week}",
    ]


def stats_day(now: datetime) -> date | None:
    """Today's date in the app's time zone, once it's past 4:00 am there. None before that."""
    local = now.astimezone(ZoneInfo(DEFAULT_TIMEZONE))
    return local.date() if local.time() >= SAVE_AFTER else None


def save_daily_stats(engine: Engine, http: httpx2.Client, now: datetime) -> bool:
    """Save today's counts once. The date is the row's ID, so running again does nothing.

    The worker calls this every minute. True when it saved a new row.
    """
    day = stats_day(now)
    if day is None:
        return False
    with Session(engine) as db:
        if db.get(UsageStats, day) is not None:
            return False
        saved = db.execute(
            insert(UsageStats)
            .values(day=day, saved_at=now, **asdict(counts(db, now)))
            .on_conflict_do_nothing()
            .returning(UsageStats.day)
        ).first()
        db.commit()
        return saved is not None


def history(db: Session) -> list[UsageStats]:
    return list(db.scalars(select(UsageStats).order_by(UsageStats.day)))
