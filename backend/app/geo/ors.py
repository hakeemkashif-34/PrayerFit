"""Drive times from OpenRouteService (ORS), on its free plan.

ORS is built on OpenStreetMap data. It gives a typical drive time with no
live traffic, so the drive block is a fair estimate, not a promise.

Privacy and limits:
1. Only coordinates are sent, rounded to 3 decimal places (about 100 m).
   Never an address.
2. The API key goes in a header, never the URL, so it can't end up in a log.
3. Calls are spaced out across the whole app (the free plan allows 40 a
   minute), and each user's drive times are saved for 30 days, so it's
   never one call per event.
4. Any problem (no key, a timeout, a 429, no route) returns no drive time.
   The calendar update carries on without a drive block.
"""

import time
from dataclasses import dataclass
from datetime import timedelta

import httpx2
from sqlalchemy.orm import Session

from app.config import get_ors_settings
from app.geo.throttle import wait_for_turn
from app.http_client import log_failure, transport_reason

TIMEOUT_SECONDS = 10
MIN_GAP = timedelta(milliseconds=1600)
# ORS error codes that mean "there's no road between these points".
NO_ROUTE_CODES = {2004, 2009, 2010}


@dataclass(frozen=True)
class Route:
    seconds: int


class NoRoute:
    """ORS answered, and there's no drivable route. Saved, so it isn't asked again for 30 days."""


NO_ROUTE = NoRoute()


def rounded(point: tuple[float, float]) -> tuple[float, float]:
    return round(point[0], 3), round(point[1], 3)


def _error_code(response: httpx2.Response) -> int | None:
    try:
        return int(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return None


def drive_time(
    db: Session, http: httpx2.Client, start: tuple[float, float], end: tuple[float, float]
) -> Route | NoRoute | None:
    """Driving time from start to end, both (latitude, longitude).

    None means "don't know right now": no key, a timeout, a 429, or any other error.
    """
    settings = get_ors_settings()
    if not settings.api_key:
        return None
    (start_lat, start_lon), (end_lat, end_lon) = rounded(start), rounded(end)
    wait_for_turn(db, "ors", MIN_GAP)
    started = time.monotonic()
    try:
        response = http.post(
            f"{settings.url}/v2/directions/driving-car",
            # ORS wants longitude first.
            json={"coordinates": [[start_lon, start_lat], [end_lon, end_lat]]},
            headers={"Authorization": settings.api_key, "Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx2.TransportError as error:
        log_failure("OpenRouteService", transport_reason(error), started)
        return None
    if response.status_code in (400, 404) and _error_code(response) in NO_ROUTE_CODES:
        return NO_ROUTE
    if response.status_code != 200:
        log_failure("OpenRouteService", f"status {response.status_code}", started)
        return None
    try:
        seconds = float(response.json()["routes"][0]["summary"]["duration"])
    except (ValueError, KeyError, IndexError, TypeError):
        log_failure("OpenRouteService", "answer couldn't be read", started)
        return None
    if seconds < 0:
        return None
    return Route(seconds=round(seconds))
