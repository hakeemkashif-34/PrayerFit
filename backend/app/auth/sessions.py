"""Sign-in sessions, kept in an HttpOnly cookie.

The cookie holds a long random value. The database only keeps its SHA-256
hash, so someone who reads the database still can't sign in as anyone.
HttpOnly means JavaScript in the page can't read the cookie.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.config import get_app_settings
from app.db import get_db
from app.models import Session, User

SESSION_COOKIE = "session"


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db: DbSession, user_id: uuid.UUID, response: Response) -> None:
    """Save a new session and set its cookie on the response. The caller commits."""
    settings = get_app_settings()
    token = secrets.token_urlsafe(32)  # 256 random bits
    db.add(
        Session(
            user_id=user_id,
            token_hash=hash_session_token(token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.session_days),
        )
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.cookie_secure,
        # Lax: the browser won't send the cookie on POSTs from other sites.
        # Strict would also drop it when arriving back from Google's redirect.
        samesite="lax",
        path="/",
    )


def end_session(db: DbSession, request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute(delete(Session).where(Session.token_hash == hash_session_token(token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_user(request: Request, db: Annotated[DbSession, Depends(get_db)]) -> User:
    """The signed-in user, or 401. Every user-specific endpoint depends on this."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        user = db.scalars(
            select(User)
            .join(Session, Session.user_id == User.id)
            .where(
                Session.token_hash == hash_session_token(token),
                Session.expires_at > datetime.now(UTC),
            )
        ).first()
        if user is not None:
            return user
    raise HTTPException(
        status_code=401,
        detail={"message": "Not signed in.", "login_url": "/auth/google/login"},
    )
