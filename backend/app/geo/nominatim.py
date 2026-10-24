"""Turn a typed address into a place, with OpenStreetMap's Nominatim.

Nominatim's usage policy (operations.osmfoundation.org/policies/nominatim):
1. Say who the app is in the User-Agent. See OsmSettings.user_agent.
2. At most 1 request per second, for the whole app. See throttle.py.
3. Cache results. Each answer is kept for 30 days.
4. No search-as-you-type. The website only searches when the button is pressed.
5. Show the OpenStreetMap credit. The website does that.

The address is personal, so it's never logged, never put in an error
message, and the cache stores it encrypted under a keyed hash.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

import httpx2
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.crypto import decrypt, encrypt, keyed_hash
from app.config import get_osm_settings
from app.geo.errors import OsmServiceError
from app.geo.throttle import wait_for_turn
from app.models import GeocodeCache

MIN_GAP = timedelta(seconds=1)
CACHE_FOR = timedelta(days=30)


@dataclass(frozen=True)
class FoundPlace:
    place_name: str  # Nominatim's display_name, like "200 Main St, Ottawa, Ontario, Canada"
    latitude: float
    longitude: float


def normalize(address: str) -> str:
    """"  200 Main  St " and "200 main st" are the same search."""
    return " ".join(address.split()).casefold()


def _cache_key(address: str) -> str:
    return keyed_hash("nominatim:" + normalize(address))


def find_address(db: Session, http: httpx2.Client, address: str, now: datetime) -> FoundPlace | None:
    """The best match for the address, or None if Nominatim found nothing."""
    key = _cache_key(address)
    cached = db.get(GeocodeCache, key)
    if cached is not None and cached.created_at > now - CACHE_FOR:
        data = json.loads(decrypt(cached.result_encrypted))
        return FoundPlace(**data) if data else None

    settings = get_osm_settings()
    wait_for_turn(db, "nominatim", MIN_GAP)
    try:
        response = http.get(
            f"{settings.nominatim_url}/search",
            params={"q": address, "format": "jsonv2", "limit": 1},
            headers={"User-Agent": settings.user_agent},
        )
    except httpx2.TransportError:
        # The error text can include the URL, which has the address in it.
        raise OsmServiceError("Couldn't reach OpenStreetMap's address search. Try again in a minute.")
    if response.status_code == 429 or response.status_code >= 500:
        raise OsmServiceError("OpenStreetMap's address search is busy. Try again in a minute.")
    if response.status_code != 200:
        raise OsmServiceError(f"OpenStreetMap's address search answered {response.status_code}.")

    try:
        results = response.json()
        found = (
            FoundPlace(
                place_name=results[0]["display_name"],
                latitude=float(results[0]["lat"]),
                longitude=float(results[0]["lon"]),
            )
            if results
            else None
        )
    except (ValueError, KeyError, IndexError, TypeError):
        raise OsmServiceError("OpenStreetMap's address search sent an answer we couldn't read.")

    # "Not found" is cached too, so retyping the same thing doesn't call again.
    values = {
        "result_encrypted": encrypt(json.dumps(asdict(found) if found else None)),
        "created_at": now,
    }
    db.execute(
        insert(GeocodeCache)
        .values(query_hash=key, **values)
        .on_conflict_do_update(index_elements=["query_hash"], set_=values)
    )
    db.commit()
    return found
