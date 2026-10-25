"""Address suggestions as the user types, from the free public Photon service.

Photon (photon.komoot.io) searches OpenStreetMap data and is built for
search-as-you-type, which Nominatim's usage policy bans. Photon asks apps
to be fair, so this app:
1. Only searches once the user stops typing for about 400 ms, and only
   with at least 3 characters. The website handles that part.
2. Asks for a handful of results and shows at most 5.
3. Caches every answer for 7 days, so the same text is only sent once.
4. Spaces calls out across the whole app (see throttle.py).
5. Sends every request from the backend with the app's User-Agent.
6. Shows the OpenStreetMap credit. The website does that.

What the user types is personal, so it's never logged or put in an error
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

MIN_QUERY_LENGTH = 3
MAX_SUGGESTIONS = 5
# Ask for a few more than we show, so Canadian results can be moved up.
ASK_FOR = 10
CACHE_FOR = timedelta(days=7)
# A gentle limit for the whole app. Typing is already slowed down by the website.
MIN_GAP = timedelta(milliseconds=250)
# Photon favours results near this point. It's roughly the middle of
# Canada, with a wide radius, so it nudges results toward Canada as a whole.
CANADA_BIAS = {"lat": 56.13, "lon": -106.35, "zoom": 4, "location_bias_scale": 0.5}


@dataclass(frozen=True)
class Suggestion:
    label: str  # like "200 Kanata Avenue, Ottawa, Ontario, K2T 1K8, Canada"
    latitude: float
    longitude: float
    country_code: str | None


def normalize(query: str) -> str:
    """"  200 Kanata  " and "200 kanata" are the same search."""
    return " ".join(query.split()).casefold()


def _cache_key(query: str) -> str:
    return keyed_hash("photon:" + normalize(query))


def _label(properties: dict) -> str:
    """Build one readable line from Photon's address parts. Only what Photon sent."""
    street = " ".join(p for p in (properties.get("housenumber"), properties.get("street")) if p)
    name = properties.get("name")
    parts = [
        name,
        street if street != name else None,
        properties.get("city") or properties.get("district") or properties.get("county"),
        properties.get("state"),
        properties.get("postcode"),
        properties.get("country"),
    ]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)


def _suggestions(features: list[dict]) -> list[Suggestion]:
    found: list[Suggestion] = []
    for feature in features:
        longitude, latitude = feature["geometry"]["coordinates"]
        properties = feature.get("properties", {})
        label = _label(properties)
        if not label or any(s.label == label for s in found):
            continue  # Photon sometimes sends the same place twice
        found.append(Suggestion(label, float(latitude), float(longitude), properties.get("countrycode")))
    # Canadian results first. sorted() keeps Photon's order within each group.
    found = sorted(found, key=lambda s: (s.country_code or "").upper() != "CA")
    return found[:MAX_SUGGESTIONS]


def suggest(db: Session, http: httpx2.Client, query: str, now: datetime) -> list[Suggestion]:
    """Up to 5 places matching what the user has typed so far."""
    if len(normalize(query)) < MIN_QUERY_LENGTH:
        return []
    key = _cache_key(query)
    cached = db.get(GeocodeCache, key)
    if cached is not None and cached.created_at > now - CACHE_FOR:
        return [Suggestion(**s) for s in json.loads(decrypt(cached.result_encrypted))]

    settings = get_osm_settings()
    wait_for_turn(db, "photon", MIN_GAP)
    try:
        response = http.get(
            f"{settings.photon_url}/api/",
            params={"q": query, "limit": ASK_FOR, "lang": "en", **CANADA_BIAS},
            headers={"User-Agent": settings.user_agent},
        )
    except httpx2.TransportError:
        # The error text can include the URL, which has what the user typed in it.
        raise OsmServiceError("Couldn't reach the address search. Try again in a minute.")
    if response.status_code == 429 or response.status_code >= 500:
        raise OsmServiceError("The address search is busy. Try again in a minute.")
    if response.status_code != 200:
        raise OsmServiceError(f"The address search answered {response.status_code}.")
    try:
        found = _suggestions(response.json()["features"])
    except (ValueError, KeyError, TypeError):
        raise OsmServiceError("The address search sent an answer we couldn't read.")

    values = {"result_encrypted": encrypt(json.dumps([asdict(s) for s in found])), "created_at": now}
    db.execute(
        insert(GeocodeCache)
        .values(query_hash=key, **values)
        .on_conflict_do_update(index_elements=["query_hash"], set_=values)
    )
    db.commit()
    return found
