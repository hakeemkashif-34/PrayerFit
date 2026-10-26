"""The private /stats page's data. Only ADMIN_EMAIL can see it.

Everyone else, signed in or not, gets 404, the same as a page that
doesn't exist, so nobody can tell it's there. It only has counts and
public masjid details, never anything about a user.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.sessions import current_user
from app.clock import get_now
from app.config import admin_email
from app.db import get_db
from app.masjid_times.freshness import Freshness, freshness
from app.models import Masjid, MasjidSource
from app.stats import counts, history

router = APIRouter(tags=["stats"])

DbDep = Annotated[Session, Depends(get_db)]
NowDep = Annotated[datetime, Depends(get_now)]


def require_admin(request: Request, db: DbDep) -> None:
    """404 unless the signed-in user is ADMIN_EMAIL."""
    allowed = admin_email()
    try:
        user = current_user(request, db)
    except HTTPException:
        user = None
    if allowed is None or user is None or user.email.strip().lower() != allowed:
        raise HTTPException(status_code=404, detail="Not Found")


class Day(BaseModel):
    day: str
    signed_up: int
    active: int


class MasjidTimesProblem(BaseModel):
    name: str
    source: str
    last_success_at: datetime | None
    error: str | None


class StatsOut(BaseModel):
    signed_up: int
    finished_setup: int
    active: int
    new_this_week: int
    # One point per day, oldest first, for the graph.
    history: list[Day]
    # Linked masjids whose read is failing or older than 24 hours.
    masjid_times: list[MasjidTimesProblem]


def masjid_problems(db: Session, now: datetime) -> list[MasjidTimesProblem]:
    problems = []
    for source, masjid in db.execute(
        select(MasjidSource, Masjid).join(Masjid, Masjid.id == MasjidSource.masjid_id).order_by(Masjid.name)
    ):
        failing = source.consecutive_failures > 0 or source.last_error is not None
        if failing or freshness(source.last_success_at, now) is not Freshness.FRESH:
            problems.append(
                MasjidTimesProblem(
                    name=masjid.name or "Unnamed masjid", source=source.source,
                    last_success_at=source.last_success_at, error=source.last_error,
                )
            )
    return problems


@router.get("/admin/stats", response_model=StatsOut, dependencies=[Depends(require_admin)])
def read_stats(db: DbDep, now: NowDep) -> StatsOut:
    found = counts(db, now)
    return StatsOut(
        signed_up=found.signed_up,
        finished_setup=found.finished_setup,
        active=found.active,
        new_this_week=found.new_this_week,
        history=[Day(day=row.day.isoformat(), signed_up=row.signed_up, active=row.active) for row in history(db)],
        masjid_times=masjid_problems(db, now),
    )
