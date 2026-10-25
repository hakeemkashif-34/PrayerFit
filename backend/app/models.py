"""Database tables.

Every table that holds a user's data has a user_id, so every query can be limited to
one user. That's how one user can never see another user's data.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
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
    # "home" or "masjid". Empty for rows made before milestone 4.
    place: Mapped[str | None] = mapped_column(String(8))
    masjid_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("masjids.id", ondelete="SET NULL")
    )
    # Title and description as sent to Google, like "Dhuhr at KMA".
    summary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # SHA-256 of the event Google last confirmed. If the new event hashes
    # the same, nothing changed and Google isn't called.
    synced_hash: Mapped[str | None] = mapped_column(String(64))


class UserSettings(Base):
    """A user's setup answers. One row per user.

    The address the user picked and its coordinates are both encrypted,
    because each one points to where the user lives.
    """

    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    address_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    place_name_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    # "latitude,longitude", encrypted.
    location_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    # Not encrypted: the nightly job needs it to know when 3:00 am is.
    time_zone: Mapped[str | None] = mapped_column(String(64))
    # Empty means the defaults (ISNA, standard). Setup doesn't ask for now.
    method: Mapped[str | None] = mapped_column(String(16))
    asr_method: Mapped[str | None] = mapped_column(String(16))
    # "masjid" or "home". Empty until the masjid step is saved.
    main_masjid_choice: Mapped[str | None] = mapped_column(String(8))
    main_masjid_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("masjids.id", ondelete="SET NULL")
    )
    # Like "KMA". Used in event titles instead of the full name.
    main_masjid_short_name: Mapped[str | None] = mapped_column(String(40))
    # True once Jumuah masjids are saved on the settings page. Not part of setup for now.
    jumuah_saved: Mapped[bool] = mapped_column(default=False)
    setup_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Masjid(Base):
    """A masjid from OpenStreetMap, or one a user typed in.

    OpenStreetMap masjids are public, so every user can see them. Typed-in
    masjids have created_by_user_id and only that user sees them. Nothing
    here is made up: no guessed address and no times.
    """

    __tablename__ = "masjids"
    # Postgres allows many NULLs here, so typed-in masjids don't clash.
    __table_args__ = (UniqueConstraint("osm_type", "osm_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # "openstreetmap" or "user"
    source: Mapped[str] = mapped_column(String(16))
    # "node", "way", or "relation". OSM IDs are only unique within a type.
    osm_type: Mapped[str | None] = mapped_column(String(8))
    osm_id: Mapped[int | None] = mapped_column(BigInteger)
    # Some masjids on OpenStreetMap have no name.
    name: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    # Only what OpenStreetMap has in its addr:* tags, or what the user typed.
    address: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WeeklyMasjidPrayers(Base):
    """One row per weekday. True means that prayer is usually at the masjid."""

    __tablename__ = "weekly_masjid_prayers"
    __table_args__ = (UniqueConstraint("user_id", "weekday"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # 0 is Monday, 6 is Sunday, the same as Python's date.weekday().
    weekday: Mapped[int] = mapped_column(SmallInteger)
    fajr: Mapped[bool] = mapped_column(default=False)
    dhuhr: Mapped[bool] = mapped_column(default=False)
    asr: Mapped[bool] = mapped_column(default=False)
    maghrib: Mapped[bool] = mapped_column(default=False)
    isha: Mapped[bool] = mapped_column(default=False)


class UserJumuahMasjid(Base):
    """A masjid the user can go to for Jumuah. A user can have several."""

    __tablename__ = "user_jumuah_masjids"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    masjid_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("masjids.id", ondelete="CASCADE"), primary_key=True
    )


class OverpassCache(Base):
    """Which masjids Overpass found around one grid cell, and when."""

    __tablename__ = "overpass_cache"

    # Like "45.35,-75.91". About 1 km across, so it never pins down a home.
    cell: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Masjid IDs (as strings) from the masjids table.
    masjid_ids: Mapped[list[str]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GeocodeCache(Base):
    """Photon answers, so the same text is never looked up twice.

    The key is an HMAC of the address, so the table can't be searched for
    an address without the secret key. The answer is encrypted.
    """

    __tablename__ = "geocode_cache"

    query_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    result_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApiThrottle(Base):
    """When the app last called an outside service, like Photon.

    Kept in Postgres so every process shares one limit.
    """

    __tablename__ = "api_throttle"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_request_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NightlyJob(Base):
    """One nightly update for one user on one local date.

    The ID is "nightly:{user_id}:{date}", so a retry or a second worker
    finds the same row instead of making a new job.
    """

    __tablename__ = "nightly_jobs"
    __table_args__ = (UniqueConstraint("user_id", "local_date"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    local_date: Mapped[date] = mapped_column(Date)
    # pending, running, done, failed, or needs_sign_in
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    events_sent: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When a failed job may try again.
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
