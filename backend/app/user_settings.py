"""Reading and saving a user's setup answers.

The address, place name, and coordinates are encrypted in the database
and only decrypted here, when the app needs them.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.crypto import decrypt, encrypt
from app.jumuah import JumuahPick
from app.models import Masjid, UserSettings, WeeklyMasjidPrayers
from app.prayer_times import AsrMethod, CalculationMethod

PRAYERS = ("fajr", "dhuhr", "asr", "maghrib", "isha")
# The setup questions, in the order the website asks them. "optional" can
# be skipped, but skipping counts as answering it (with the defaults).
STEPS = ("address", "masjid", "weekly", "optional")
# Calculated times always use these. There's no setting for them.
DEFAULT_METHOD = CalculationMethod.ISNA
DEFAULT_ASR_METHOD = AsrMethod.STANDARD
# The optional step's defaults, used when it's skipped. Users who saved
# the step before these existed keep what they have.
DEFAULT_ARRIVE_EARLY_MINUTES = 5
DEFAULT_JUMUAH_ARRIVE_EARLY_MINUTES = 5
DEFAULT_COLOR_ID = "10"  # Basil, Google Calendar's green


def _empty(user_id: uuid.UUID) -> UserSettings:
    # Column defaults only apply on insert, so an unsaved row needs them set here.
    return UserSettings(
        user_id=user_id,
        optional_saved=False,
        arrive_early_minutes=0,
        jumuah_arrive_early_minutes=DEFAULT_JUMUAH_ARRIVE_EARLY_MINUTES,
    )


def get_settings(db: Session, user_id: uuid.UUID) -> UserSettings:
    """This user's settings row, made empty the first time."""
    row = db.scalars(select(UserSettings).where(UserSettings.user_id == user_id)).first()
    if row is None:
        row = _empty(user_id)
        db.add(row)
        db.flush()
    return row


def find_settings(db: Session, user_id: uuid.UUID) -> UserSettings:
    """This user's settings, or an unsaved empty row. For reading only:
    GET requests must never change data."""
    row = db.scalars(select(UserSettings).where(UserSettings.user_id == user_id)).first()
    return row if row is not None else _empty(user_id)


def save_location(row: UserSettings, label: str, latitude: float, longitude: float, time_zone: str) -> None:
    """Save the place the user picked. All 3 parts point to a home, so all are encrypted."""
    row.address_encrypted = encrypt(label)
    row.place_name_encrypted = encrypt(label)
    row.location_encrypted = encrypt(f"{latitude},{longitude}")
    row.time_zone = time_zone


def read_address(row: UserSettings) -> str | None:
    return decrypt(row.address_encrypted) if row.address_encrypted else None


def read_place_name(row: UserSettings) -> str | None:
    return decrypt(row.place_name_encrypted) if row.place_name_encrypted else None


def read_location(row: UserSettings) -> tuple[float, float] | None:
    if not row.location_encrypted:
        return None
    latitude, longitude = decrypt(row.location_encrypted).split(",")
    return float(latitude), float(longitude)


def weekly_rows(db: Session, user_id: uuid.UUID) -> list[WeeklyMasjidPrayers]:
    return list(
        db.scalars(
            select(WeeklyMasjidPrayers)
            .where(WeeklyMasjidPrayers.user_id == user_id)
            .order_by(WeeklyMasjidPrayers.weekday)
        )
    )


def usable_masjid(db: Session, user_id: uuid.UUID, masjid_id: uuid.UUID) -> Masjid | None:
    """A masjid this user may pick: any OpenStreetMap one, or one they typed in."""
    return db.scalars(
        select(Masjid).where(
            Masjid.id == masjid_id,
            or_(Masjid.source == "openstreetmap", Masjid.created_by_user_id == user_id),
        )
    ).first()


def missing_steps(db: Session, row: UserSettings) -> list[str]:
    missing = []
    if row.location_encrypted is None or row.time_zone is None:
        missing.append("address")
    if row.main_masjid_choice is None or (
        row.main_masjid_choice == "masjid" and row.main_masjid_id is None
    ):
        missing.append("masjid")
    # Someone who prays at home skips the grid.
    if row.main_masjid_choice != "home" and len(weekly_rows(db, row.user_id)) != 7:
        missing.append("weekly")
    if not row.optional_saved:
        missing.append("optional")
    return missing


