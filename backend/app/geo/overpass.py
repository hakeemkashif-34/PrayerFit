"""Find masjids near a location, with OpenStreetMap's Overpass API.

Overpass's usage policy (wiki.openstreetmap.org/wiki/Overpass_API):
1. Fewer than 10,000 queries a day, and don't hammer it. Results are cached
   for 30 days per grid cell (masjids rarely change), and calls to each
   server are spaced at least 1 second apart.
2. Say who the app is. The same User-Agent as Photon.
3. Show the OpenStreetMap credit. The website does that.

Public Overpass servers are often busy or down. So:
1. There's a list of servers (OVERPASS_URLS). If one answers 429 or 5xx,
   times out, or can't be reached, the next one is asked.
2. The search starts in the background as soon as the location is saved
   (see routers/settings.py), so it's usually done before the masjid page.
3. The website never waits on it: "My masjid isn't listed" and "I pray at
   home" always work.

Privacy: Overpass is asked about a rounded grid cell (about 1 km across),
never the exact home location. The exact distance is worked out here.
"""

import math
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit
from datetime import datetime, timedelta

import httpx2
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_osm_settings
from app.geo.errors import OsmServiceError
from app.geo.throttle import wait_for_turn
from app.http_client import log_failure, transport_reason
from app.locks import advisory_lock
from app.models import Masjid, OverpassCache

SEARCH_RADIUS_KM = 15
# 0.01 degrees is about 1.1 km north to south (less east to west).
CELL_DECIMALS = 2
# Any point in a cell is under 0.8 km from its centre, so 17 km around the
# centre covers the full 15 km around every point in the cell.
QUERY_RADIUS_M = 17_000
CACHE_FOR = timedelta(days=30)
MIN_GAP = timedelta(seconds=1)
# Overpass often takes 30 to 45 seconds when it's busy (a real query for
# Kanata took 40.5 s), so each server gets much longer than the usual 10 seconds.
OVERPASS_TIMEOUT = 60
# All the servers together get at most this long. nginx waits 120 s for
# /api/, so the backend always answers first.
TOTAL_BUDGET = 100
# Not worth asking another server with less time than this left.
MIN_TRY = 5

# Swapped in tests to pretend time passed.
clock = time.monotonic
EARTH_RADIUS_KM = 6371.0088  # mean radius


@dataclass(frozen=True)
class NearbyMasjid:
    masjid: Masjid
    distance_km: float


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance over the Earth's surface (the haversine formula)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def cell_for(latitude: float, longitude: float) -> tuple[float, float]:
    return round(latitude, CELL_DECIMALS), round(longitude, CELL_DECIMALS)


def overpass_query(latitude: float, longitude: float) -> str:
    # nwr = nodes, ways, and relations. A masjid drawn as a building is a
    # way, and "out center" gives its middle point.
    return (
        "[out:json][timeout:25];"
        f'nwr["amenity"="place_of_worship"]["religion"="muslim"]'
        f"(around:{QUERY_RADIUS_M},{latitude},{longitude});"
        "out center tags;"
    )


def _address_from_tags(tags: dict[str, str]) -> str | None:
    """Only what OpenStreetMap has. Never a guess."""
    street = " ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p)
    parts = [p for p in (street, tags.get("addr:city"), tags.get("addr:postcode")) if p]
    return ", ".join(parts) or None


class _TryNextServer(Exception):
    """This server is down or busy. Ask the next one."""


def _ask(http: httpx2.Client, url: str, query: str, timeout: float, user_agent: str) -> list[dict]:
    """One Overpass server. Raises _TryNextServer, or OsmServiceError if trying others won't help."""
    name = f"Overpass ({urlsplit(url).hostname})"
    started = time.monotonic()
    try:
        response = http.post(url, data={"data": query}, headers={"User-Agent": user_agent}, timeout=timeout)
    except httpx2.TransportError as error:
        log_failure(name, transport_reason(error), started)
        raise _TryNextServer()
    if response.status_code != 200:
        log_failure(name, f"status {response.status_code}", started)
    # 429: too many requests. 5xx: down or overloaded (504 is Overpass's "too busy").
    if response.status_code == 429 or response.status_code >= 500:
        raise _TryNextServer()
    if response.status_code != 200:
        # A 400 means our query is wrong, and every server would say the same.
        raise OsmServiceError(f"OpenStreetMap's masjid search answered {response.status_code}.")
    try:
        return response.json()["elements"]
    except (ValueError, KeyError):
        log_failure(name, "answer couldn't be read", started)
        raise _TryNextServer()


