"""Each user's commute time to each of their masjids.

The user's own time (user_commute_times) wins. Otherwise it's a driving
estimate from OpenRouteService, saved per user and masjid.

A drive time is only asked again when:
1. There isn't one saved yet.
2. The home or the masjid moved (the route key changed).
3. The saved one is more than 30 days old.
So a nightly update for an unchanged user makes no OpenRouteService calls.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx2
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.crypto import keyed_hash
from app.config import get_ors_settings
from app.geo.ors import NO_ROUTE, Route, drive_time, rounded
from app.models import Masjid, UserCommuteTime, UserDriveTime

KEEP_FOR = timedelta(days=30)


def route_key(home: tuple[float, float], masjid: Masjid) -> str:
    """A keyed hash, so the saved row can't be used to find where someone lives."""
    start, end = rounded(home), rounded((masjid.latitude, masjid.longitude))
    return keyed_hash(f"route:v1:{start[0]:.3f},{start[1]:.3f}:{end[0]:.3f},{end[1]:.3f}")


def drive_seconds(
    db: Session, http: httpx2.Client, user_id: uuid.UUID, home: tuple[float, float], masjids: list[Masjid], now: datetime
) -> dict[uuid.UUID, int | None]:
    """Seconds to drive to each masjid, or None when unknown. Commits."""
    found: dict[uuid.UUID, int | None] = {m.id: None for m in masjids}
    if not get_ors_settings().api_key:
        return found  # drive times are off
    for masjid in masjids:
        if masjid.latitude is None or masjid.longitude is None:
            continue
        key = route_key(home, masjid)
        saved = db.get(UserDriveTime, (user_id, masjid.id))
        if saved is not None and saved.route_key == key and now - saved.fetched_at < KEEP_FOR:
            found[masjid.id] = saved.seconds
            continue
        result = drive_time(db, http, home, (masjid.latitude, masjid.longitude))
        if result is None:
            # Couldn't ask right now. An old answer for the same route is still a fair guess.
            if saved is not None and saved.route_key == key:
                found[masjid.id] = saved.seconds
            continue
        values = {
            "seconds": result.seconds if isinstance(result, Route) else None,
            "status": "no_route" if result is NO_ROUTE else "ok",
            "route_key": key,
            "fetched_at": now,
        }
        db.execute(
            insert(UserDriveTime)
            .values(user_id=user_id, masjid_id=masjid.id, **values)
            .on_conflict_do_update(index_elements=["user_id", "masjid_id"], set_=values)
        )
        db.commit()
        found[masjid.id] = values["seconds"]
    return found


@dataclass(frozen=True)
class Commute:
    seconds: int | None  # None when unknown, so there's no commute block
    # "user" (their own time), "ors" (OpenRouteService), or None when unknown.
    source: str | None


def commute_times(
    db: Session,
    http: httpx2.Client,
    user_id: uuid.UUID,
    home: tuple[float, float],
    masjids: list[Masjid],
    now: datetime,
    overrides: dict[uuid.UUID, int | None] | None = None,
) -> dict[uuid.UUID, Commute]:
    """The commute to each masjid. OpenRouteService is only asked for masjids
    with no time of the user's own. overrides are unsaved times from a form
    the user is still filling in (None clears one)."""
    own = {
        row.masjid_id: row.minutes
        for row in db.scalars(select(UserCommuteTime).where(UserCommuteTime.user_id == user_id))
    }
    for masjid_id, minutes in (overrides or {}).items():
        if minutes is None:
            own.pop(masjid_id, None)
        else:
            own[masjid_id] = minutes
    found = {m.id: Commute(own[m.id] * 60, "user") for m in masjids if m.id in own}
    rest = [m for m in masjids if m.id not in own]
    drives = drive_seconds(db, http, user_id, home, rest, now) if rest else {}
    for masjid in rest:
        seconds = drives.get(masjid.id)
        found[masjid.id] = Commute(seconds, "ors" if seconds is not None else None)
    return found
