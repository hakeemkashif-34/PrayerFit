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

from app.auth import google_oauth
from app.auth.crypto import decrypt, encrypt
from app.auth.sessions import current_user, end_session, start_session
from app.auth.tokens import save_tokens
from app.config import get_app_settings
from app.db import get_db
from app.google_errors import GoogleError
from app.google_http import get_google_http
from app.models import GoogleToken, User

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


def _sign_in_failed(message: str) -> JSONResponse:
    response = JSONResponse(status_code=400, content={"detail": message})
    response.delete_cookie(FLOW_COOKIE, path=FLOW_COOKIE_PATH)
    return response


@router.get("/auth/google/callback")
def callback(
    request: Request,
    db: Annotated[DbSession, Depends(get_db)],
    http: Annotated[httpx2.Client, Depends(get_google_http)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    """Google sends the browser here after the user agrees (or says no)."""
    # Read the flow cookie once. Every answer below deletes it, so each
    # sign-in can only be finished once.
    flow_cookie = request.cookies.get(FLOW_COOKIE)
    if error:
        return _sign_in_failed(f"Google sign-in was cancelled or failed: {error}")
    if not flow_cookie:
        return _sign_in_failed("Sign-in expired or was already used. Start again at /auth/google/login.")
    try:
        flow = json.loads(decrypt(flow_cookie.encode(), max_age_seconds=FLOW_MAX_AGE))
    except (InvalidToken, ValueError):
        return _sign_in_failed("Sign-in expired or was changed. Start again at /auth/google/login.")
    # compare_digest takes the same time whether or not the start matches.
    if not state or not secrets.compare_digest(state, flow["state"]):
        return _sign_in_failed("State doesn't match. Start again at /auth/google/login.")
    if not code:
        return _sign_in_failed("Google didn't send a sign-in code.")

    try:
        tokens = google_oauth.exchange_code(http, code, flow["verifier"])
        if not tokens.id_token:
            raise GoogleError("Google didn't send an ID token")
        identity = google_oauth.read_id_token(tokens.id_token)
    except GoogleError as failure:
        return _sign_in_failed(str(failure))

    user = db.scalars(select(User).where(User.google_sub == identity.sub)).first()
    if user is None:
        user = User(google_sub=identity.sub, email=identity.email)
        db.add(user)
        db.flush()  # gives the new user its ID
    user.email = identity.email
    save_tokens(db, user.id, tokens)

    response = RedirectResponse("/docs", status_code=303)
    start_session(db, user.id, response)
    db.commit()
    response.delete_cookie(FLOW_COOKIE, path=FLOW_COOKIE_PATH)
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


@router.get("/me", response_model=Me)
def me(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[DbSession, Depends(get_db)],
) -> Me:
    tokens = db.scalars(select(GoogleToken).where(GoogleToken.user_id == user.id)).first()
    return Me(
        email=user.email,
        google_sign_in_needed=tokens is None or tokens.needs_reauth,
        calendar_access=tokens is not None and google_oauth.has_calendar_scope(tokens.scopes),
    )
