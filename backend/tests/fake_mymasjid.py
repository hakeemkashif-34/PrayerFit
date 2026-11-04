"""A fake mymasjid.ca for tests. It answers only the timetable, records
every request, and can be told to fail. No test reaches the real site."""

from pathlib import Path

import httpx2

HOST = "app.mymasjid.ca"
SAVED_PAGE = Path(__file__).parent / "fixtures" / "mymasjid" / "timetable_2026-11-03.html"


class FakeMyMasjid:
    def __init__(self) -> None:
        # What the timetable returns. The saved real page from November 3, 2026 by default.
        self.page = SAVED_PAGE.read_text(encoding="utf-8")
        self.requests: list[httpx2.Request] = []
        # A status code (302, 403, 500), "timeout", or "huge" makes every call fail.
        self.failure: int | str | None = None

    def handles(self, host: str) -> bool:
        return host == HOST

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        assert request.method == "GET"
        assert "PrayerFit" in request.headers["user-agent"]
        if request.url.path != "/protected/public/timetable":
            raise AssertionError(f"The app called a mymasjid.ca URL the fake doesn't know: {request.url}")
        if self.failure == "timeout":
            raise httpx2.ReadTimeout("fake timeout", request=request)
        if self.failure == "huge":
            return httpx2.Response(200, content=b"x" * (300 * 1024))
        if self.failure == 302:
            return httpx2.Response(302, headers={"location": "https://example.com/elsewhere"})
        if self.failure is not None:
            return httpx2.Response(int(self.failure), text="Fake failure")
        return httpx2.Response(200, text=self.page, headers={"content-type": "text/html; charset=utf-8"})
