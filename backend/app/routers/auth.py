"""Sign in with Google, sign out, and see who's signed in."""

import json
import secrets
from typing import Annotated

import httpx2
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.account import delete_account
from app.auth import google_oauth
from app.auth.crypto import decrypt, encrypt
from app.auth.sessions import SESSION_COOKIE, current_user, end_session, start_session
from app.auth.tokens import save_tokens
from app.config import get_app_settings
from app.db import get_db
from app.google_errors import GoogleError
from app.http_client import get_http
from app.models import GoogleToken, User, UserSettings
from app.stats import record_sign_up

router = APIRouter(tags=["sign-in"])

# Holds the state and PKCE verifier between /login and /callback.
FLOW_COOKIE = "oauth_flow"
FLOW_COOKIE_PATH = "/auth/google"
FLOW_MAX_AGE = 10 * 60  # seconds to finish signing in on Google's page


@router.get("/auth/google/login")
def login() -> RedirectResponse:
    """Start signing in. Open this URL in the browser tab, not from "Try it out".

    The state and PKCE verifier go in a short-lived encrypted cookie. That
    ties the sign-in to this browser, so nobody can finish it from another one.
    """
    state = secrets.token_urlsafe(32)
    pkce = google_oauth.make_pkce()
    response = RedirectResponse(google_oauth.authorization_url(state, pkce.challenge))
    response.set_cookie(
        FLOW_COOKIE,
        encrypt(json.dumps({"state": state, "verifier": pkce.verifier})).decode(),
        max_age=FLOW_MAX_AGE,
        httponly=True,
        secure=get_app_settings().cookie_secure,
        # Lax still sends it on Google's redirect back, which is a normal link.
        samesite="lax",
        path=FLOW_COOKIE_PATH,
    )
    return response


def _sign_in_failed(code: str) -> RedirectResponse:
    """Send the browser back to the website's sign-in screen with the reason.

    The code is one of: cancelled, expired, state, google. The website
    turns each into its own message. Only fixed codes go in the URL, so
    nobody can make a link that shows their own text on the sign-in page.
    """
    response = RedirectResponse(f"/?sign_in_error={code}", status_code=303)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_COOKIE_PATH)
    return response


@router.get("/auth/google/callback")
def callback(
    request: Request,
    db: Annotated[DbSession, Depends(get_db)],
    http: Annotated[httpx2.Client, Depends(get_http)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    """Google sends the browser here after the user agrees (or says no)."""
    # Read the flow cookie once. Every answer below deletes it, so each
    # sign-in can only be finished once.
    flow_cookie = request.cookies.get(FLOW_COOKIE)
    if error:
        return _sign_in_failed("cancelled")
    if not flow_cookie:
        return _sign_in_failed("expired")
    try:
        flow = json.loads(decrypt(flow_cookie.encode(), max_age_seconds=FLOW_MAX_AGE))
    except (InvalidToken, ValueError):
        return _sign_in_failed("expired")
    # compare_digest takes the same time whether or not the start matches.
    if not state or not secrets.compare_digest(state, flow["state"]):
        return _sign_in_failed("state")
    if not code:
        return _sign_in_failed("google")

    try:
        tokens = google_oauth.exchange_code(http, code, flow["verifier"])
        if not tokens.id_token:
            raise GoogleError("Google didn't send an ID token")
        identity = google_oauth.read_id_token(tokens.id_token)
    except GoogleError:
        return _sign_in_failed("google")

    user = db.scalars(select(User).where(User.google_sub == identity.sub)).first()
    if user is None:
        user = User(google_sub=identity.sub, email=identity.email)
        db.add(user)
        db.flush()  # gives the new user its ID
        record_sign_up(db)
    user.email = identity.email
    save_tokens(db, user.id, tokens)

    # Back to the website, which shows setup or the settings page.
    response = RedirectResponse("/", status_code=303)
    start_session(db, user.id, response)
    db.commit()
    response.delete_cookie(FLOW_COOKIE, path=FLOW_COOKIE_PATH)
    return response


class AccountDeleted(BaseModel):
    # False: Google couldn't be reached, so the website says how to remove the Prayers calendar by hand.
    google_cleaned: bool


@router.delete("/account", response_model=AccountDeleted)
def delete_my_account(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[DbSession, Depends(get_db)],
    http: Annotated[httpx2.Client, Depends(get_http)],
) -> Response:
    """Delete my account: the Prayers calendar, the app's Google access, and everything stored."""
    deleted = delete_account(db, http, user.id)
    response = JSONResponse({"google_cleaned": deleted.google_cleaned})
    # The session row went with the user. This clears the cookie too.
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: Annotated[DbSession, Depends(get_db)]) -> Response:
    response = Response(status_code=204)
    end_session(db, request, response)
    return response


class Me(BaseModel):
    email: str
    # True when the user has to sign in again before calendar updates work.
    google_sign_in_needed: bool
    calendar_access: bool
    # False for users who signed in before free/busy was asked for. The
    # website asks them to sign in again. Everything else still works.
    busy_access: bool
    # False until the setup questions are answered and finished.
    setup_complete: bool


@router.get("/me", response_model=Me)
def me(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[DbSession, Depends(get_db)],
) -> Me:
    tokens = db.scalars(select(GoogleToken).where(GoogleToken.user_id == user.id)).first()
    settings = db.scalars(select(UserSettings).where(UserSettings.user_id == user.id)).first()
    return Me(
        email=user.email,
        google_sign_in_needed=tokens is None or tokens.needs_reauth,
        calendar_access=tokens is not None and google_oauth.has_calendar_scope(tokens.scopes),
        busy_access=tokens is not None and google_oauth.has_freebusy_scope(tokens.scopes),
        setup_complete=settings is not None and settings.setup_completed_at is not None,
    )
