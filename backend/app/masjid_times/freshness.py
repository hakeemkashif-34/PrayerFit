"""How old a masjid's times can be and still be used.

Each good read saves a full 30-day calendar from MAWAQIT (FETCH_DAYS in
scheduler.py), so the last read is still right for days if MAWAQIT can't
be reached. Measured from the last read that passed every check:
1. Under 24 hours: fresh, so they're used.
2. 24 hours to 7 days: they couldn't be confirmed, but they're still used.
   Settings shows a notice with the date the calendar switches over.
3. Over 7 days: too old, so the calendar uses calculated times until a read
   works again. A calculated start is never later than the iqamah, so the
   user is early, never late.
"""

from datetime import datetime, timedelta
from enum import Enum

FRESH_FOR = timedelta(hours=24)
USABLE_FOR = timedelta(days=7)


class Freshness(Enum):
    FRESH = "fresh"
    # The last good read was 24 hours to 7 days ago. Still used.
    STALE = "stale"
    # The last good read was over 7 days ago. Not used.
    TOO_OLD = "too_old"
    # Linked, but no read has worked yet.
    NEVER = "never"

    @property
    def usable(self) -> bool:
        return self in (Freshness.FRESH, Freshness.STALE)


def freshness(last_success_at: datetime | None, now: datetime) -> Freshness:
    if last_success_at is None:
        return Freshness.NEVER
    age = now - last_success_at
    if age < FRESH_FOR:
        return Freshness.FRESH
    if age <= USABLE_FOR:
        return Freshness.STALE
    return Freshness.TOO_OLD
