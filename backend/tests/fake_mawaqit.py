"""A fake MAWAQIT for tests. Like fake_photon.py, it answers only masjid
pages, records every request, and can be told to fail. No test reaches
the real mawaqit.net."""

import httpx2

MAWAQIT_HOST = "mawaqit.net"


class FakeMawaqit:
    def __init__(self) -> None:
        # Page name ("kma-kanata") -> the HTML the page returns.
        self.pages: dict[str, str] = {}
        self.requests: list[httpx2.Request] = []
        # A status code (403, 429, 500), "timeout", or "huge" makes every call fail.
        self.failure: int | str | None = None

    def handles(self, host: str) -> bool:
        return host == MAWAQIT_HOST

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        assert request.method == "GET"
        assert "MuslimCalendar" in request.headers["user-agent"]
        parts = request.url.path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "en":
            raise AssertionError(f"The app called a MAWAQIT URL the fake doesn't know: {request.url}")
        if self.failure == "timeout":
            raise httpx2.ReadTimeout("fake timeout", request=request)
        if self.failure == "huge":
            return httpx2.Response(200, content=b"x" * (4 * 1024 * 1024))
        if self.failure is not None:
            return httpx2.Response(int(self.failure), text="Fake failure")
        if parts[1] not in self.pages:
            return httpx2.Response(404, text="Not found")
        return httpx2.Response(200, text=self.pages[parts[1]], headers={"content-type": "text/html"})
