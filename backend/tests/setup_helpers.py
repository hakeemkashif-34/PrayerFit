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


# ---- Going through setup the way the website does ----

HOME_ADDRESS = "200 Kanata Ave, Ottawa"
HOME_PLACE = "200, Kanata Avenue, Kanata, Ottawa, Ontario, K2T 1K8, Canada"
HOME = (45.3088, -75.8987)  # a made-up point in Kanata


def add_nearby_masjids(fake_osm) -> None:
    """3 masjids "on OpenStreetMap" near HOME, and 1 too far away."""
    fake_osm.add_masjid(101, "Kanata Muslim Association", HOME[0] + 0.01, HOME[1])  # 1.1 km
    fake_osm.add_masjid(102, "Stittsville Masjid", HOME[0] - 0.05, HOME[1] - 0.02, osm_type="way")
    fake_osm.add_masjid(103, "Jamia Omar", HOME[0] + 0.08, HOME[1] + 0.09)
    fake_osm.add_masjid(104, "Downtown Masjid", HOME[0] + 0.11, HOME[1] + 0.2)  # about 19 km


def setup_through_api(
    client,
    fake_osm,
    *,
    masjid: str | None = "Kanata Muslim Association",
    short_name: str | None = "KMA",
    at_masjid: dict[int, list[str]] | None = None,
    finish: bool = True,
):
    """Answer every setup question through the API. Returns the finish response."""
    if not fake_osm.places:
        fake_osm.add_place(HOME_ADDRESS, HOME_PLACE, *HOME)
    if not fake_osm.elements:
        add_nearby_masjids(fake_osm)

    assert client.post("/setup/address/search", json={"address": HOME_ADDRESS}).status_code == 200
    assert client.put("/settings/address", json={"address": HOME_ADDRESS}).status_code == 200
    assert client.put("/settings/methods", json={}).status_code == 200

    nearby = client.get("/masjids/nearby").json()["masjids"]
    by_name = {m["name"]: m["id"] for m in nearby}
    if masjid is None:
        assert client.put("/settings/main-masjid", json={"choice": "home"}).status_code == 200
    else:
        response = client.put(
            "/settings/main-masjid",
            json={"choice": "masjid", "masjid_id": by_name[masjid], "short_name": short_name},
        )
        assert response.status_code == 200
        # Default: Dhuhr and Isha at the masjid on weekdays.
        if at_masjid is None:
            at_masjid = {day: ["dhuhr", "isha"] for day in range(5)}
        days = [
            {"weekday": day, **{p: p in at_masjid.get(day, []) for p in PRAYERS}} for day in range(7)
        ]
        assert client.put("/settings/weekly", json={"days": days}).status_code == 200

    jumuah = [by_name["Kanata Muslim Association"], by_name["Stittsville Masjid"]]
    assert client.put("/settings/jumuah", json={"masjid_ids": jumuah}).status_code == 200
    if finish:
        return client.post("/setup/finish")
    return None
