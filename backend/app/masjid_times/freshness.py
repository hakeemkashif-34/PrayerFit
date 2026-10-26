"""How old a masjid's times can be and still be used.

Measured from the last fetch that passed every check:
1. Under 24 hours: fresh, so they're used.
2. 24 hours or more: they couldn't be confirmed, so the calendar uses
   calculated times until a fetch works again. A calculated start is never
   later than the iqamah, so the user is early, never late. Settings shows
   a notice while this lasts.
"""

from datetime import datetime, timedelta
from enum import Enum

FRESH_FOR = timedelta(hours=24)


class Freshness(Enum):
    FRESH = "fresh"
    # The last good fetch was 24 hours ago or more.
    STALE = "stale"
    # Linked, but no fetch has worked yet.
    NEVER = "never"

    @property
    def usable(self) -> bool:
        return self is Freshness.FRESH


def freshness(last_success_at: datetime | None, now: datetime) -> Freshness:
    if last_success_at is None:
        return Freshness.NEVER
    if now - last_success_at < FRESH_FOR:
        return Freshness.FRESH
    return Freshness.STALE
