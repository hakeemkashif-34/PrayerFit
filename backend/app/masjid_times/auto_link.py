"""Link masjids to MAWAQIT automatically, using my list (mawaqit_list.py).

It happens at 3 times:
1. When a user picks a masjid in setup. The page is read straight away, so
   the Jumuah question shows the masjid's real Jumuah times.
2. When the list changes (the app starts with new rows, or add-mawaqit).
   Every masjid users already picked is matched again.
3. Never over a link I made with link-mawaqit, and never for a masjid I
   unlinked by hand (no_auto_link).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx2
from sqlalchemy import Engine, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.masjid_times.freshness import Freshness, freshness
from app.masjid_times.match import Listed, Match, match
from app.masjid_times.mawaqit_list import listed, read_file, save_rows
from app.masjid_times.scheduler import run_fetch
from app.models import Masjid, MasjidSource, UserSettings

logger = logging.getLogger("app.masjid_times")


@dataclass(frozen=True)
class NewLink:
    masjid: Masjid
    found: Match


def auto_link(db: Session, masjid: Masjid, now: datetime, entries: list[Listed] | None = None) -> Match | None:
    """Link the masjid if exactly 1 listed masjid matches. None when it's already linked or I unlinked it."""
    if masjid.no_auto_link or db.get(MasjidSource, masjid.id) is not None:
        return None
    found = match(masjid.latitude, masjid.longitude, masjid.name, listed(db) if entries is None else entries)
    if found.status == "linked":
        # Do nothing on a clash, so 2 users picking the same masjid at once can't fail.
        db.execute(
            insert(MasjidSource)
            .values(
                masjid_id=masjid.id, source="mawaqit", external_id=found.entry.external_id, origin="auto",
                list_external_id=found.entry.external_id, match_distance_m=found.distance_m, linked_at=now,
            )
            .on_conflict_do_nothing()
        )
        db.flush()
        # Only IDs, never anything about a user.
        logger.info("Linked masjid %s to MAWAQIT %s (%d m)", masjid.id, found.entry.external_id, found.distance_m)
    return found


def link_and_fetch(db: Session, http: httpx2.Client, masjid: Masjid, now: datetime) -> None:
    """In setup: link the picked masjid if it can be, then read its times if there are none fresh.

    Any problem is logged and dropped. Picking a masjid must work even when
    MAWAQIT is down, and calculated times are the fallback.
    """
    try:
        auto_link(db, masjid, now)
        db.commit()
        source = db.get(MasjidSource, masjid.id)
        if source is not None and freshness(source.last_success_at, now) is not Freshness.FRESH:
            # Uses the same job ID as the worker, so this never adds a 2nd fetch in the same 6 hours.
            run_fetch(db, http, masjid.id, now)
    except Exception:  # noqa: BLE001 - MAWAQIT trouble never stops setup
        db.rollback()
        logger.exception("Linking or reading masjid %s failed", masjid.id)


def rematch_picked(db: Session, now: datetime) -> list[NewLink]:
    """Match every masjid users picked that isn't linked. Run when the list changes.

    The worker reads the new links within a minute, and that updates the users' calendars.
    """
    entries = listed(db)
    picked = exists().where(UserSettings.main_masjid_choice == "masjid", UserSettings.main_masjid_id == Masjid.id)
    linked = exists().where(MasjidSource.masjid_id == Masjid.id)
    new_links = []
    for masjid in db.scalars(select(Masjid).where(picked, ~linked, Masjid.no_auto_link.is_(False)).order_by(Masjid.name)):
        found = auto_link(db, masjid, now, entries)
        if found is not None and found.status == "linked":
            new_links.append(NewLink(masjid, found))
    db.commit()
    return new_links


def load_list(engine: Engine, now: datetime) -> int:
    """Load the file when the app starts. Returns how many rows were added or changed."""
    with Session(engine, expire_on_commit=False) as db:
        changed = save_rows(db, read_file(), "file", now)
        db.commit()
        if changed:
            new_links = rematch_picked(db, now)
            logger.info("MAWAQIT list: %d rows added or changed, %d masjids linked", changed, len(new_links))
    return changed


def load_list_on_start(engine: Engine) -> None:
    """For the backend and the worker when they start.

    A bad line is logged, not raised, so a typo can't take the site down. The
    rows already saved stay in use, and a test reads the file on every push.
    """
    try:
        load_list(engine, datetime.now(UTC))
    except Exception:  # noqa: BLE001
        logger.exception("Couldn't load the MAWAQIT list")
