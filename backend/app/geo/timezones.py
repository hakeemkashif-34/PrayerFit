"""Work out a time zone from a location, offline.

timezonefinder ships the world's time zone borders inside the package, so
this never calls a paid (or any) web service.
"""

import os
import threading
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from timezonefinder import TimezoneFinder

from app.prayer_times import DEFAULT_TIMEZONE

# The finder isn't promised to be thread safe, and FastAPI runs requests in threads.
_lock = threading.Lock()


@lru_cache
def _finder() -> TimezoneFinder:
    # Loading the border data takes about 0.2 seconds, so do it once.
    return TimezoneFinder()


def timezone_for(latitude: float, longitude: float) -> str:
    """The IANA time zone at this point, like "America/Toronto"."""
    with _lock:
        name = _finder().timezone_at(lng=longitude, lat=latitude)
    try:
        if name:
            ZoneInfo(name)
            return name
    except (ZoneInfoNotFoundError, ValueError):
        pass
    # Shouldn't happen on land. Fall back instead of failing setup.
    return os.environ.get("DEFAULT_TIMEZONE") or DEFAULT_TIMEZONE
