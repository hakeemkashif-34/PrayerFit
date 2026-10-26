"""A fake Google for tests.

It answers the same URLs the app calls (the token endpoint and the
Calendar API), keeps calendars and events in memory, and records every
request. Any URL it doesn't know fails the test, so no test can reach
the real Google by mistake.

Tests can also tell it to fail on purpose: time out, rate limit, error,
expire tokens, or pretend the user deleted something.
"""

import base64
import hashlib
import itertools
import json
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote

import httpx2

CLIENT_ID = "test-client-id.apps.googleusercontent.com"
SCOPES = (
    "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/calendar.app.created "
    "https://www.googleapis.com/auth/calendar.freebusy"
)
# What a user who signed in before milestone 5 granted: no free/busy.
OLD_SCOPES = "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/calendar.app.created"
CALENDAR_API = "/calendar/v3"


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def fake_id_token(sub: str, email: str, aud: str = CLIENT_ID) -> str:
    """An unsigned JWT with the claims the app checks."""
    header = _base64url(json.dumps({"alg": "none"}).encode())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": aud,
        "sub": sub,
        "email": email,
        "exp": int(time.time()) + 3600,
    }
    return f"{header}.{_base64url(json.dumps(claims).encode())}.signature"


@dataclass
class PendingCode:
    sub: str
    email: str
    code_challenge: str
    scopes: str


@dataclass
class Account:
    sub: str
    email: str
    refresh_tokens: set[str] = field(default_factory=set)


@dataclass
class Calendar:
    id: str
    owner_sub: str
    summary: str
    time_zone: str
    deleted: bool = False
    events: dict[str, dict] = field(default_factory=dict)


@dataclass
class Recorded:
    method: str
    path: str
    body: dict | None
    # The Google user whose access token was used, if any.
    sub: str | None


