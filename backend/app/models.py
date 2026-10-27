"""Database tables.

Every table that holds a user's data has a user_id, so every query can be limited to
one user. That's how one user can never see another user's data.
"""

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    Time,
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
    # One row per prayer per day per user, plus one for its drive block.
    # Running twice updates these rows.
    __table_args__ = (UniqueConstraint("user_id", "local_date", "prayer", "kind"),)

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
    # "pending" until Google confirms it, then "synced". Drive blocks can
    # also be "delete_pending" and then "deleted".
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
    # "prayer", or "drive" for the drive block before a masjid prayer.
    kind: Mapped[str] = mapped_column(String(8), default="prayer", server_default="prayer")
    # Google's event colour, "1" to "11". Empty uses the calendar's colour.
    color_id: Mapped[str | None] = mapped_column(String(2))
    # A popup this many minutes before the start. Empty means no reminder at all.
    reminder_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    # "normal", "moved" (busy times moved it), or "clash" (no free time at all).
    # When free/busy fails, moved and clash rows are kept as they are.
    fit: Mapped[str] = mapped_column(String(8), default="normal", server_default="normal")


class UserCountChange(Base):
    """How many people signed up and deleted their account in each hour.

    The /stats graph adds these up, so it goes down when someone deletes
    their account. Counts per hour only: no user ID, no email, nothing that
    leads back to a person. Deleting an account adds 1 to "deleted" and
    leaves "signed_up" alone, so the history stays right.
    """

    __tablename__ = "user_count_changes"

    # The start of the hour, in UTC. Real hours, so daylight saving can't merge or skip any.
    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    signed_up: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    deleted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


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
    # "masjid" or "home". Empty until the masjid step is saved.
    main_masjid_choice: Mapped[str | None] = mapped_column(String(8))
    main_masjid_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("masjids.id", ondelete="SET NULL")
    )
    # Like "KMA". Used in event titles instead of the full name.
    main_masjid_short_name: Mapped[str | None] = mapped_column(String(40))
    # The optional setup step. True once it's saved or skipped.
    optional_saved: Mapped[bool] = mapped_column(default=False, server_default="false")
    # How many minutes before iqamah the user wants to arrive, 0 to 60.
    arrive_early_minutes: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    # The same for Jumuah, 0 to 60. Jumuah often needs more time to park and find a spot.
    jumuah_arrive_early_minutes: Mapped[int] = mapped_column(SmallInteger, default=5, server_default="5")
    # The Jumuah the user picked: a masjid and the slot's order (1, 2, or 3),
    # not a clock time, since a masjid's 3rd Jumuah can move every week.
    jumuah_pick_masjid_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("masjids.id", ondelete="SET NULL")
    )
    jumuah_pick_order: Mapped[int | None] = mapped_column(SmallInteger)
    # Google event colours, "1" to "11". Empty uses the calendar's colour.
    prayer_color_id: Mapped[str | None] = mapped_column(String(2))
    drive_color_id: Mapped[str | None] = mapped_column(String(2))
    # Google Calendar popup reminders, in minutes before the event. Empty means no reminder at all.
    # New and existing users start with 5 minutes before leaving and at home, and none before iqamah.
    # Before iqamah: masjid prayer blocks, Jumuah too. Before leaving: drive blocks. At home: home prayers.
    masjid_reminder_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    leave_reminder_minutes: Mapped[int | None] = mapped_column(SmallInteger, default=5, server_default="5")
    home_reminder_minutes: Mapped[int | None] = mapped_column(SmallInteger, default=5, server_default="5")
    setup_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Masjid(Base):
    """A masjid a user picked: one Photon found on OpenStreetMap, or an address.

    OpenStreetMap masjids are public, so every user can pick them. A masjid
    picked by its address has created_by_user_id, and only that user sees
    it. Nothing here is made up: no guessed name or address, and no times.
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
    # Only what OpenStreetMap has, like "351 Sandhill Road, Ottawa", or the address the user picked.
    address: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # How long its Jumuah (khutbah and prayer) takes, 15 to 90 minutes. Set
    # with the admin command, since MAWAQIT doesn't publish it. Empty uses 45.
    jumuah_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    # Set by unlink-mawaqit, so a link I removed by hand isn't added back automatically.
    no_auto_link: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MawaqitListEntry(Base):
    """One masjid on my list of MAWAQIT masjids (app/data/mawaqit_masjids.csv).

    MAWAQIT's search needs a login, so the app can't find a masjid's page by
    itself. I collect them by hand, and the app matches users' masjids to
    this list by distance and name (see masjid_times/match.py).
    """

    __tablename__ = "mawaqit_list"

    # "id/9793" for a share link (mawaqit.net/en/id/9793), or a page name like "cio-gatineau".
    external_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    # "file" (the CSV) or "admin" (python -m app.admin add-mawaqit).
    added_by: Mapped[str] = mapped_column(String(8))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class MasjidSource(Base):
    """Where a masjid's times are read from.

    I add these with link-mawaqit (origin "admin"), or the app adds them by
    matching the masjid to my MAWAQIT list (origin "auto"). An automatic
    link never replaces one of mine.

    external_id is the masjid's ID on that source: a MAWAQIT page name, or
    "id/9793" for a share link. The app builds the URL itself, so a saved
    value can't point anywhere else.
    """

    __tablename__ = "masjid_sources"

    masjid_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("masjids.id", ondelete="CASCADE"), primary_key=True
    )
    # "mawaqit" for now. Each source has its own adapter.
    source: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(200))
    # "admin" or "auto". Links made before automatic matching are all "admin".
    origin: Mapped[str] = mapped_column(String(8), default="admin", server_default="admin")
    # For an automatic link: the list entry it matched, and how far apart they are, for spot-checks.
    list_external_id: Mapped[str | None] = mapped_column(
        ForeignKey("mawaqit_list.external_id", ondelete="SET NULL")
    )
    match_distance_m: Mapped[int | None] = mapped_column(Integer)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The last fetch that passed every check. Freshness is measured from this.
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The last time a fetch changed a future time. Event descriptions show this date.
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # After a 403, a 429, or 3 failures in a row, no fetch before this.
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class MasjidDayTimes(Base):
    """One masjid's published times for one local date.

    Times are clock times in the masjid's time zone, not instants, so the
    daylight saving offset is applied for that exact date when an event is
    built. Iqamah is empty when the masjid didn't publish one.
    """

    __tablename__ = "masjid_day_times"
    __table_args__ = (UniqueConstraint("masjid_id", "local_date", "source"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    masjid_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("masjids.id", ondelete="CASCADE"), index=True)
    local_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(16))
    fajr_adhan: Mapped[time] = mapped_column(Time)
    dhuhr_adhan: Mapped[time] = mapped_column(Time)
    asr_adhan: Mapped[time] = mapped_column(Time)
    maghrib_adhan: Mapped[time] = mapped_column(Time)
    isha_adhan: Mapped[time] = mapped_column(Time)
    fajr_iqamah: Mapped[time | None] = mapped_column(Time)
    dhuhr_iqamah: Mapped[time | None] = mapped_column(Time)
    asr_iqamah: Mapped[time | None] = mapped_column(Time)
    maghrib_iqamah: Mapped[time | None] = mapped_column(Time)
    isha_iqamah: Mapped[time | None] = mapped_column(Time)
    # Jumuah slots like {"order": 1, "time": "12:45"}, in MAWAQIT's order.
    # Only on the coming Friday, since later ones aren't published yet.
    jumuah: Mapped[list] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MasjidFetchJob(Base):
    """One read of one masjid's source.

    The ID is "{source}:{masjid_id}:{6-hour block}", so each masjid is read
    at most once per block, however many users picked it.
    """

    __tablename__ = "masjid_fetch_jobs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    masjid_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("masjids.id", ondelete="CASCADE"), index=True)
    # pending, running, done, failed, or blocked
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class UserDriveTime(Base):
    """How long the drive from one user's home to one masjid takes.

    route_key is a keyed hash of the rounded home and masjid points. If
    either one moves, the key changes and the drive time is asked again.
    The points themselves are never stored here.
    """

    __tablename__ = "user_drive_times"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    masjid_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("masjids.id", ondelete="CASCADE"), primary_key=True
    )
    # Empty when there's no route.
    seconds: Mapped[int | None] = mapped_column(Integer)
    # "ok" or "no_route"
    status: Mapped[str] = mapped_column(String(16))
    route_key: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UpdateJob(Base):
    """A queued calendar update for one user, outside the nightly run.

    The ID is "update:{user_id}", one row per user. Queuing again while it's
    waiting changes nothing, so 5 changes in a row become 1 update.
    """

    __tablename__ = "update_jobs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    # pending, running, done, failed, needs_sign_in, or skipped
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # Why it was queued last, like "settings" or "mawaqit".
    reason: Mapped[str] = mapped_column(String(32))
    # When it was last queued. If that's after the run started, it runs again.
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    events_sent: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class BusyCheckJob(Base):
    """One 5-minute check of a user's busy times for today and tomorrow.

    Saved before it runs. The ID is "busy:{user_id}:{block}", where the
    block is the 5 minutes in UTC it belongs to, so a second worker or a
    retry in the same block finds the same row and does nothing.
    """

    __tablename__ = "busy_check_jobs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    block_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # pending, running, done, failed, skipped, or needs_sign_in
    status: Mapped[str] = mapped_column(String(16), default="pending")
    events_sent: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class GeocodeCache(Base):
    """Photon answers, so the same search is never sent twice.

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