def _fetch(db: Session, http: httpx2.Client, latitude: float, longitude: float) -> list[dict]:
    """Ask each server in turn until one answers, within TOTAL_BUDGET seconds."""
    settings = get_osm_settings()
    query = overpass_query(latitude, longitude)
    deadline = clock() + TOTAL_BUDGET
    for url in settings.overpass_urls:
        left = deadline - clock()
        if left < MIN_TRY:
            break
        # Spacing is per server, so a busy one doesn't slow down asking the next.
        wait_for_turn(db, f"overpass:{urlsplit(url).hostname}", MIN_GAP)
        try:
            return _ask(http, url, query, min(OVERPASS_TIMEOUT, left), settings.user_agent)
        except _TryNextServer:
            continue
    raise OsmServiceError("OpenStreetMap's masjid search is busy right now. Try again in a few minutes.")


def _save_masjids(db: Session, elements: list[dict]) -> list[uuid.UUID]:
    """Add or update each masjid by its OpenStreetMap ID. Returns their IDs."""
    ids = []
    for element in elements:
        point = element.get("center", element)
        if "lat" not in point or "lon" not in point:
            continue
        tags = element.get("tags", {})
        values = {
            "name": tags.get("name") or tags.get("name:en"),
            "latitude": float(point["lat"]),
            "longitude": float(point["lon"]),
            "address": _address_from_tags(tags),
            "updated_at": func.now(),
        }
        masjid_id = db.execute(
            insert(Masjid)
            .values(
                id=uuid.uuid4(),
                source="openstreetmap",
                osm_type=element["type"],
                osm_id=int(element["id"]),
                **values,
            )
            .on_conflict_do_update(index_elements=["osm_type", "osm_id"], set_=values)
            .returning(Masjid.id)
        ).scalar_one()
        ids.append(masjid_id)
    return ids


def nearby_masjids(
    db: Session, http: httpx2.Client, latitude: float, longitude: float, now: datetime
) -> list[NearbyMasjid]:
    """OpenStreetMap masjids within 15 km, closest first."""
    cell_lat, cell_lon = cell_for(latitude, longitude)
    cell = f"{cell_lat:.{CELL_DECIMALS}f},{cell_lon:.{CELL_DECIMALS}f}"
    # One search per cell at a time. If the background search is still
    # running when the masjid page asks, the page waits for it and then
    # reads the cache, instead of asking Overpass a second time.
    with advisory_lock(db, f"overpass:{cell}") as waited:
        cached = db.get(OverpassCache, cell, populate_existing=True)
        if cached is not None and cached.fetched_at > now - CACHE_FOR:
            ids = [uuid.UUID(i) for i in cached.masjid_ids]
        elif waited:
            # The search we waited for just failed. Trying again straight
            # away would likely fail too, and could outlast nginx's 120 s.
            raise OsmServiceError("OpenStreetMap's masjid search is busy right now. Try again in a few minutes.")
        else:
            ids = _save_masjids(db, _fetch(db, http, cell_lat, cell_lon))
            values = {"masjid_ids": [str(i) for i in ids], "fetched_at": now}
            db.execute(
                insert(OverpassCache)
                .values(cell=cell, **values)
                .on_conflict_do_update(index_elements=["cell"], set_=values)
            )
            db.commit()

    masjids = db.scalars(select(Masjid).where(Masjid.id.in_(ids))).all() if ids else []
    nearby = [
        NearbyMasjid(m, distance_km(latitude, longitude, m.latitude, m.longitude))
        for m in masjids
        if m.latitude is not None and m.longitude is not None
    ]
    # Ties (same distance) fall back to name, so the order never changes between calls.
    nearby = [n for n in nearby if n.distance_km <= SEARCH_RADIUS_KM]
    return sorted(nearby, key=lambda n: (n.distance_km, n.masjid.name or ""))
