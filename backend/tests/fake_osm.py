"""A fake Photon and Overpass for tests.

Like fake_google.py, it answers only the URLs the app calls, records every
request, and can be told to fail. No test reaches the real OpenStreetMap.
"""

import math
import re
from urllib.parse import parse_qs

import httpx2

PHOTON_HOST = "photon.komoot.io"
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
        # Every place Photon "knows", as GeoJSON features.
        self.places: list[dict] = []
        # Every masjid "on OpenStreetMap", as Overpass elements.
        self.elements: list[dict] = []
        self.photon_requests: list[httpx2.Request] = []
        self.overpass_requests: list[httpx2.Request] = []
        # Set to a status code (like 429) or "timeout" to make the next calls fail.
        self.photon_failure: int | str | None = None
        self.overpass_failure: int | str | None = None

    # ---- Things tests call to set up a scene ----

    def add_place(self, lat: float, lon: float, countrycode: str = "CA", **properties: str) -> None:
        """A place Photon can suggest, like add_place(45.3, -75.9, housenumber="200", street="Kanata Avenue")."""
        self.places.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},  # GeoJSON is lon, lat
                "properties": {"countrycode": countrycode, **properties},
            }
        )

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
        return host in (PHOTON_HOST, OVERPASS_HOST)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host == PHOTON_HOST and request.url.path == "/api/":
            self.photon_requests.append(request)
            return self._photon(request)
        if request.url.host == OVERPASS_HOST and request.url.path == "/api/interpreter":
            self.overpass_requests.append(request)
            return self._overpass(request)
        raise AssertionError(f"The app called a URL the fake OpenStreetMap doesn't know: {request.url}")

    @staticmethod
    def _fail(request: httpx2.Request, failure: int | str) -> httpx2.Response:
        if failure == "timeout":
            raise httpx2.ReadTimeout("fake timeout", request=request)
        return httpx2.Response(int(failure), text="Fake failure")

    def _photon(self, request: httpx2.Request) -> httpx2.Response:
        if self.photon_failure is not None:
            return self._fail(request, self.photon_failure)
        params = request.url.params
        assert "MuslimCalendar" in request.headers["user-agent"]
        assert params["lang"] == "en"
        assert "lat" in params and "lon" in params  # the bias toward Canada
        # Like Photon: every word typed has to start a word in the place.
        words = params["q"].casefold().split()
        found = []
        for place in self.places:
            text = " ".join(str(v) for v in place["properties"].values()).casefold().replace(",", " ").split()
            if all(any(t.startswith(w) for t in text) for w in words):
                found.append(place)
        return httpx2.Response(
            200, json={"type": "FeatureCollection", "features": found[: int(params["limit"])]}
        )

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
