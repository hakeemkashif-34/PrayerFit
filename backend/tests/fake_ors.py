"""A fake OpenRouteService for tests. It answers only driving directions,
records what it was sent, and can be told to fail."""

import json

import httpx2

ORS_HOST = "api.heigit.org"
DIRECTIONS_PATH = "/openrouteservice/v2/directions/driving-car"


class FakeOrs:
    def __init__(self) -> None:
        # Seconds for every route, unless a test changes it.
        self.seconds: float = 14 * 60
        # Seconds to one destination, by its (latitude, longitude) rounded to 3 places.
        self.seconds_to: dict[tuple[float, float], float] = {}
        self.requests: list[httpx2.Request] = []
        self.bodies: list[dict] = []
        # A status code (429, 500), "timeout", or "no_route".
        self.failure: int | str | None = None

    def handles(self, host: str) -> bool:
        return host == ORS_HOST

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.method != "POST" or request.url.path != DIRECTIONS_PATH:
            raise AssertionError(f"The app called an OpenRouteService URL the fake doesn't know: {request.url}")
        self.requests.append(request)
        body = json.loads(request.content)
        self.bodies.append(body)
        if self.failure == "timeout":
            raise httpx2.ReadTimeout("fake timeout", request=request)
        if self.failure == "no_route":
            return httpx2.Response(
                404, json={"error": {"code": 2009, "message": "Route could not be found"}}
            )
        if self.failure is not None:
            return httpx2.Response(int(self.failure), json={"error": "Fake failure"})
        end_lon, end_lat = body["coordinates"][1]
        seconds = self.seconds_to.get((end_lat, end_lon), self.seconds)
        return httpx2.Response(
            200, json={"routes": [{"summary": {"distance": 9000.0, "duration": seconds}}]}
        )
