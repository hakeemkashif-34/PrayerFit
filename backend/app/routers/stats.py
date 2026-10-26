"""The private /stats page's data. Only ADMIN_EMAIL can see it.

Everyone else, signed in or not, gets 404, the same as a page that
doesn't exist, so nobody can tell it's there. It only has counts and
public masjid details, never anything about a user.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.sessions import current_user
from app.clock import get_now
from app.config import admin_email
from app.db import get_db
from app.masjid_times.freshness import Freshness, freshness
from app.models import Masjid, MasjidSource, UserSettings
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


class UnlinkedMasjid(BaseModel):
    # The ID is what `python -m app.admin link-mawaqit --masjid <id>` needs.
    id: str
    name: str
    users: int


class StatsOut(BaseModel):
    signed_up: int
    finished_setup: int
    active: int
    new_this_week: int
    # One point per day, oldest first, for the graph.
    history: list[Day]
    # Linked masjids whose read is failing or older than 24 hours.
    masjid_times: list[MasjidTimesProblem]
    # Masjids someone picked that aren't linked to MAWAQIT yet, most users first.
    unlinked_masjids: list[UnlinkedMasjid]


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


def unlinked_masjids(db: Session) -> list[UnlinkedMasjid]:
    """Main masjids with no MAWAQIT link, and how many users have each, so I know which to link first.

    A count, never who the users are. A masjid picked by its address has no
    name, so its address is shown instead.
    """
    users = func.count(UserSettings.user_id)
    rows = db.execute(
        select(Masjid, users)
        .join(UserSettings, UserSettings.main_masjid_id == Masjid.id)
        .outerjoin(MasjidSource, MasjidSource.masjid_id == Masjid.id)
        .where(UserSettings.main_masjid_choice == "masjid", MasjidSource.masjid_id.is_(None))
        .group_by(Masjid.id)
        .order_by(users.desc(), Masjid.name)
    )
    return [
        UnlinkedMasjid(id=str(masjid.id), name=masjid.name or masjid.address or "Unnamed masjid", users=count)
        for masjid, count in rows
    ]


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
        unlinked_masjids=unlinked_masjids(db),
    )
