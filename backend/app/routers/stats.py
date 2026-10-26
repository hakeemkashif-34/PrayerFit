"""The private /stats page's data. Only ADMIN_EMAIL can see it.

Everyone else, signed in or not, gets 404, the same as a page that
doesn't exist, so nobody can tell it's there. It only has counts and
public masjid details, never anything about a user.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.auth.sessions import current_user
from app.clock import get_now
from app.config import admin_email
from app.db import get_db
from app.masjid_times.freshness import Freshness, freshness
from app.masjid_times.match import match
from app.masjid_times.mawaqit import page_url
from app.masjid_times.mawaqit_list import listed
from app.models import Masjid, MasjidSource, MawaqitListEntry, UserSettings
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


class NoMatchMasjid(BaseModel):
    # The ID is what `python -m app.admin link-mawaqit --masjid <id>` needs.
    id: str
    name: str
    users: int
    # Why it wasn't linked, like "No listed masjid within 200 m".
    reason: str


class AutoLink(BaseModel):
    """An automatic link, so I can spot-check it."""

    id: str
    # The masjid's name on the map, and the name on my list.
    name: str
    list_name: str
    mawaqit_url: str
    distance_m: int | None
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
    # Masjids linked automatically from my list, newest first.
    auto_links: list[AutoLink]
    # Masjids someone picked with no MAWAQIT match, most users first, so I know which to add.
    no_match_masjids: list[NoMatchMasjid]


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


def _name(masjid: Masjid) -> str:
    # A masjid picked by its address is where one user said it is, so the address is never shown.
    return masjid.name or "(no name, picked by address)"


def _users():
    return func.count(UserSettings.user_id)


def _picked(query):
    return query.join(UserSettings, UserSettings.main_masjid_id == Masjid.id).where(
        UserSettings.main_masjid_choice == "masjid"
    )


def no_match_masjids(db: Session) -> list[NoMatchMasjid]:
    """Main masjids with no MAWAQIT link, and how many users have each, so I know which to add first.

    A count, never who the users are. The reason is worked out again from
    the list, so it's always up to date.
    """
    users = _users()
    entries = listed(db)
    rows = db.execute(
        _picked(select(Masjid, users))
        .outerjoin(MasjidSource, MasjidSource.masjid_id == Masjid.id)
        .where(MasjidSource.masjid_id.is_(None))
        .group_by(Masjid.id)
        .order_by(users.desc(), Masjid.name)
    )
    out = []
    for masjid, count in rows:
        found = match(masjid.latitude, masjid.longitude, masjid.name, entries)
        if masjid.no_auto_link:
            reason = "Unlinked by hand"
        elif found.status == "unclear":
            reason = f"{len(found.candidates)} listed masjids are close, so it wasn't linked"
        else:
            reason = "No listed masjid within 200 m"
        out.append(NoMatchMasjid(id=str(masjid.id), name=_name(masjid), users=count, reason=reason))
    return out


def auto_links(db: Session) -> list[AutoLink]:
    users = _users()
    # Every automatic link, even one nobody has saved as their masjid yet (0 users).
    rows = db.execute(
        select(Masjid, MasjidSource, MawaqitListEntry.name, users)
        .join(MasjidSource, MasjidSource.masjid_id == Masjid.id)
        .outerjoin(
            UserSettings,
            and_(UserSettings.main_masjid_id == Masjid.id, UserSettings.main_masjid_choice == "masjid"),
        )
        .outerjoin(MawaqitListEntry, MawaqitListEntry.external_id == MasjidSource.list_external_id)
        .where(MasjidSource.origin == "auto")
        .group_by(Masjid.id, MasjidSource.masjid_id, MawaqitListEntry.name)
        .order_by(MasjidSource.linked_at.desc(), Masjid.name)
    )
    return [
        AutoLink(
            id=str(masjid.id), name=_name(masjid), list_name=list_name or "(no longer on the list)",
            mawaqit_url=page_url(source.external_id), distance_m=source.match_distance_m, users=count,
        )
        for masjid, source, list_name, count in rows
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
        auto_links=auto_links(db),
        no_match_masjids=no_match_masjids(db),
    )
