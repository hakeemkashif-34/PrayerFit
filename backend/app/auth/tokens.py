"""Saving and using a user's Google tokens. Tokens never leave the server."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.crypto import encrypt
from app.auth.google_oauth import TokenResponse
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
