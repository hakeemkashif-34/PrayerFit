"""Users, masjids, and MAWAQIT links for the milestone 5 tests."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Masjid, MasjidSource, User
from tests.conftest import new_client, sign_in
from tests.mawaqit_pages import conf, page
from tests.setup_helpers import save_setup


def add_user(fake_google, engine, sub: str, **setup) -> uuid.UUID:
    """A user who signed in and finished setup. Returns their ID."""
    with new_client() as browser:
        sign_in(browser, fake_google, sub=sub, email=f"{sub}@example.com")
    save_setup(engine, sub=sub, **setup)
    return user_id(engine, sub)


def user_id(engine, sub: str) -> uuid.UUID:
    with Session(engine) as db:
        return db.scalars(select(User.id).where(User.google_sub == sub)).one()


def masjid_id(engine, name: str) -> uuid.UUID:
    with Session(engine) as db:
        return db.scalars(select(Masjid.id).where(Masjid.name == name)).one()


def add_masjid(engine, name: str, latitude: float = 45.43, longitude: float = -75.70, osm_id: int | None = None) -> uuid.UUID:
    with Session(engine) as db:
        masjid = Masjid(
            source="openstreetmap", osm_type="node", osm_id=osm_id or abs(hash(name)) % 10**9,
            name=name, latitude=latitude, longitude=longitude, address="1 Masjid Road, Ottawa",
        )
        db.add(masjid)
        db.commit()
        return masjid.id


def link(engine, masjid: uuid.UUID, slug: str, fake_mawaqit=None, data: dict | None = None, at: datetime | None = None) -> None:
    """Link a masjid to a MAWAQIT page, and put that page on the fake MAWAQIT."""
    with Session(engine) as db:
        db.add(MasjidSource(masjid_id=masjid, source="mawaqit", external_id=slug, **({"linked_at": at} if at else {})))
        db.commit()
    if fake_mawaqit is not None:
        fake_mawaqit.pages[slug] = page(data if data is not None else conf())
