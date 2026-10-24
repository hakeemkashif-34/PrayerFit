"""Saving and using a user's Google tokens. Tokens never leave the server."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx2
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.crypto import decrypt, encrypt
from app.auth.google_oauth import TokenResponse, has_calendar_scope, refresh_access_token
from app.google_errors import CalendarAccessMissing, ReauthRequired
from app.models import GoogleToken


def save_tokens(db: Session, user_id: uuid.UUID, tokens: TokenResponse) -> GoogleToken:
    """Encrypt and save the tokens from a sign-in. The caller commits."""
    row = db.scalars(select(GoogleToken).where(GoogleToken.user_id == user_id)).first()
    if row is None:
        row = GoogleToken(user_id=user_id)
        db.add(row)
    row.access_token_encrypted = encrypt(tokens.access_token)
    row.access_token_expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_in)
    # Keep the old refresh token if Google didn't send a new one.
    if tokens.refresh_token:
        row.refresh_token_encrypted = encrypt(tokens.refresh_token)
    row.scopes = tokens.scopes
    row.needs_reauth = row.refresh_token_encrypted is None
    return row


# Refresh a little early, so a token doesn't expire halfway through a request.
REFRESH_MARGIN = timedelta(seconds=60)


def get_access_token(
    db: Session, http: httpx2.Client, user_id: uuid.UUID, force_refresh: bool = False
) -> str:
    """A working access token for this user, refreshing it on the server if needed.

    force_refresh is for when Google rejected a token we thought was fine.
    Raises ReauthRequired if Google won't refresh any more, and remembers
    that, so /me can tell the user to sign in again.
    """
    row = db.scalars(select(GoogleToken).where(GoogleToken.user_id == user_id)).first()
    if row is None or row.needs_reauth or row.refresh_token_encrypted is None:
        raise ReauthRequired()
    if not has_calendar_scope(row.scopes):
        raise CalendarAccessMissing()

    still_valid = (
        row.access_token_encrypted is not None
        and row.access_token_expires_at is not None
        and row.access_token_expires_at > datetime.now(UTC) + REFRESH_MARGIN
    )
    if still_valid and not force_refresh:
        return decrypt(row.access_token_encrypted)

    try:
        tokens = refresh_access_token(http, decrypt(row.refresh_token_encrypted))
    except ReauthRequired:
        row.needs_reauth = True
        db.commit()
        raise

    row.access_token_encrypted = encrypt(tokens.access_token)
    row.access_token_expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_in)
    if tokens.refresh_token:  # Google sometimes rotates it
        row.refresh_token_encrypted = encrypt(tokens.refresh_token)
    db.commit()
    return tokens.access_token
