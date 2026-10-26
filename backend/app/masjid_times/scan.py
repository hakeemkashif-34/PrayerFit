"""scan-area: check how well my MAWAQIT list covers an area.

It asks OpenStreetMap's Overpass API for every masjid within 40 km of a
point, matches each one against the list, and prints what would happen:
linked, no match, or unclear. It only reports. Nothing is saved.

Overpass is free, and only this admin command uses it, a few times a year.
Setup uses Photon for searching (see geo/photon.py), since Overpass is
meant for occasional big queries, not one per user.
"""

import time as clock
from dataclasses import dataclass

import httpx2

from app.config import get_osm_settings
from app.http_client import log_failure, transport_reason
from app.masjid_times.match import Listed, Match, match

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
TIMEOUT_SECONDS = 90
# Ottawa's city hall, when no point is given.
OTTAWA = (45.4215, -75.6972)
DEFAULT_KM = 40
ORDER = {"linked": 0, "unclear": 1, "no match": 2}


class ScanFailed(Exception):
    pass


@dataclass(frozen=True)
class MapMasjid:
    name: str | None
    latitude: float
    longitude: float


def overpass_query(latitude: float, longitude: float, km: float) -> str:
    # nwr: a masjid can be a point, a building outline, or a group of buildings.
    # "out center" gives outlines a single point, their middle.
    return (
        "[out:json][timeout:60];"
        f'nwr["amenity"="place_of_worship"]["religion"="muslim"](around:{round(km * 1000)},{latitude},{longitude});'
        "out center tags;"
    )


def find_masjids(http: httpx2.Client, latitude: float, longitude: float, km: float) -> list[MapMasjid]:
    started = clock.monotonic()
    try:
        response = http.post(
            OVERPASS_URL,
            data={"data": overpass_query(latitude, longitude, km)},
            headers={"User-Agent": get_osm_settings().user_agent},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx2.TransportError as error:
        reason = transport_reason(error)
        log_failure("Overpass", reason, started)
        raise ScanFailed(f"Couldn't reach OpenStreetMap's Overpass API: {reason}") from error
    if response.status_code != 200:
        log_failure("Overpass", f"status {response.status_code}", started)
        raise ScanFailed(f"OpenStreetMap's Overpass API answered {response.status_code}. Try again in a few minutes.")
    found = []
    for element in response.json().get("elements", []):
        point = element if "lat" in element else element.get("center") or {}
        if "lat" in point and "lon" in point:
            found.append(MapMasjid((element.get("tags") or {}).get("name"), point["lat"], point["lon"]))
    return found


def scan_lines(found: list[MapMasjid], listed: list[Listed]) -> list[str]:
    """One line per masjid (linked first, then unclear, then no match), then the totals."""
    results: list[tuple[MapMasjid, Match]] = [(m, match(m.latitude, m.longitude, m.name, listed)) for m in found]
    results.sort(key=lambda r: (ORDER[r[1].status], (r[0].name or "").casefold()))
    lines = []
    for masjid, result in results:
        name = masjid.name or "(no name)"
        if result.status == "linked":
            lines.append(f"linked     {name} -> {result.entry.external_id} {result.entry.name} ({result.distance_m} m)")
        elif result.status == "unclear":
            near = ", ".join(f"{c.entry.external_id} {c.entry.name} ({c.distance_m} m)" for c in result.candidates)
            lines.append(f"unclear    {name}: {near}")
        else:
            lines.append(f"no match   {name} ({masjid.latitude:.5f}, {masjid.longitude:.5f})")
    totals = {status: sum(r.status == status for _, r in results) for status in ORDER}
    lines.append(
        f"{len(results)} masjid{'s' if len(results) != 1 else ''} on OpenStreetMap: "
        f"{totals['linked']} linked, {totals['no match']} no match, {totals['unclear']} unclear."
    )
    return lines
