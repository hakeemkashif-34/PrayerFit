"""Save a finished setup straight into the database.

Most tests only care what happens after setup, so this skips the setup
questions. test_settings.py goes through the real setup endpoints.
"""

from datetime import UTC, datetime

# Long before any "now" the tests use, so the nightly job counts every night.
SETUP_FINISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)

from sqlalchemy import select
from sqlalchemy.orm import Session

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
        save_location(row, "1 Test Street, Ottawa", *location, time_zone)
        row.method = method
        row.asr_method = asr_method
        row.jumuah_saved = True
        row.optional_saved = True
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
            row.setup_completed_at = SETUP_FINISHED_AT
        db.commit()


def settings_row(engine, sub: str = "user-a") -> UserSettings:
    with Session(engine) as db:
        user = db.scalars(select(User).where(User.google_sub == sub)).one()
        return db.scalars(select(UserSettings).where(UserSettings.user_id == user.id)).one()


# ---- Going through setup the way the website does ----

HOME_QUERY = "200 Kanata Ave"
HOME_PLACE = "200 Kanata Avenue, Ottawa, Ontario, Canada"
HOME = (45.3088, -75.8987)  # a made-up point in Kanata


def add_home(fake_photon) -> None:
    """The home "on Photon", plus a place with the same street name in the US."""
    fake_photon.add_place(
        43.1, -77.6, countrycode="US", housenumber="200", street="Kanata Avenue",
        city="Rochester", state="New York", country="United States",
    )
    fake_photon.add_place(
        *HOME, housenumber="200", street="Kanata Avenue", city="Ottawa",
        state="Ontario", postcode="K2T 1K8", country="Canada",
    )


def add_masjids(fake_photon) -> None:
    """Masjids "on Photon": 3 near HOME, 1 in Toronto with a similar name, and a church."""
    fake_photon.add_masjid(
        101, "Kanata Muslim Association", HOME[0] + 0.01, HOME[1],  # 1.1 km
        housenumber="351", street="Sandhill Road", city="Ottawa", state="Ontario", country="Canada",
    )
    fake_photon.add_masjid(
        102, "Stittsville Masjid", HOME[0] - 0.05, HOME[1] - 0.02, osm_type="way",  # 5.8 km
        city="Ottawa", state="Ontario", country="Canada",
    )
    fake_photon.add_masjid(103, "Jamia Omar", HOME[0] + 0.08, HOME[1] + 0.09, city="Ottawa", country="Canada")
    fake_photon.add_masjid(104, "Kanata Masjid Toronto", 43.65, -79.38, city="Toronto", country="Canada")
    fake_photon.add_masjid(105, "St. Paul's Church", HOME[0] + 0.02, HOME[1], city="Ottawa", country="Canada")


def pick_masjid(client, query: str, label: str) -> dict:
    """Type into the masjid box and pick a suggestion, like the website does. Returns the saved masjid."""
    suggestions = client.post("/setup/masjid/suggest", json={"query": query}).json()["suggestions"]
    index = next(s["index"] for s in suggestions if s["label"] == label)
    response = client.post("/masjids/from-suggestion", json={"query": query, "index": index})
    assert response.status_code == 200, response.text
    return response.json()


def setup_through_api(
    client,
    fake_photon,
    *,
    masjid: str | None = "Kanata Muslim Association",
    short_name: str | None = "KMA",
    at_masjid: dict[int, list[str]] | None = None,
    finish: bool = True,
):
    """Answer the 4 setup questions through the API, then finish. Returns the finish response.

    masjid=None means the user pressed "Skip": every prayer at home, no weekly grid.
    """
    if not fake_photon.places:
        add_home(fake_photon)
        add_masjids(fake_photon)

    suggestions = client.post("/setup/location/suggest", json={"query": HOME_QUERY}).json()["suggestions"]
    index = next(s["index"] for s in suggestions if s["label"] == HOME_PLACE)
    assert client.put("/settings/location", json={"query": HOME_QUERY, "index": index}).status_code == 200

    if masjid is None:
        assert client.put("/settings/main-masjid", json={"choice": "home"}).status_code == 200
    else:
        picked = pick_masjid(client, masjid, masjid)
        response = client.put("/settings/main-masjid", json={"choice": "masjid", "masjid_id": picked["id"]})
        assert response.status_code == 200
        # Default: Dhuhr and Isha at the masjid on weekdays.
        if at_masjid is None:
            at_masjid = {day: ["dhuhr", "isha"] for day in range(5)}
        days = [
            {"weekday": day, **{p: p in at_masjid.get(day, []) for p in PRAYERS}} for day in range(7)
        ]
        assert client.put("/settings/weekly", json={"days": days}).status_code == 200

    # The optional step. The short name is part of it.
    response = client.put("/settings/optional", json={"short_name": short_name if masjid else None})
    assert response.status_code == 200, response.text

    if finish:
        return client.post("/setup/finish")
    return None
