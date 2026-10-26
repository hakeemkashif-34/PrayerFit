"""Admin commands, run on the server. There are no website buttons for
these, so a user can't link the wrong page for everyone.

    python -m app.admin list-masjids
    python -m app.admin link-mawaqit --masjid <masjid id> --url <MAWAQIT page link>
    python -m app.admin unlink-mawaqit --masjid <masjid id>
    python -m app.admin fetch-mawaqit --masjid <masjid id>
    python -m app.admin set-jumuah-length --masjid <masjid id> --minutes 40
    python -m app.admin stats            usage counts only, never anyone's details

With Docker: docker compose exec backend python -m app.admin list-masjids
"""

import argparse
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.http_client import new_http_client
from app.jumuah import DEFAULT_JUMUAH_MINUTES
from app.masjid_times.mawaqit import BadLink, slug_from_link
from app.masjid_times.scheduler import run_fetch
from app.models import Masjid, MasjidDayTimes, MasjidSource
from app.stats import counts, stats_lines
from app.update_jobs import queue_update, users_of_masjid


def _masjid(db: Session, masjid_id: str) -> Masjid:
    try:
        found = db.get(Masjid, uuid.UUID(masjid_id))
    except ValueError:
        found = None
    if found is None:
        raise SystemExit(f"No masjid with ID {masjid_id}. Run list-masjids to see the IDs.")
    return found


def list_masjids(db: Session) -> list[str]:
    lines = []
    for masjid in db.scalars(select(Masjid).order_by(Masjid.name.nulls_last(), Masjid.id)):
        source = db.get(MasjidSource, masjid.id)
        users = len(users_of_masjid(db, masjid.id))
        # A typed-in masjid's address is where one user said it is, so it isn't printed.
        name = masjid.name or "(no name, picked by address)"
        linked = f"MAWAQIT {source.external_id}" if source else "not linked"
        fetched = f", last fetched {source.last_success_at:%Y-%m-%d %H:%M} UTC" if source and source.last_success_at else ""
        length = (
            f"Jumuah {masjid.jumuah_minutes} min" if masjid.jumuah_minutes
            else f"Jumuah length not set ({DEFAULT_JUMUAH_MINUTES} min estimated)"
        )
        lines.append(f"{masjid.id}  {name}  [{linked}{fetched}]  {length}  {users} user{'s' if users != 1 else ''}")
    return lines or ["No masjids yet. They're added when users pick them in setup."]


def link_mawaqit(db: Session, masjid_id: str, link: str, now: datetime) -> str:
    masjid = _masjid(db, masjid_id)
    try:
        slug = slug_from_link(link)
    except BadLink as error:
        raise SystemExit(str(error))
    source = db.get(MasjidSource, masjid.id)
    if source is not None and source.source == "mawaqit" and source.external_id == slug:
        return f"{masjid.name or masjid.id} is already linked to MAWAQIT {slug}."
    if source is not None:
        # A different page: the old page's times don't belong to this one.
        db.execute(delete(MasjidDayTimes).where(MasjidDayTimes.masjid_id == masjid.id))
        db.delete(source)
        db.flush()
    db.add(MasjidSource(masjid_id=masjid.id, source="mawaqit", external_id=slug, linked_at=now))
    db.commit()
    return f"Linked {masjid.name or masjid.id} to MAWAQIT {slug}. The worker reads it within a minute."


JUMUAH_MINUTES = range(15, 91)


def set_jumuah_length(db: Session, masjid_id: str, minutes: int, now: datetime) -> str:
    """How long this masjid's Jumuah takes, from the start of the khutbah to the end of the prayer."""
    if minutes not in JUMUAH_MINUTES:
        raise SystemExit("Jumuah length must be a whole number of minutes from 15 to 90.")
    masjid = _masjid(db, masjid_id)
    masjid.jumuah_minutes = minutes
    # Their Jumuah events end at the new time.
    users = users_of_masjid(db, masjid.id)
    for user_id in users:
        queue_update(db, user_id, "jumuah_length", now)
    db.commit()
    return f"Set {masjid.name or masjid.id}'s Jumuah to {minutes} minutes. Updates queued for {len(users)} user(s)."


def unlink_mawaqit(db: Session, masjid_id: str, now: datetime) -> str:
    masjid = _masjid(db, masjid_id)
    source = db.get(MasjidSource, masjid.id)
    if source is None:
        return f"{masjid.name or masjid.id} isn't linked."
    db.execute(delete(MasjidDayTimes).where(MasjidDayTimes.masjid_id == masjid.id))
    db.delete(source)
    # Their calendars go back to calculated times.
    users = users_of_masjid(db, masjid.id)
    for user_id in users:
        queue_update(db, user_id, "unlinked", now)
    db.commit()
    return f"Unlinked {masjid.name or masjid.id}. Updates queued for {len(users)} user(s)."


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.admin")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list-masjids", help="every masjid with its ID and MAWAQIT link")
    link = commands.add_parser("link-mawaqit", help="read a masjid's times from its MAWAQIT page")
    link.add_argument("--masjid", required=True, help="the masjid's ID, from list-masjids")
    link.add_argument("--url", required=True, help="the masjid's page, like https://mawaqit.net/en/your-masjid")
    unlink = commands.add_parser("unlink-mawaqit", help="stop reading a masjid's MAWAQIT page")
    unlink.add_argument("--masjid", required=True)
    fetch = commands.add_parser("fetch-mawaqit", help="read a linked masjid's page now")
    fetch.add_argument("--masjid", required=True)
    length = commands.add_parser("set-jumuah-length", help="how long a masjid's Jumuah takes, 15 to 90 minutes")
    length.add_argument("--masjid", required=True)
    # A string, so "40.5" gets this command's own message instead of argparse's.
    length.add_argument("--minutes", required=True)
    commands.add_parser("stats", help="how many people signed up, finished setup, are active, and are new")
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    with Session(get_engine(), expire_on_commit=False) as db:
        if args.command == "list-masjids":
            print("\n".join(list_masjids(db)))
        elif args.command == "stats":
            print("\n".join(stats_lines(counts(db, now))))
        elif args.command == "link-mawaqit":
            print(link_mawaqit(db, args.masjid, args.url, now))
        elif args.command == "unlink-mawaqit":
            print(unlink_mawaqit(db, args.masjid, now))
        elif args.command == "set-jumuah-length":
            if not args.minutes.isdigit():
                raise SystemExit("Jumuah length must be a whole number of minutes from 15 to 90.")
            print(set_jumuah_length(db, args.masjid, int(args.minutes), now))
        elif args.command == "fetch-mawaqit":
            masjid = _masjid(db, args.masjid)
            with new_http_client() as http:
                result = run_fetch(db, http, masjid.id, now, force=True)
            print(f"{result.status}{'. ' + result.message if result.message else ''}")
            if result.status not in ("done", "skipped"):
                sys.exit(1)


if __name__ == "__main__":
    main()
