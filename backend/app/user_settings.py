"""Reading and saving a user's setup answers.

The address, place name, and coordinates are encrypted in the database
and only decrypted here, when the app needs them.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.crypto import decrypt, encrypt
from app.geo.nominatim import FoundPlace
from app.models import Masjid, UserJumuahMasjid, UserSettings, WeeklyMasjidPrayers
from app.prayer_times import AsrMethod, CalculationMethod

PRAYERS = ("fajr", "dhuhr", "asr", "maghrib", "isha")
# The setup steps, in the order the website asks them.
STEPS = ("address", "methods", "masjid", "weekly", "jumuah")


def get_settings(db: Session, user_id: uuid.UUID) -> UserSettings:
    """This user's settings row, made empty the first time."""
    row = db.scalars(select(UserSettings).where(UserSettings.user_id == user_id)).first()
    if row is None:
        row = UserSettings(user_id=user_id, jumuah_saved=False)
        db.add(row)
        db.flush()
    return row


def find_settings(db: Session, user_id: uuid.UUID) -> UserSettings:
    """This user's settings, or an unsaved empty row. For reading only:
    GET requests must never change data."""
    row = db.scalars(select(UserSettings).where(UserSettings.user_id == user_id)).first()
    return row if row is not None else UserSettings(user_id=user_id, jumuah_saved=False)


def save_location(row: UserSettings, address: str, found: FoundPlace, time_zone: str) -> None:
    row.address_encrypted = encrypt(address)
    row.place_name_encrypted = encrypt(found.place_name)
    row.location_encrypted = encrypt(f"{found.latitude},{found.longitude}")
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


def jumuah_masjids(db: Session, user_id: uuid.UUID) -> list[Masjid]:
    return list(
        db.scalars(
            select(Masjid)
            .join(UserJumuahMasjid, UserJumuahMasjid.masjid_id == Masjid.id)
            .where(UserJumuahMasjid.user_id == user_id)
            .order_by(Masjid.name)
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
    if row.method is None or row.asr_method is None:
        missing.append("methods")
    if row.main_masjid_choice is None or (
        row.main_masjid_choice == "masjid" and row.main_masjid_id is None
    ):
        missing.append("masjid")
    # Someone who prays at home skips the grid.
    if row.main_masjid_choice != "home" and len(weekly_rows(db, row.user_id)) != 7:
        missing.append("weekly")
    if not row.jumuah_saved:
        missing.append("jumuah")
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

    def place_for(self, weekday: int, prayer: str) -> str:
        if self.masjid is not None and prayer in self.at_masjid.get(weekday, frozenset()):
            return "masjid"
        return "home"


def masjid_label(masjid: Masjid, short_name: str | None) -> str:
    return short_name or masjid.name or "the masjid"


def load_setup(db: Session, user_id: uuid.UUID) -> Setup | None:
    """The user's setup, or None if setup isn't finished."""
    row = db.scalars(select(UserSettings).where(UserSettings.user_id == user_id)).first()
    if row is None or row.setup_completed_at is None or missing_steps(db, row):
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
        method=CalculationMethod(row.method),
        asr_method=AsrMethod(row.asr_method),
        masjid=masjid,
        masjid_label=masjid_label(masjid, row.main_masjid_short_name) if masjid else None,
        at_masjid=at_masjid,
    )
