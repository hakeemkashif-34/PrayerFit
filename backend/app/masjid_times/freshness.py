"""How old a masjid's times can be and still be used.

Measured from the last fetch that passed every check:
1. Under 24 hours: fresh.
2. 24 hours to 7 days: stale. Still used, but the event says it may be out of date.
3. Over 7 days: too old. Not used, so the calculated time is used instead.
"""

from datetime import datetime, timedelta
from enum import Enum

FRESH_FOR = timedelta(hours=24)
USABLE_FOR = timedelta(days=7)


class Freshness(Enum):
    FRESH = "fresh"
    STALE = "stale"
    TOO_OLD = "too_old"
    # Linked, but no fetch has worked yet.
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
