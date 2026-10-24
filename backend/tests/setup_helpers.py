"""Save a finished setup straight into the database.

Most tests only care what happens after setup, so this skips the setup
questions. test_settings.py goes through the real setup endpoints.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.geo.nominatim import FoundPlace
from app.models import Masjid, User, UserSettings, WeeklyMasjidPrayers
from app.user_settings import PRAYERS, get_settings, save_location

OTTAWA = (45.4215, -75.6972)


def save_setup(
    engine,
    sub: str = "user-a",
    location: tuple[float, float] = OTTAWA,
    time_zone: str = "America/Toronto",
    method: str = "isna",
    asr_method: str = "standard",
    masjid_name: str | None = None,
    short_name: str | None = None,
    at_masjid: dict[int, set[str]] | None = None,
    finished: bool = True,
) -> None:
    """Save (or replace) a user's setup.

    masjid_name: make an OpenStreetMap masjid and pick it. None means "I pray at home".
    at_masjid: weekday (0 is Monday) -> prayers usually at the masjid.
    """
    with Session(engine) as db:
        user = db.scalars(select(User).where(User.google_sub == sub)).one()
        row = get_settings(db, user.id)
        save_location(row, "1 Test Street", FoundPlace("1 Test Street, Ottawa", *location), time_zone)
        row.method = method
        row.asr_method = asr_method
        row.jumuah_saved = True
        if masjid_name is None:
            row.main_masjid_choice = "home"
            row.main_masjid_id = None
        else:
            masjid = db.scalars(select(Masjid).where(Masjid.name == masjid_name)).first()
            if masjid is None:
                masjid = Masjid(
                    source="openstreetmap", osm_type="node", osm_id=abs(hash(masjid_name)) % 10**9,
                    name=masjid_name, latitude=location[0] + 0.01, longitude=location[1],
                )
                db.add(masjid)
                db.flush()
            row.main_masjid_choice = "masjid"
            row.main_masjid_id = masjid.id
            row.main_masjid_short_name = short_name
            saved = {d.weekday: d for d in db.scalars(
                select(WeeklyMasjidPrayers).where(WeeklyMasjidPrayers.user_id == user.id)
            )}
            for weekday in range(7):
                day = saved.get(weekday) or WeeklyMasjidPrayers(user_id=user.id, weekday=weekday)
                db.add(day)
                for prayer in PRAYERS:
                    setattr(day, prayer, prayer in (at_masjid or {}).get(weekday, set()))
        if finished and row.setup_completed_at is None:
            row.setup_completed_at = datetime.now(UTC)
        db.commit()


def settings_row(engine, sub: str = "user-a") -> UserSettings:
    with Session(engine) as db:
        user = db.scalars(select(User).where(User.google_sub == sub)).one()
        return db.scalars(select(UserSettings).where(UserSettings.user_id == user.id)).one()
