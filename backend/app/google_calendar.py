"""The only code that talks to the Google Calendar API.

It has exactly 5 calls: create a calendar, look one up, change its time
zone, add an event, and update an event. There's no delete call at all. There's nothing here that lists or changes the user's other
calendars, so the app can't touch them by mistake. The calendar.app.created
scope would block it anyway.
"""

from collections.abc import Callable
from urllib.parse import quote

import httpx2

from app.google_errors import (
    GoogleConflict,
    GoogleError,
    GoogleNotFound,
    GoogleTemporaryError,
    ReauthRequired,
)

CALENDAR_API = "https://www.googleapis.com/calendar/v3"

# Google sometimes reports rate limits as 403 with one of these reasons.
RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}

# Takes force_refresh and returns an access token.
TokenGetter = Callable[[bool], str]


def _reasons(response: httpx2.Response) -> set[str]:
    try:
        errors = response.json().get("error", {}).get("errors", [])
    except ValueError:
        return set()
    return {error.get("reason", "") for error in errors}


class GoogleCalendar:
    def __init__(self, http: httpx2.Client, get_token: TokenGetter) -> None:
        self._http = http
        self._get_token = get_token

    def _send(self, method: str, path: str, body: dict | None, token: str) -> httpx2.Response:
        try:
            return self._http.request(
                method,
                f"{CALENDAR_API}{path}",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx2.TransportError as error:
            # Includes timeouts. A timed out write may still have worked,
            # which is why events use fixed IDs (see prayer_sync.py).
            raise GoogleTemporaryError(f"Couldn't reach Google Calendar: {error}") from error

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        response = self._send(method, path, body, self._get_token(False))
        if response.status_code == 401:
            # The token was rejected early (for example, revoked). Refresh once and retry once.
            response = self._send(method, path, body, self._get_token(True))
            if response.status_code == 401:
                raise ReauthRequired()

        status = response.status_code
        if status < 300:
            return response.json()
        if status == 429 or status >= 500 or (status == 403 and _reasons(response) & RATE_LIMIT_REASONS):
            raise GoogleTemporaryError(f"Google Calendar answered {status}")
        if status in (404, 410):
            raise GoogleNotFound(f"Google Calendar answered {status} for {path}")
        if status == 409:
            raise GoogleConflict(f"Google Calendar answered 409 for {path}")
        raise GoogleError(f"Google Calendar answered {status}: {response.text[:200]}")

    @staticmethod
    def _calendar_path(calendar_id: str) -> str:
        # Calendar IDs look like abc@group.calendar.google.com, so encode the @.
        return f"/calendars/{quote(calendar_id, safe='')}"

    def create_calendar(self, summary: str, time_zone: str) -> str:
        """Create a calendar and return its ID."""
        created = self._request("POST", "/calendars", {"summary": summary, "timeZone": time_zone})
        return created["id"]

    def get_calendar(self, calendar_id: str) -> dict:
        return self._request("GET", self._calendar_path(calendar_id))

    def set_calendar_time_zone(self, calendar_id: str, time_zone: str) -> dict:
        # PATCH only changes the fields sent, so the name stays "Prayers".
        return self._request("PATCH", self._calendar_path(calendar_id), {"timeZone": time_zone})

    def insert_event(self, calendar_id: str, event: dict) -> dict:
        return self._request("POST", f"{self._calendar_path(calendar_id)}/events", event)

    def update_event(self, calendar_id: str, event_id: str, event: dict) -> dict:
        path = f"{self._calendar_path(calendar_id)}/events/{quote(event_id, safe='')}"
        return self._request("PUT", path, event)
