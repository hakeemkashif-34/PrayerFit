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
from app.models import Masjid, MasjidSource, MawaqitListEntry, UserSettings
from app.update_jobs import queue_update, users_of_masjid

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
                masjid_id=masjid.id, source=found.entry.source, external_id=found.entry.external_id, origin="auto",
                list_external_id=found.entry.external_id, match_distance_m=found.distance_m, linked_at=now,
            )
            .on_conflict_do_nothing()
        )
        db.flush()
        # Only IDs, never anything about a user.
        logger.info(
            "Linked masjid %s to %s %s (%d m)", masjid.id, found.entry.source, found.entry.external_id, found.distance_m
        )
    return found


def link_and_fetch(db: Session, http: httpx2.Client, masjid: Masjid, now: datetime) -> None:
    """In setup: link the picked masjid if it can be, then read its times if there are none fresh.

    Any problem is logged and dropped. Picking a masjid must work even when
    MAWAQIT is down, and calculated times are the fallback.
    """
    try:
        auto_link(db, masjid, now)
        # Picking an OpenStreetMap masjid saves OpenStreetMap's name again, so
        # it's set back to the list's name here. Other users of it already had
        # the list's name, so their calendars don't need an update.
        use_list_name(db, masjid)
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


def list_entry_for(db: Session, masjid: Masjid) -> MawaqitListEntry | None:
    """The list entry this masjid is linked to, if any: by an automatic match, or a link I made to a listed page."""
    source = db.get(MasjidSource, masjid.id)
    if source is None:
        return None
    entry = db.get(MawaqitListEntry, source.list_external_id or source.external_id)
    return entry if entry is not None and entry.source == source.source else None


def use_list_name(db: Session, masjid: Masjid) -> bool:
    """An OpenStreetMap masjid linked to a list entry takes the list's name. Doesn't commit.

    OpenStreetMap's name can be long or different ("Masjid Bilal, Islamic
    Society of Cumberland"), while setup's search shows the list's name
    ("Masjid Bilal"). Using the list's name keeps event titles and Settings
    the same as what the user picked. Only the name changes: the address
    stays OpenStreetMap's, and a short name the user typed is saved apart
    (user_settings) and never touched. True when the name changed.
    """
    if masjid.source != "openstreetmap":
        return False
    entry = list_entry_for(db, masjid)
    if entry is None or masjid.name == entry.name:
        return False
    masjid.name = entry.name
    return True


def update_picked_list_masjids(db: Session, now: datetime) -> int:
    """Bring masjids users already picked in line with the list. Commits.

    1. Picked from the list: copy the entry's name and address. A list
       masjid's row is saved when someone first picks it, so a fix in the
       file would otherwise only reach new picks.
    2. Picked from OpenStreetMap and linked to a list entry: use the list's name.
    Users of a masjid that changed get a calendar update, since the name is in
    event titles and the address is each masjid prayer's location. Returns how
    many masjids changed.
    """
    changed: list[Masjid] = []
    for masjid, entry in db.execute(
        select(Masjid, MawaqitListEntry).join(MawaqitListEntry, MawaqitListEntry.external_id == Masjid.list_external_id)
    ):
        if (masjid.name, masjid.address) == (entry.name, entry.address):
            continue
        masjid.name, masjid.address = entry.name, entry.address
        changed.append(masjid)
    linked = select(Masjid).join(MasjidSource, MasjidSource.masjid_id == Masjid.id).where(Masjid.source == "openstreetmap")
    for masjid in db.scalars(linked):
        if use_list_name(db, masjid):
            changed.append(masjid)
    for masjid in changed:
        for user_id in users_of_masjid(db, masjid.id):
            queue_update(db, user_id, "masjid list", now)
    db.commit()
    return len(changed)


def load_list(engine: Engine, now: datetime) -> int:
    """Load the file when the app starts. Returns how many rows were added or changed."""
    with Session(engine, expire_on_commit=False) as db:
        changed = save_rows(db, read_file(), "file", now)
        db.commit()
        if changed:
            new_links = rematch_picked(db, now)
            logger.info("MAWAQIT list: %d rows added or changed, %d masjids linked", changed, len(new_links))
        # Every start, not only when the list changed, so masjids picked before
        # a list name was used get it on the next deploy. Nothing changes if they match.
        # After rematching, so a masjid linked just now gets the list's name too.
        renamed = update_picked_list_masjids(db, now)
        if renamed:
            logger.info("Masjid list: %d picked masjids took the list's name or address", renamed)
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
