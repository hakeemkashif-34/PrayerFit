"""Keep calls to a free service under its rate limit, across every process.

The last call time lives in one Postgres row. Each caller locks that row,
waits until enough time has passed, writes the new time, and commits. A
second caller blocks on the lock until the first is done, so calls are
spaced out even with several server processes running.
"""

import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import ApiThrottle

# Tests swap these so they don't really wait.
sleep = time.sleep


def utc_now() -> datetime:
    return datetime.now(UTC)


def wait_for_turn(db: Session, name: str, min_gap: timedelta) -> None:
    """Return once min_gap has passed since the last call to `name`. Commits."""
    long_ago = datetime(2000, 1, 1, tzinfo=UTC)
    db.execute(
        insert(ApiThrottle).values(name=name, last_request_at=long_ago).on_conflict_do_nothing()
    )
    row = db.execute(
        select(ApiThrottle).where(ApiThrottle.name == name).with_for_update()
    ).scalar_one()
    wait = (row.last_request_at + min_gap - utc_now()).total_seconds()
    if wait > 0:
        sleep(wait)
    row.last_request_at = utc_now()
    db.commit()  # releases the lock for the next caller