class FakeGoogle:
    def __init__(self) -> None:
        self._counter = itertools.count(1)
        self.codes: dict[str, PendingCode] = {}
        self.accounts: dict[str, Account] = {}
        self.access_tokens: dict[str, str] = {}  # token -> sub
        self.calendars: dict[str, Calendar] = {}
        self.requests: list[Recorded] = []
        self.token_requests: list[dict[str, str]] = []
        # Failure on the Nth event write (1 is the first): "timeout", 429, 500,
        # or "timeout_after_write" (Google saves it but the answer never arrives).
        self.fail_event_write: dict[int, str | int] = {}
        self._event_writes = 0
        # Busy times in each user's primary calendar, as (start, end) RFC 3339 strings.
        self.busy: dict[str, list[tuple[str, str]]] = {}
        # Set to a status code (like 500) to make free/busy fail.
        self.freebusy_failure: int | None = None

    # ---- Things tests call to set up a scene ----

    def issue_code(self, sub: str, email: str, code_challenge: str, scopes: str = SCOPES) -> str:
        """What Google does when the user clicks Allow: make a one-time code."""
        code = f"code-{next(self._counter)}"
        self.codes[code] = PendingCode(sub, email, code_challenge, scopes)
        return code

    def expire_access_tokens(self) -> None:
        self.access_tokens.clear()

    def kill_refresh_tokens(self, sub: str) -> None:
        """Like Testing mode's 7 day limit, or the user removing the app's access."""
        self.accounts[sub].refresh_tokens.clear()

    def delete_calendar(self, calendar_id: str) -> None:
        self.calendars[calendar_id].deleted = True

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        # Google keeps deleted events as "cancelled", and the ID stays taken.
        self.calendars[calendar_id].events[event_id]["status"] = "cancelled"

    def calendars_of(self, sub: str) -> list[Calendar]:
        return [c for c in self.calendars.values() if c.owner_sub == sub and not c.deleted]

    def live_events(self, calendar_id: str) -> list[dict]:
        events = self.calendars[calendar_id].events.values()
        return [e for e in events if e.get("status") != "cancelled"]

    def writes(self) -> list[Recorded]:
        # Free/busy is a POST, but it only reads.
        return [r for r in self.requests if r.method != "GET" and not r.path.endswith("/freeBusy")]

    # ---- The transport the app's HTTP client uses ----

    def client(self) -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(self.handle))

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        url = request.url
        if url.host == "oauth2.googleapis.com" and url.path == "/token":
            return self._token(request)
        if url.host == "www.googleapis.com" and url.path.startswith(CALENDAR_API):
            return self._calendar_api(request)
        raise AssertionError(f"The app called a URL the fake Google doesn't know: {url}")

    # ---- Token endpoint ----

    def _new_access_token(self, sub: str) -> str:
        token = f"ya29.fake-access-{next(self._counter)}"
        self.access_tokens[token] = sub
        return token

    def _token(self, request: httpx2.Request) -> httpx2.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.token_requests.append(form)
        if form.get("client_id") != CLIENT_ID or form.get("client_secret") != "test-client-secret":
            return httpx2.Response(401, json={"error": "invalid_client"})

        if form.get("grant_type") == "authorization_code":
            pending = self.codes.pop(form.get("code", ""), None)  # each code works once
            if pending is None:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            # PKCE: the verifier has to hash to the challenge sent at the start.
            verifier = form.get("code_verifier", "")
            if _base64url(hashlib.sha256(verifier.encode()).digest()) != pending.code_challenge:
                return httpx2.Response(400, json={"error": "invalid_grant"})
            account = self.accounts.setdefault(pending.sub, Account(pending.sub, pending.email))
            refresh_token = f"1//fake-refresh-{next(self._counter)}"
            account.refresh_tokens.add(refresh_token)
            return httpx2.Response(
                200,
                json={
                    "access_token": self._new_access_token(pending.sub),
                    "expires_in": 3599,
                    "refresh_token": refresh_token,
                    "scope": pending.scopes,
                    "token_type": "Bearer",
                    "id_token": fake_id_token(pending.sub, pending.email),
                },
            )

        if form.get("grant_type") == "refresh_token":
            for account in self.accounts.values():
                if form.get("refresh_token") in account.refresh_tokens:
                    return httpx2.Response(
                        200,
                        json={
                            "access_token": self._new_access_token(account.sub),
                            "expires_in": 3599,
                            "scope": SCOPES,
                            "token_type": "Bearer",
                        },
                    )
            return httpx2.Response(400, json={"error": "invalid_grant"})

        return httpx2.Response(400, json={"error": "unsupported_grant_type"})

    # ---- Calendar API ----

    def _calendar_api(self, request: httpx2.Request) -> httpx2.Response:
        auth = request.headers.get("authorization", "")
        sub = self.access_tokens.get(auth.removeprefix("Bearer "))
        body = json.loads(request.content) if request.content else None
        # raw_path keeps %40 encoded, so split first and then decode each part.
        raw_path = request.url.raw_path.decode().split("?")[0]
        parts = [unquote(p) for p in raw_path.removeprefix(CALENDAR_API).strip("/").split("/")]
        self.requests.append(Recorded(request.method, unquote(raw_path), body, sub))

        if sub is None:
            return httpx2.Response(401, json={"error": {"code": 401, "message": "Invalid Credentials"}})

        # POST /calendars
        if request.method == "POST" and parts == ["calendars"]:
            calendar_id = f"prayers-{next(self._counter)}@group.calendar.google.com"
            self.calendars[calendar_id] = Calendar(
                calendar_id, sub, body["summary"], body["timeZone"]
            )
            return httpx2.Response(
                200, json={"id": calendar_id, "summary": body["summary"], "timeZone": body["timeZone"]}
            )

        # POST /freeBusy
        if request.method == "POST" and parts == ["freeBusy"]:
            return self._free_busy(sub, body)

        if len(parts) < 2 or parts[0] != "calendars":
            raise AssertionError(f"The app called a Calendar API path the fake doesn't know: {raw_path}")

        calendar = self.calendars.get(parts[1])
        # calendar.app.created can only reach calendars this app made for this user.
        if calendar is None or calendar.deleted or calendar.owner_sub != sub:
            return httpx2.Response(404, json={"error": {"code": 404, "message": "Not Found"}})

        # GET /calendars/{id}
        if request.method == "GET" and len(parts) == 2:
            return httpx2.Response(
                200, json={"id": calendar.id, "summary": calendar.summary, "timeZone": calendar.time_zone}
            )

        # PATCH /calendars/{id}
        if request.method == "PATCH" and len(parts) == 2:
            if "timeZone" in body:
                calendar.time_zone = body["timeZone"]
            if "summary" in body:
                calendar.summary = body["summary"]
            return httpx2.Response(
                200, json={"id": calendar.id, "summary": calendar.summary, "timeZone": calendar.time_zone}
            )

        # POST /calendars/{id}/events
        if request.method == "POST" and parts[2:] == ["events"]:
            failure = self._event_write_failure()
            if failure not in (None, "timeout_after_write"):
                return self._fail(request, failure)
            if body["id"] in calendar.events:
                return httpx2.Response(409, json={"error": {"code": 409, "message": "Duplicate"}})
            calendar.events[body["id"]] = dict(body)
            if failure == "timeout_after_write":
                raise httpx2.ReadTimeout("fake timeout after write", request=request)
            return httpx2.Response(200, json=calendar.events[body["id"]])

        # PUT /calendars/{id}/events/{eventId}
        if request.method == "PUT" and len(parts) == 4 and parts[2] == "events":
            failure = self._event_write_failure()
            if failure not in (None, "timeout_after_write"):
                return self._fail(request, failure)
            if parts[3] not in calendar.events:
                return httpx2.Response(404, json={"error": {"code": 404, "message": "Not Found"}})
            calendar.events[parts[3]] = dict(body)
            if failure == "timeout_after_write":
                raise httpx2.ReadTimeout("fake timeout after write", request=request)
            return httpx2.Response(200, json=calendar.events[parts[3]])

        # DELETE /calendars/{id}/events/{eventId}
        if request.method == "DELETE" and len(parts) == 4 and parts[2] == "events":
            failure = self._event_write_failure()
            if failure not in (None, "timeout_after_write"):
                return self._fail(request, failure)
            event = calendar.events.get(parts[3])
            if event is None or event.get("status") == "cancelled":
                return httpx2.Response(410, json={"error": {"code": 410, "message": "Resource has been deleted"}})
            # Like Google: the event stays as "cancelled", and its ID stays taken.
            event["status"] = "cancelled"
            return httpx2.Response(204)

        raise AssertionError(f"The app called a Calendar API path the fake doesn't know: {raw_path}")

    def _free_busy(self, sub: str, body: dict) -> httpx2.Response:
        if self.freebusy_failure is not None:
            return httpx2.Response(self.freebusy_failure, json={"error": {"code": self.freebusy_failure}})
        start, end = body["timeMin"], body["timeMax"]
        calendars = {}
        for item in body["items"]:
            if item["id"] == "primary":
                busy = [{"start": s, "end": e} for s, e in self.busy.get(sub, [])]
                calendars["primary"] = {"busy": busy}
        # Like a real answer that also has another calendar in it. The app must ignore it.
        for calendar in self.calendars_of(sub):
            calendars[calendar.id] = {"busy": [{"start": start, "end": end}]}
        return httpx2.Response(200, json={"kind": "calendar#freeBusy", "timeMin": start, "timeMax": end, "calendars": calendars})

    def freebusy_requests(self) -> list[Recorded]:
        return [r for r in self.requests if r.path.endswith("/freeBusy")]

    def deletes(self) -> list[Recorded]:
        return [r for r in self.requests if r.method == "DELETE"]

    def _event_write_failure(self) -> str | int | None:
        self._event_writes += 1
        return self.fail_event_write.get(self._event_writes)

    @staticmethod
    def _fail(request: httpx2.Request, failure: str | int) -> httpx2.Response:
        if failure == "timeout":
            raise httpx2.ReadTimeout("fake timeout", request=request)
        return httpx2.Response(int(failure), json={"error": {"code": failure, "message": "Fake failure"}})
