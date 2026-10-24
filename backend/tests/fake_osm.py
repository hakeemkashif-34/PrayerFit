"""A fake Nominatim and Overpass for tests.

Like fake_google.py, it answers only the URLs the app calls, records every
request, and can be told to fail. No test reaches the real OpenStreetMap.
"""

import math
import re
from urllib.parse import parse_qs

import httpx2

NOMINATIM_HOST = "nominatim.openstreetmap.org"
OVERPASS_HOST = "overpass-api.de"


def _metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((phi2 - phi1) / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6_371_008.8 * math.asin(math.sqrt(a))


class FakeOsm:
    def __init__(self) -> None:
        # Normalized address -> Nominatim's answer.
        self.places: dict[str, dict] = {}
        # Every masjid "on OpenStreetMap", as Overpass elements.
        self.elements: list[dict] = []
        self.nominatim_requests: list[httpx2.Request] = []
        self.overpass_requests: list[httpx2.Request] = []
        # Set to a status code (like 429) or "timeout" to make the next calls fail.
        self.nominatim_failure: int | str | None = None
        self.overpass_failure: int | str | None = None

    # ---- Things tests call to set up a scene ----

    def add_place(self, address: str, display_name: str, lat: float, lon: float) -> None:
        self.places[" ".join(address.split()).casefold()] = {
            "display_name": display_name,
            "lat": str(lat),  # Nominatim sends numbers as strings
            "lon": str(lon),
        }

    def add_masjid(self, osm_id: int, name: str | None, lat: float, lon: float, osm_type: str = "node", **tags) -> None:
        all_tags = {"amenity": "place_of_worship", "religion": "muslim", **tags}
        if name is not None:
            all_tags["name"] = name
        element = {"type": osm_type, "id": osm_id, "tags": all_tags}
        if osm_type == "node":
            element |= {"lat": lat, "lon": lon}
        else:
            element["center"] = {"lat": lat, "lon": lon}  # "out center" for ways and relations
        self.elements.append(element)

    # ---- The transport ----

    def handles(self, host: str) -> bool:
        return host in (NOMINATIM_HOST, OVERPASS_HOST)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host == NOMINATIM_HOST and request.url.path == "/search":
            self.nominatim_requests.append(request)
            return self._nominatim(request)
        if request.url.host == OVERPASS_HOST and request.url.path == "/api/interpreter":
            self.overpass_requests.append(request)
            return self._overpass(request)
        raise AssertionError(f"The app called a URL the fake OpenStreetMap doesn't know: {request.url}")

    @staticmethod
    def _fail(request: httpx2.Request, failure: int | str) -> httpx2.Response:
        if failure == "timeout":
            raise httpx2.ReadTimeout("fake timeout", request=request)
        return httpx2.Response(int(failure), text="Fake failure")

    def _nominatim(self, request: httpx2.Request) -> httpx2.Response:
        if self.nominatim_failure is not None:
            return self._fail(request, self.nominatim_failure)
        params = request.url.params
        assert params["format"] == "jsonv2"
        assert params["limit"] == "1"
        assert "MuslimCalendar" in request.headers["user-agent"]
        place = self.places.get(" ".join(params["q"].split()).casefold())
        return httpx2.Response(200, json=[place] if place else [])

    def _overpass(self, request: httpx2.Request) -> httpx2.Response:
        if self.overpass_failure is not None:
            return self._fail(request, self.overpass_failure)
        assert "MuslimCalendar" in request.headers["user-agent"]
        query = parse_qs(request.content.decode())["data"][0]
        assert '["religion"="muslim"]' in query
        radius, lat, lon = map(float, re.search(r"around:([\d.]+),(-?[\d.]+),(-?[\d.]+)", query).groups())
        found = []
        for element in self.elements:
            point = element.get("center", element)
            if _metres(lat, lon, point["lat"], point["lon"]) <= radius:
                found.append(element)
        return httpx2.Response(200, json={"version": 0.6, "elements": found})

    def last_overpass_point(self) -> tuple[float, float]:
        query = parse_qs(self.overpass_requests[-1].content.decode())["data"][0]
        _, lat, lon = re.search(r"around:([\d.]+),(-?[\d.]+),(-?[\d.]+)", query).groups()
        return float(lat), float(lon)
