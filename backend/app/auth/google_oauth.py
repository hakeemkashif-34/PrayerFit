"""Talking to Google's sign-in (OAuth) endpoints.

The flow, all on the server:
1. /auth/google/login sends the browser to Google with a random state and
   a PKCE code challenge.
2. The user agrees, and Google sends the browser back to /auth/google/callback
   with a one-time code and the same state.
3. The server swaps the code for tokens, proving with the PKCE code verifier
   that it's the same server that started the flow.
"""

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx2

from app.config import get_google_settings
from app.google_errors import GoogleError, GoogleTemporaryError, ReauthRequired

AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.app.created"
# calendar.app.created only lets the app see and change calendars it created
# itself. It can't read the user's other calendars. No Gmail, no full calendar.
SCOPES = ("openid", "email", CALENDAR_SCOPE)

GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


@dataclass(frozen=True)
class Pkce:
    verifier: str
    challenge: str


@dataclass(frozen=True)
class TokenResponse:
    access_token: str
    expires_in: int
    scopes: str
    # Google only sends these sometimes. A refresh doesn't include an ID
    # token, and usually doesn't include a new refresh token.
    refresh_token: str | None = None
    id_token: str | None = None


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_pkce() -> Pkce:
    """A random verifier, and its SHA-256 hash (the challenge) for Google.

    Google gets the challenge now and the verifier later. Someone who steals
    the code from the redirect can't use it without the verifier, which
    never leaves the server.
    """
    verifier = secrets.token_urlsafe(64)  # 86 characters, inside PKCE's 43 to 128
    challenge = _base64url(hashlib.sha256(verifier.encode()).digest())
    return Pkce(verifier=verifier, challenge=challenge)


def authorization_url(state: str, code_challenge: str) -> str:
    settings = get_google_settings()
    params = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # offline asks for a refresh token, so the server can act later.
        "access_type": "offline",
        # Always show the consent screen. Without it, Google only sends a
        # refresh token the first time, and a sign-in after the old one
        # expired would come back without one.
        "prompt": "consent",
    }
    return f"{AUTHORIZATION_URL}?{urlencode(params)}"


def _post_to_token_endpoint(http: httpx2.Client, data: dict[str, str]) -> httpx2.Response:
    try:
        response = http.post(TOKEN_URL, data=data)
    except httpx2.TransportError as error:
        raise GoogleTemporaryError(f"Couldn't reach Google: {error}") from error
    if response.status_code == 429 or response.status_code >= 500:
        raise GoogleTemporaryError(f"Google token endpoint answered {response.status_code}")
    return response


def _token_response(body: dict) -> TokenResponse:
    return TokenResponse(
        access_token=body["access_token"],
        expires_in=int(body["expires_in"]),
        scopes=body.get("scope", ""),
        refresh_token=body.get("refresh_token"),
        id_token=body.get("id_token"),
    )


def exchange_code(http: httpx2.Client, code: str, code_verifier: str) -> TokenResponse:
    settings = get_google_settings()
    response = _post_to_token_endpoint(
        http,
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "redirect_uri": settings.redirect_uri,
        },
    )
    if response.status_code != 200:
        error = response.json().get("error", "unknown_error")
        raise GoogleError(f"Google refused the sign-in code: {error}")
    return _token_response(response.json())


def refresh_access_token(http: httpx2.Client, refresh_token: str) -> TokenResponse:
    settings = get_google_settings()
    response = _post_to_token_endpoint(
        http,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
        },
    )
    if response.status_code != 200:
        error = response.json().get("error", "unknown_error")
        # invalid_grant: the refresh token expired (7 days in Testing mode)
        # or the user removed the app's access.
        if error == "invalid_grant":
            raise ReauthRequired()
        raise GoogleError(f"Google refused to refresh the token: {error}")
    return _token_response(response.json())


def read_id_token(id_token: str) -> GoogleIdentity:
    """Read who signed in from the ID token.

    The signature isn't checked. The OpenID Connect spec (section 3.1.3.7)
    allows that when the token came straight from Google's token endpoint
    over HTTPS in our own request, like here. The issuer, audience, and
    expiry are still checked.
    """
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # base64 needs padding back
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as error:
        raise GoogleError("Google sent an ID token that couldn't be read") from error

    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleError("ID token wasn't issued by Google")
    if claims.get("aud") != get_google_settings().client_id:
        raise GoogleError("ID token was made for a different app")
    if claims.get("exp", 0) < datetime.now(UTC).timestamp():
        raise GoogleError("ID token has expired")
    if not claims.get("sub") or not claims.get("email"):
        raise GoogleError("ID token is missing the user ID or email")
    return GoogleIdentity(sub=claims["sub"], email=claims["email"])


def has_calendar_scope(scopes: str) -> bool:
    return CALENDAR_SCOPE in scopes.split()
