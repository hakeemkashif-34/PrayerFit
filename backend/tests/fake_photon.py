"""A fake Photon for tests.

Like fake_google.py, it answers only the URL the app calls, records every
request, and can be told to fail. No test reaches the real Photon.
"""

import math

import httpx2

PHOTON_HOST = "photon.komoot.io"
SHORT_OSM_TYPES = {"node": "N", "way": "W", "relation": "R"}


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((phi2 - phi1) / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


class FakePhoton:
    def __init__(self) -> None:
        # Every place Photon "knows", as GeoJSON features.
        self.places: list[dict] = []
        self.requests: list[httpx2.Request] = []
        # Set to a status code (like 429), "timeout", or "connect" to make the next calls fail.
        self.failure: int | str | None = None

    # ---- Things tests call to set up a scene ----

    def add_place(self, lat: float, lon: float, countrycode: str = "CA", **properties) -> None:
        """A place Photon can suggest, like add_place(45.3, -75.9, housenumber="200", street="Kanata Avenue")."""
        self.places.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},  # GeoJSON is lon, lat
                "properties": {"countrycode": countrycode, **properties},
            }
        )

    def add_masjid(self, osm_id: int, name: str | None, lat: float, lon: float, osm_type: str = "node", **properties) -> None:
        """A place of worship, the way Photon sends one."""
        extra = {"name": name} if name is not None else {}
        self.add_place(
            lat, lon, osm_key="amenity", osm_value="place_of_worship",
            osm_type=SHORT_OSM_TYPES[osm_type], osm_id=osm_id, **extra, **properties,
        )

    # ---- The transport ----

    def handles(self, host: str) -> bool:
        return host == PHOTON_HOST

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path != "/api/":
            raise AssertionError(f"The app called a Photon URL the fake doesn't know: {request.url}")
        self.requests.append(request)
        if self.failure == "timeout":
            raise httpx2.ReadTimeout("fake timeout", request=request)
        if self.failure == "connect":
            raise httpx2.ConnectError("fake connection error", request=request)
        if self.failure is not None:
            return httpx2.Response(int(self.failure), text="Fake failure")

        params = request.url.params
        assert "PrayerFit" in request.headers["user-agent"]
        assert params["lang"] == "en"
        assert "lat" in params and "lon" in params  # every search has a bias
        osm_tag = params.get("osm_tag")
        # Like Photon: every word typed has to start a word in the place.
        words = params["q"].casefold().split()
        found = []
        for place in self.places:
            properties = place["properties"]
            if osm_tag and f"{properties.get('osm_key')}:{properties.get('osm_value')}" != osm_tag:
                continue
            text = " ".join(
                str(v) for k, v in properties.items() if k not in ("osm_key", "osm_value", "osm_type", "osm_id")
            ).casefold().replace(",", " ").split()
            if all(any(t.startswith(w) for t in text) for w in words):
                found.append(place)
        # Like Photon's bbox: only places inside the box.
        if "bbox" in params:
            min_lon, min_lat, max_lon, max_lat = (float(v) for v in params["bbox"].split(","))
            found = [
                p for p in found
                if min_lon <= p["geometry"]["coordinates"][0] <= max_lon and min_lat <= p["geometry"]["coordinates"][1] <= max_lat
            ]
        # Like Photon's location bias: closer places first.
        bias = (float(params["lat"]), float(params["lon"]))
        found.sort(key=lambda p: _km(*bias, p["geometry"]["coordinates"][1], p["geometry"]["coordinates"][0]))
        return httpx2.Response(
            200, json={"type": "FeatureCollection", "features": found[: int(params["limit"])]}
        )

    # ---- Reading what happened ----

    def masjid_requests(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.params.get("osm_tag")]
