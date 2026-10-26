"""The private /stats page's data. Only ADMIN_EMAIL can see it.

Everyone else, signed in or not, gets 404, the same as a page that
doesn't exist, so nobody can tell it's there. It only has counts and
public masjid names, never anything about a user.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.sessions import current_user
from app.clock import get_now
from app.config import admin_email
from app.db import get_db
from app.stats import daily_totals, masjid_counts, total_users

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
    # Signed up that day, and the total so far.
    signed_up: int
    total: int


class MasjidOut(BaseModel):
    name: str
    users: int
    # False shows a "No MAWAQIT times" tag, so I know which to add.
    mawaqit_linked: bool


class StatsOut(BaseModel):
    total_users: int
    # One point per day, oldest first, for the graph.
    history: list[Day]
    # Masjids with at least 1 user, most users first.
    masjids: list[MasjidOut]


@router.get("/admin/stats", response_model=StatsOut, dependencies=[Depends(require_admin)])
def read_stats(db: DbDep, now: NowDep) -> StatsOut:
    return StatsOut(
        total_users=total_users(db),
        history=[Day(day=d.day.isoformat(), signed_up=d.signed_up, total=d.total) for d in daily_totals(db, now)],
        masjids=[MasjidOut(name=m.name, users=m.users, mawaqit_linked=m.mawaqit_linked) for m in masjid_counts(db)],
    )
