"""Tests for the Google Calendar client, with a fake transport. No database needed."""

import httpx2
import pytest

from app.google_calendar import GoogleCalendar
from app.google_errors import (
    GoogleConflict,
    GoogleError,
    GoogleNotFound,
    GoogleTemporaryError,
    ReauthRequired,
)


def _calendar(handler, tokens=None):
    """A client whose requests go to handler. tokens records each force_refresh."""
    tokens = tokens if tokens is not None else []

    def get_token(force_refresh: bool) -> str:
        tokens.append(force_refresh)
        return "fresh-token" if force_refresh else "old-token"

    return GoogleCalendar(httpx2.Client(transport=httpx2.MockTransport(handler)), get_token)


def test_calendar_id_is_url_encoded():
    seen = []

    def handler(request):
        seen.append(request.url.raw_path.decode())
        return httpx2.Response(200, json={"id": "x"})

    _calendar(handler).get_calendar("abc@group.calendar.google.com")

    assert seen == ["/calendar/v3/calendars/abc%40group.calendar.google.com"]


def test_401_refreshes_once_and_retries():
    tokens = []

    def handler(request):
        if request.headers["authorization"] == "Bearer old-token":
            return httpx2.Response(401, json={})
        return httpx2.Response(200, json={"id": "x"})

    assert _calendar(handler, tokens).get_calendar("x") == {"id": "x"}
    assert tokens == [False, True]


def test_401_twice_asks_to_sign_in_again():
    with pytest.raises(ReauthRequired):
        _calendar(lambda request: httpx2.Response(401, json={})).get_calendar("x")


@pytest.mark.parametrize(
    "response, error",
    [
        (httpx2.Response(429, json={}), GoogleTemporaryError),
        (httpx2.Response(500, json={}), GoogleTemporaryError),
        (httpx2.Response(503, json={}), GoogleTemporaryError),
        (
            httpx2.Response(403, json={"error": {"errors": [{"reason": "rateLimitExceeded"}]}}),
            GoogleTemporaryError,
        ),
        (httpx2.Response(404, json={}), GoogleNotFound),
        (httpx2.Response(410, json={}), GoogleNotFound),
        (httpx2.Response(409, json={}), GoogleConflict),
        (httpx2.Response(403, json={"error": {"errors": [{"reason": "forbidden"}]}}), GoogleError),
    ],
)
def test_error_codes_become_the_right_error(response, error):
    with pytest.raises(error):
        _calendar(lambda request: response).insert_event("x", {})


def test_timeout_is_a_temporary_error():
    def handler(request):
        raise httpx2.ReadTimeout("slow", request=request)

    with pytest.raises(GoogleTemporaryError):
        _calendar(handler).update_event("x", "event1", {})
