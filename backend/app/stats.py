"""Usage stats: counts only, never emails, names, or any other user details.

1. Total users right now, for `python -m app.admin stats`.
2. Total users over time, for the /stats page's graph. It adds up
   user_count_changes, the sign-ups and deletions per hour, so the line goes
   down when someone deletes their account.
3. Each masjid users picked, with how many picked it, and whether it has
   MAWAQIT times, so I know which masjids to add next.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Masjid, MasjidSource, User, UserCountChange, UserSettings
from app.prayer_times import DEFAULT_TIMEZONE

# A masjid picked by its address is where one user said it is, so the address is never shown.
PICKED_BY_ADDRESS = "(picked by address)"

Range = Literal["1d", "2d", "3d", "5d", "7d", "30d", "all"]
# How many days each choice covers (None is all time), and one point per hour or per day.
RANGES: dict[str, tuple[int | None, Literal["hour", "day"]]] = {
    "1d": (1, "hour"),
    "2d": (2, "hour"),
    "3d": (3, "hour"),
    "5d": (5, "day"),
    "7d": (7, "day"),
    "30d": (30, "day"),
    "all": (None, "day"),
}


@dataclass(frozen=True)
class Point:
    # The start of the hour or day, in Toronto time.
    start: datetime
    # Users at the end of that hour or day, or right now for the current one.
    total: int


@dataclass(frozen=True)
class MasjidCount:
    name: str
    users: int
    # False when it isn't linked to MAWAQIT, so its users get calculated times.
    mawaqit_linked: bool


def total_users(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User))


def _this_hour():
    # The hour from the database's clock, so it matches users.created_at.
    return func.date_trunc("hour", func.timezone("UTC", func.now())).op("AT TIME ZONE")("UTC")


def _add(db: Session, signed_up: int = 0, deleted: int = 0) -> None:
    row = insert(UserCountChange).values(hour=_this_hour(), signed_up=signed_up, deleted=deleted)
    # Adds to the hour's counts if someone else already signed up or left this hour.
    db.execute(
        row.on_conflict_do_update(
            index_elements=[UserCountChange.hour],
            set_={
                "signed_up": UserCountChange.signed_up + row.excluded.signed_up,
                "deleted": UserCountChange.deleted + row.excluded.deleted,
            },
        )
    )


def record_sign_up(db: Session) -> None:
    """Count a new user. Part of the sign-in's own commit, so a failed sign-in counts nothing."""
    _add(db, signed_up=1)


def record_deletion(db: Session) -> None:
    """Count a deleted account. Only the hour, never who."""
    _add(db, deleted=1)


def user_totals(db: Session, now: datetime, range_: str) -> tuple[str, list[Point]]:
    """Total users over time: one point per hour for 1 to 3 days, one per day after that.

    Hours are real hours, counted in UTC, so a daylight saving day has 23 or
    25 of them. Days are Toronto calendar days. No changes at all means no points.
    """
    days, step = RANGES[range_]
    zone = ZoneInfo(DEFAULT_TIMEZONE)
    changes = [
        (hour, signed_up - deleted)
        for hour, signed_up, deleted in db.execute(
            select(UserCountChange.hour, UserCountChange.signed_up, UserCountChange.deleted).order_by(UserCountChange.hour)
        )
    ]
    if not changes:
        return step, []

    if step == "hour":
        last = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        slots = [last - timedelta(hours=n) for n in reversed(range(days * 24))]
    else:
        today = now.astimezone(zone).date()
        first = min(changes[0][0].astimezone(zone).date(), today) if days is None else today - timedelta(days=days - 1)
        # Calendar days, never "plus 24 hours".
        slots = [first + timedelta(days=n) for n in range((today - first).days + 1)]

    per_slot: dict = {}
    for hour, change in changes:
        key = hour if step == "hour" else hour.astimezone(zone).date()
        per_slot[key] = per_slot.get(key, 0) + change
    # Everything before the first point is already in its total.
    total = sum(change for key, change in per_slot.items() if key < slots[0])
    points = []
    for key in slots:
        total += per_slot.get(key, 0)
        start = key.astimezone(zone) if step == "hour" else datetime.combine(key, time(0), tzinfo=zone)
        points.append(Point(start, total))
    return step, points


def masjid_counts(db: Session) -> list[MasjidCount]:
    """Every masjid at least 1 user picked as their main masjid, most users first."""
    users = func.count(UserSettings.user_id)
    rows = db.execute(
        select(Masjid, users, MasjidSource.masjid_id.isnot(None))
        .join(UserSettings, UserSettings.main_masjid_id == Masjid.id)
        .outerjoin(MasjidSource, MasjidSource.masjid_id == Masjid.id)
        .where(UserSettings.main_masjid_choice == "masjid")
        .group_by(Masjid.id, MasjidSource.masjid_id)
        .order_by(users.desc(), Masjid.name.nulls_last())
    )
    return [MasjidCount(masjid.name or PICKED_BY_ADDRESS, count, linked) for masjid, count, linked in rows]


def stats_lines(total: int, masjids: list[MasjidCount]) -> list[str]:
    """What `python -m app.admin stats` prints: the same as the /stats page."""
    lines = [f"Total users: {total}", "", "Masjids:"]
    if not masjids:
        return [*lines, "  None picked yet."]
    return lines + [
        f"  {m.name}: {m.users}{'' if m.mawaqit_linked else '  (no MAWAQIT times)'}" for m in masjids
    ]
