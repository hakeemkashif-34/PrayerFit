"""Each user's drive time to each of their masjids, saved per user and masjid.

A drive time is only asked again when:
1. There isn't one saved yet.
2. The home or the masjid moved (the route key changed).
3. The saved one is more than 30 days old.
So a nightly update for an unchanged user makes no OpenRouteService calls.
"""

import uuid
from datetime import datetime, timedelta

import httpx2
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.crypto import keyed_hash
from app.config import get_ors_settings
from app.geo.ors import NO_ROUTE, Route, drive_time, rounded
from app.models import Masjid, UserDriveTime

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
