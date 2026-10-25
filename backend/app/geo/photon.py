"""Suggestions as the user types, from the free public Photon service.

Photon (photon.komoot.io) searches OpenStreetMap data and is built for
search-as-you-type, which Nominatim's usage policy bans. Setup uses it twice:
1. Location: addresses, with Canadian results first.
2. Masjid: places of worship (osm_tag=amenity:place_of_worship), biased
   toward the user's saved location and sorted by distance from home. If
   no masjid matches, or the text has a number in it (like a house
   number), addresses near home are added, so a masjid that isn't on the
   map can be picked by its address.

Photon asks apps to be fair, so this app:
1. Only searches once the user stops typing for about 400 ms, and only
   with at least 3 characters. The website handles the first part.
2. Asks for a handful of results and shows at most 5.
3. Caches every answer for 7 days, so the same text is only sent once.
4. Spaces out calls across the whole app (see throttle.py).
5. Sends every request from the backend with the app's User-Agent.
6. Shows the OpenStreetMap credit (the website's footer).

What the user types is personal, so it's never logged or put in an error
message, and the cache stores it encrypted under a keyed hash. For masjid
searches, Photon gets the home location rounded to about 1 km, never the
exact one.
"""

import json
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta

import httpx2
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.crypto import decrypt, encrypt, keyed_hash
from app.config import get_osm_settings
from app.geo.distance import distance_km
from app.geo.errors import OsmServiceError
from app.geo.throttle import wait_for_turn
from app.http_client import log_failure, transport_reason
from app.models import GeocodeCache

MIN_QUERY_LENGTH = 3
MAX_SUGGESTIONS = 5
# Ask for a few more than we show, so the best 5 can be picked.
ASK_FOR = 10
CACHE_FOR = timedelta(days=7)
# A gentle limit for the whole app. Typing is already slowed down by the website.
MIN_GAP = timedelta(milliseconds=250)
# Photon favours results near this point. It's roughly the middle of
# Canada, with a wide radius, so it nudges results toward Canada as a whole.
CANADA_BIAS = {"lat": 56.13, "lon": -106.35, "zoom": 4, "location_bias_scale": 0.5}
PLACE_OF_WORSHIP = "amenity:place_of_worship"
# Photon's short OpenStreetMap types, in the words the masjids table uses.
OSM_TYPES = {"N": "node", "W": "way", "R": "relation"}


@dataclass(frozen=True)
class Suggestion:
    label: str  # like "200 Kanata Avenue, Ottawa, Ontario, Canada", or a masjid's name
    latitude: float
    longitude: float
    country_code: str | None
    # "address", or "masjid" for a place of worship.
    kind: str = "address"
    name: str | None = None
    # The address part without the name, like "351 Sandhill Road, Ottawa".
    street_address: str | None = None
    osm_type: str | None = None
    osm_id: int | None = None


def normalize(query: str) -> str:
    """"  200 Kanata  " and "200 kanata" are the same search."""
    return " ".join(query.split()).casefold()


def _join(parts: list[str | None]) -> str:
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)


def _from_feature(feature: dict) -> Suggestion | None:
    """One Photon result. Only what Photon sent, and never the postal code.

    OpenStreetMap's Canadian postal codes are often wrong, and prayer times
    only need the location.
    """
    properties = feature.get("properties", {})
    if properties.get("osm_value") == "postcode":
        return None  # a postal code area, not a place. Its name is the postal code.
    longitude, latitude = feature["geometry"]["coordinates"]
    street = " ".join(p for p in (properties.get("housenumber"), properties.get("street")) if p)
    name = properties.get("name")
    city = properties.get("city") or properties.get("district") or properties.get("county")
    label = _join([name, street if street != name else None, city, properties.get("state"), properties.get("country")])
    if not label:
        return None
    osm_id = properties.get("osm_id")
    return Suggestion(
        label=label,
        latitude=float(latitude),
        longitude=float(longitude),
        country_code=properties.get("countrycode"),
        name=name,
        street_address=_join([street, city]) or None,
        osm_type=OSM_TYPES.get(properties.get("osm_type", "")),
        osm_id=int(osm_id) if osm_id is not None else None,
    )


