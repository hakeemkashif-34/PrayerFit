"""Database tables.

Every table except users has a user_id, so every query can be limited to
one user. That's how one user can never see another user's data.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Google's ID for the account. Emails can change, this never does.
    google_sub: Mapped[str] = mapped_column(String(255), unique=True)
    email: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    """One signed-in browser."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # SHA-256 of the cookie value. A leaked database can't be used to sign in.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoogleToken(Base):
    """A user's Google tokens, encrypted with TOKEN_ENCRYPTION_KEY."""

    __tablename__ = "google_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    refresh_token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    access_token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Space separated, as Google returns them.
    scopes: Mapped[str] = mapped_column(Text, default="")
    # True when Google refused the refresh token, so the user has to sign in again.
    needs_reauth: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PrayerCalendar(Base):
    """The "Prayers" calendar the app created in the user's Google account."""

    __tablename__ = "prayer_calendars"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    google_calendar_id: Mapped[str] = mapped_column(String(1024))
    time_zone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PrayerEvent(Base):
    """One prayer on one day. Saved here before it's sent to Google."""

    __tablename__ = "prayer_events"
    # One row per prayer per day per user. Running twice updates this row.
    __table_args__ = (UniqueConstraint("user_id", "local_date", "prayer"),)

    # The app's own event ID. Its hex form is also the Google event ID.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    local_date: Mapped[date] = mapped_column(Date)
    prayer: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    time_zone: Mapped[str] = mapped_column(String(64))
    # Where the time came from, like "Calculated (ISNA, standard Asr)".
    source_description: Mapped[str] = mapped_column(Text)
    # Which Google calendar it was last sent to. Changes if the calendar is recreated.
    google_calendar_id: Mapped[str | None] = mapped_column(String(1024))
    # "pending" until Google confirms it, then "synced".
    sync_status: Mapped[str] = mapped_column(String(16), default="pending")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