@dataclass(frozen=True)
class Setup:
    """Everything the calendar needs, decrypted and checked."""

    latitude: float
    longitude: float
    time_zone: str
    method: CalculationMethod
    asr_method: AsrMethod
    # None when the user prays at home.
    masjid: Masjid | None
    # What event titles say, like "KMA" in "Dhuhr at KMA".
    masjid_label: str | None
    # weekday (0 is Monday) -> the prayers usually prayed at the masjid
    at_masjid: dict[int, frozenset[str]]
    user_id: uuid.UUID | None = None
    arrive_early_minutes: int = 0
    jumuah_arrive_early_minutes: int = 5
    # The Jumuah the user picked, or None for the earliest that fits.
    jumuah_pick: "JumuahPick | None" = None
    # Google event colours, "1" to "11". None uses the calendar's colour.
    prayer_color_id: str | None = None
    drive_color_id: str | None = None
    # Popup reminders, minutes before the event. None means no reminder.
    masjid_reminder_minutes: int | None = None
    leave_reminder_minutes: int | None = None
    home_reminder_minutes: int | None = None

    @property
    def jumuah_masjid(self) -> Masjid | None:
        """Jumuah is always at the main masjid. Praying at home means no Jumuah."""
        return self.masjid

    def label_for(self, masjid: Masjid) -> str:
        """The main masjid's short name if this is it, otherwise the masjid's name."""
        if self.masjid is not None and masjid.id == self.masjid.id:
            return self.masjid_label
        return masjid_label(masjid, None)

    def place_for(self, weekday: int, prayer: str) -> str:
        if self.masjid is not None and prayer in self.at_masjid.get(weekday, frozenset()):
            return "masjid"
        return "home"


def masjid_label(masjid: Masjid, short_name: str | None) -> str:
    return short_name or masjid.name or "the masjid"


def load_setup(db: Session, user_id: uuid.UUID, preview: bool = False) -> Setup | None:
    """The user's setup, or None if setup isn't finished.

    preview: for the "Adding your prayers" page, which opens while setup is
    finishing. Only the required answers are needed; the optional ones use
    what's saved (the defaults until they're saved).
    """
    row = db.scalars(select(UserSettings).where(UserSettings.user_id == user_id)).first()
    if row is None:
        return None
    missing = [step for step in missing_steps(db, row) if not (preview and step == "optional")]
    if missing or (row.setup_completed_at is None and not preview):
        return None
    latitude, longitude = read_location(row)
    masjid = None
    if row.main_masjid_choice == "masjid" and row.main_masjid_id is not None:
        masjid = db.get(Masjid, row.main_masjid_id)
    at_masjid = {
        day.weekday: frozenset(p for p in PRAYERS if getattr(day, p))
        for day in weekly_rows(db, user_id)
    }
    return Setup(
        latitude=latitude,
        longitude=longitude,
        time_zone=row.time_zone,
        method=DEFAULT_METHOD,
        asr_method=DEFAULT_ASR_METHOD,
        masjid=masjid,
        masjid_label=masjid_label(masjid, row.main_masjid_short_name) if masjid else None,
        at_masjid=at_masjid,
        user_id=user_id,
        arrive_early_minutes=row.arrive_early_minutes or 0,
        jumuah_arrive_early_minutes=row.jumuah_arrive_early_minutes,
        jumuah_pick=(
            JumuahPick(row.jumuah_pick_masjid_id, row.jumuah_pick_order)
            if row.jumuah_pick_masjid_id is not None and row.jumuah_pick_order is not None
            else None
        ),
        prayer_color_id=row.prayer_color_id,
        drive_color_id=row.drive_color_id,
        masjid_reminder_minutes=row.masjid_reminder_minutes,
        leave_reminder_minutes=row.leave_reminder_minutes,
        home_reminder_minutes=row.home_reminder_minutes,
    )