def _ask_photon(db: Session, http: httpx2.Client, query: str, now: datetime, cache_name: str, params: dict) -> list[Suggestion]:
    """One Photon search, from the cache if it's there. Every place Photon sent, deduplicated."""
    # "v3" because the cached shape changed. Older cached answers are never read.
    key = keyed_hash(f"photon:v3:{cache_name}:{normalize(query)}")
    cached = db.get(GeocodeCache, key)
    if cached is not None and cached.created_at > now - CACHE_FOR:
        return [Suggestion(**s) for s in json.loads(decrypt(cached.result_encrypted))]

    settings = get_osm_settings()
    wait_for_turn(db, "photon", MIN_GAP)
    started = time.monotonic()
    try:
        response = http.get(
            f"{settings.photon_url}/api/",
            params={"q": query, "limit": ASK_FOR, "lang": "en", **params},
            headers={"User-Agent": settings.user_agent},
        )
    except httpx2.TransportError as error:
        # The error text can include the URL, which has what the user typed in it.
        log_failure("Photon", transport_reason(error), started)
        raise OsmServiceError("Couldn't reach the search. Try again in a minute.")
    if response.status_code != 200:
        log_failure("Photon", f"status {response.status_code}", started)
    if response.status_code == 429 or response.status_code >= 500:
        raise OsmServiceError("The search is busy. Try again in a minute.")
    if response.status_code != 200:
        raise OsmServiceError(f"The search answered {response.status_code}.")
    try:
        found: list[Suggestion] = []
        for feature in response.json()["features"]:
            suggestion = _from_feature(feature)
            # Photon sometimes sends the same place twice.
            if suggestion is not None and all(s.label != suggestion.label for s in found):
                found.append(suggestion)
    except (ValueError, KeyError, TypeError):
        log_failure("Photon", "answer couldn't be read", started)
        raise OsmServiceError("The search sent an answer we couldn't read.")

    values = {"result_encrypted": encrypt(json.dumps([asdict(s) for s in found])), "created_at": now}
    db.execute(
        insert(GeocodeCache)
        .values(query_hash=key, **values)
        .on_conflict_do_update(index_elements=["query_hash"], set_=values)
    )
    db.commit()
    return found


def suggest(db: Session, http: httpx2.Client, query: str, now: datetime) -> list[Suggestion]:
    """Location: up to 5 addresses matching what the user has typed, Canada first."""
    if len(normalize(query)) < MIN_QUERY_LENGTH:
        return []
    found = _ask_photon(db, http, query, now, "address", CANADA_BIAS)
    # sorted() keeps Photon's order within each group.
    found = sorted(found, key=lambda s: (s.country_code or "").upper() != "CA")
    return found[:MAX_SUGGESTIONS]


def suggest_masjids(
    db: Session, http: httpx2.Client, query: str, home: tuple[float, float], now: datetime
) -> list[Suggestion]:
    """Masjid: up to 5 places of worship, closest to home first, then addresses if needed."""
    if len(normalize(query)) < MIN_QUERY_LENGTH:
        return []
    # Rounded to about 1 km, so Photon never gets the exact home. It's also
    # part of the cache key, since the same name finds different places in
    # different cities.
    near = (round(home[0], 2), round(home[1], 2))
    cell = f"{near[0]:.2f},{near[1]:.2f}"
    # A low location_bias_scale means distance matters more than how well known a place is.
    bias = {"lat": near[0], "lon": near[1], "zoom": 12, "location_bias_scale": 0.1}

    def by_distance(s: Suggestion) -> float:
        return distance_km(*home, s.latitude, s.longitude)

    places = _ask_photon(db, http, query, now, f"masjid:{cell}", {**bias, "osm_tag": PLACE_OF_WORSHIP})
    # A masjid has to have a name to be picked. The address search covers the rest.
    found = sorted((replace(p, kind="masjid", label=p.name) for p in places if p.name), key=by_distance)
    found = found[:MAX_SUGGESTIONS]

    # Only ask for addresses when no masjid matched, or the text looks like
    # an address (house numbers have digits). That keeps it to one Photon
    # call for most searches.
    if len(found) < MAX_SUGGESTIONS and (not found or any(c.isdigit() for c in query)):
        addresses = _ask_photon(db, http, query, now, f"near:{cell}", bias)
        taken = {(s.latitude, s.longitude) for s in found}
        extra = sorted((a for a in addresses if (a.latitude, a.longitude) not in taken), key=by_distance)
        found += extra[: MAX_SUGGESTIONS - len(found)]
    return found
