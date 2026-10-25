"""The admin commands for linking masjids to MAWAQIT."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import admin
from app.models import Masjid, MasjidDayTimes, MasjidSource, UpdateJob
from tests.masjid_helpers import add_user, link, masjid_id, user_id

NOW = datetime(2026, 10, 25, 17, 0, tzinfo=UTC)


@pytest.fixture
def kma(db, fake_google):
    add_user(fake_google, db, "user-a", masjid_name="KMA", at_masjid={0: {"isha"}})
    return masjid_id(db, "KMA")


def test_link_stores_only_the_page_name(db, kma):
    with Session(db) as session:
        message = admin.link_mawaqit(session, str(kma), "https://mawaqit.net/en/kma-kanata?x=1#top", NOW)
    assert "Linked KMA to MAWAQIT kma-kanata" in message
    with Session(db) as session:
        source = session.get(MasjidSource, kma)
    assert (source.source, source.external_id) == ("mawaqit", "kma-kanata")


@pytest.mark.parametrize(
    "link", ["https://example.com/en/kma-kanata", "http://mawaqit.net/en/kma-kanata", "https://mawaqit.net.evil.com/en/kma"]
)
def test_link_rejects_links_that_arent_mawaqit(db, kma, link):
    with Session(db) as session, pytest.raises(SystemExit, match="mawaqit.net"):
        admin.link_mawaqit(session, str(kma), link, NOW)
    with Session(db) as session:
        assert session.get(MasjidSource, kma) is None


def test_link_needs_a_real_masjid(db):
    with Session(db) as session, pytest.raises(SystemExit, match="list-masjids"):
        admin.link_mawaqit(session, "not-an-id", "https://mawaqit.net/en/kma-kanata", NOW)


def test_linking_another_page_drops_the_old_pages_times(db, kma, fake_mawaqit, http):
    from app.masjid_times.scheduler import run_due_fetches

    link(db, kma, "kma-kanata", fake_mawaqit)
    run_due_fetches(db, http, NOW)
    with Session(db) as session:
        admin.link_mawaqit(session, str(kma), "https://mawaqit.net/en/kma-new", NOW)
    with Session(db) as session:
        assert session.get(MasjidSource, kma).external_id == "kma-new"
        assert session.scalars(select(MasjidDayTimes)).all() == []


def test_unlink_removes_times_and_queues_updates(db, kma, fake_mawaqit, http):
    from app.masjid_times.scheduler import run_due_fetches

    link(db, kma, "kma-kanata", fake_mawaqit)
    run_due_fetches(db, http, NOW)
    with Session(db) as session:
        session.execute(UpdateJob.__table__.delete())
        session.commit()
        assert "Updates queued for 1 user" in admin.unlink_mawaqit(session, str(kma), NOW)
    with Session(db) as session:
        assert session.get(MasjidSource, kma) is None
        assert session.scalars(select(MasjidDayTimes)).all() == []
        assert session.get(UpdateJob, f"update:{user_id(db, 'user-a')}").status == "pending"


def test_list_shows_ids_and_links_but_not_typed_in_addresses(db, kma, fake_google):
    with Session(db) as session:
        session.add(Masjid(source="user", address="12 Private Lane, Ottawa", latitude=45.3, longitude=-75.9))
        session.commit()
    link(db, kma, "kma-kanata")
    with Session(db) as session:
        lines = admin.list_masjids(session)
    text = "\n".join(lines)
    assert f"{kma}  KMA  [MAWAQIT kma-kanata]  Jumuah length not set (45 min estimated)  1 user" in text
    assert "(no name, picked by address)  [not linked]  Jumuah length not set (45 min estimated)  0 users" in text
    assert "Private Lane" not in text


def test_set_jumuah_length(db, kma):
    with Session(db) as session:
        message = admin.set_jumuah_length(session, str(kma), 40, NOW)
    assert "Set KMA's Jumuah to 40 minutes. Updates queued for 1 user(s)." == message
    with Session(db) as session:
        assert session.get(Masjid, kma).jumuah_minutes == 40
        assert session.get(UpdateJob, f"update:{user_id(db, 'user-a')}").status == "pending"
        assert f"{kma}  KMA  [not linked]  Jumuah 40 min  1 user" in "\n".join(admin.list_masjids(session))


@pytest.mark.parametrize("minutes", [14, 91, 0, -5])
def test_jumuah_length_is_15_to_90(db, kma, minutes):
    with Session(db) as session, pytest.raises(SystemExit, match="15 to 90"):
        admin.set_jumuah_length(session, str(kma), minutes, NOW)


@pytest.mark.parametrize("typed", ["40.5", "forty", ""])
def test_the_command_takes_whole_minutes_only(db, kma, typed, monkeypatch):
    monkeypatch.setattr(admin, "get_engine", lambda: db)
    with pytest.raises(SystemExit, match="whole number"):
        admin.main(["set-jumuah-length", "--masjid", str(kma), "--minutes", typed])


def test_the_command_sets_it(db, kma, monkeypatch, capsys):
    monkeypatch.setattr(admin, "get_engine", lambda: db)
    admin.main(["set-jumuah-length", "--masjid", str(kma), "--minutes", "30"])
    assert "Jumuah to 30 minutes" in capsys.readouterr().out
