"""The private /stats page's data. Only ADMIN_EMAIL can see it.

Everyone else, signed in or not, gets 404, the same as a page that
doesn't exist, so nobody can tell it's there. It only has counts and
public masjid names, never anything about a user.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.sessions import current_user
from app.clock import get_now
from app.config import admin_email
from app.db import get_db
from app.stats import Range, masjid_counts, user_totals

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


class MasjidOut(BaseModel):
    name: str
    users: int
    # False shows a "No MAWAQIT times" tag, so I know which to add.
    mawaqit_linked: bool


class StatsOut(BaseModel):
    # Masjids with at least 1 user, most users first.
    masjids: list[MasjidOut]


class PointOut(BaseModel):
    # The start of the hour or day in Toronto time, like "2026-10-26T14:00:00-04:00".
    start: str
    total: int


class UsersOut(BaseModel):
    # "hour" for 1 to 3 days, "day" for longer.
    step: Literal["hour", "day"]
    # Oldest first. Empty when nobody has ever signed up.
    points: list[PointOut]


@router.get("/admin/stats", response_model=StatsOut, dependencies=[Depends(require_admin)])
def read_stats(db: DbDep) -> StatsOut:
    return StatsOut(
        masjids=[MasjidOut(name=m.name, users=m.users, mawaqit_linked=m.mawaqit_linked) for m in masjid_counts(db)],
    )


@router.get("/admin/stats/users", response_model=UsersOut, dependencies=[Depends(require_admin)])
def read_user_totals(db: DbDep, now: NowDep, range: Range = "7d") -> UsersOut:  # noqa: A002 - the query is ?range=
    """Total users over time for the graph. The page asks again each time the dropdown changes."""
    step, points = user_totals(db, now, range)
    return UsersOut(step=step, points=[PointOut(start=p.start.isoformat(), total=p.total) for p in points])
