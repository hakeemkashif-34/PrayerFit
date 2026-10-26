"""Usage stats: counts only, never emails, names, or any other user details.

1. Total users: everyone who ever signed in.
2. Sign-ups per day and the total so far, for the /stats page's graph. It's
   worked out from each user's sign-up date, so nothing has to be saved
   each day.
3. Each masjid users picked, with how many picked it, and whether it has
   MAWAQIT times, so I know which masjids to add next.

Both the /stats page and `python -m app.admin stats` use these.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Masjid, MasjidSource, User, UserSettings
from app.prayer_times import DEFAULT_TIMEZONE

# A masjid picked by its address is where one user said it is, so the address is never shown.
PICKED_BY_ADDRESS = "(picked by address)"


@dataclass(frozen=True)
class Day:
    day: date
    signed_up: int
    total: int


@dataclass(frozen=True)
class MasjidCount:
    name: str
    users: int
    # False when it isn't linked to MAWAQIT, so its users get calculated times.
    mawaqit_linked: bool


def total_users(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User))


def daily_totals(db: Session, now: datetime) -> list[Day]:
    """One point per day in the app's time zone, from the first sign-up to today.

    Days with no sign-ups are still there (0 signed up, the same total), so
    the graph has one dot per day.
    """
    local_day = func.date(func.timezone(DEFAULT_TIMEZONE, User.created_at))
    per_day = dict(db.execute(select(local_day, func.count()).group_by(local_day)).all())
    if not per_day:
        return []
    today = now.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()
    day, last = min(per_day), max(today, max(per_day))
    points, total = [], 0
    while day <= last:
        total += per_day.get(day, 0)
        points.append(Day(day, per_day.get(day, 0), total))
        # A calendar date plus 1 day, never "plus 24 hours".
        day += timedelta(days=1)
    return points


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
