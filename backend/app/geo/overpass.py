"""Find masjids near a location, with OpenStreetMap's Overpass API.

Overpass's usage policy (wiki.openstreetmap.org/wiki/Overpass_API):
1. Fewer than 10,000 queries a day, and don't hammer it. Results are cached
   for 7 days per grid cell, and calls are spaced at least 1 second apart.
2. Say who the app is. The same User-Agent as Nominatim.
3. Show the OpenStreetMap credit. The website does that.

Privacy: Overpass is asked about a rounded grid cell (about 1 km across),
never the exact home location. The exact distance is worked out here.
"""

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx2
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_osm_settings
from app.geo.errors import OsmServiceError
from app.geo.throttle import wait_for_turn
from app.models import Masjid, OverpassCache

SEARCH_RADIUS_KM = 15
# 0.01 degrees is about 1.1 km north to south (less east to west).
CELL_DECIMALS = 2
# Any point in a cell is under 0.8 km from its centre, so 17 km around the
# centre covers the full 15 km around every point in the cell.
QUERY_RADIUS_M = 17_000
CACHE_FOR = timedelta(days=7)
MIN_GAP = timedelta(seconds=1)
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


def _fetch(db: Session, http: httpx2.Client, latitude: float, longitude: float) -> list[dict]:
    settings = get_osm_settings()
    wait_for_turn(db, "overpass", MIN_GAP)
    try:
        response = http.post(
            settings.overpass_url,
            data={"data": overpass_query(latitude, longitude)},
            headers={"User-Agent": settings.user_agent},
        )
    except httpx2.TransportError:
        raise OsmServiceError("Couldn't reach OpenStreetMap's masjid search. Try again in a minute.")
    # 429: too many requests. 504: the server is overloaded.
    if response.status_code == 429 or response.status_code >= 500:
        raise OsmServiceError("OpenStreetMap's masjid search is busy. Try again in a minute.")
    if response.status_code != 200:
        raise OsmServiceError(f"OpenStreetMap's masjid search answered {response.status_code}.")
    try:
        return response.json()["elements"]
    except (ValueError, KeyError):
        raise OsmServiceError("OpenStreetMap's masjid search sent an answer we couldn't read.")


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
    cached = db.get(OverpassCache, cell)
    if cached is not None and cached.fetched_at > now - CACHE_FOR:
        ids = [uuid.UUID(i) for i in cached.masjid_ids]
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
