"""My list of MAWAQIT masjids (app/data/mawaqit_masjids.csv) and how it loads."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import app
from app.masjid_times.auto_link import load_list, load_list_on_start
from app.masjid_times.mawaqit_list import BadListRow, ListRow, read_file, save_rows
from app.models import MasjidSource, MawaqitListEntry
from tests.conftest import new_client
from tests.masjid_helpers import add_user, masjid_id

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
HEADER = "name,mawaqit_link,latitude,longitude\n"


def saved(db) -> dict[str, MawaqitListEntry]:
    with Session(db) as session:
        return {e.external_id: e for e in session.scalars(select(MawaqitListEntry))}


def write(tmp_path, text: str):
    path = tmp_path / "mawaqit_masjids.csv"
    path.write_text(text, encoding="utf-8")
    return path


# ---- The real file ----


def test_the_real_file_has_23_masjids_with_valid_links():
    rows = read_file()
    assert len(rows) == 23
    by_id = {r.external_id: r for r in rows}
    assert by_id["id/9793"] == ListRow("id/9793", "Kanata Muslim Association", 45.356128, -75.9283718)
    # The one name link: saved as its page name.
    assert by_id["cio-gatineau"].name == "Mosquee de Gatineau - CIO"
    # Every masjid is around Ottawa (Deep River is the furthest, about 170 km away).
    assert all(45 < r.latitude < 46.2 and -77.6 < r.longitude < -75.4 for r in rows)


# ---- Loading ----


def test_each_listed_masjid_loads_once(db):
    assert load_list(db, NOW) == 23
    # Loading again, like the next restart, adds and changes nothing.
    assert load_list(db, NOW) == 0
    with Session(db) as session:
        assert session.scalar(select(func.count()).select_from(MawaqitListEntry)) == 23
    assert {e.added_by for e in saved(db).values()} == {"file"}


def test_the_app_loads_the_list_when_it_starts(db):
    with new_client() as client:  # "with" runs the app's start-up
        assert client.get("/health").status_code == 200
    assert len(saved(db)) == 23
    assert app.router.lifespan_context is not None


def test_a_fixed_name_or_location_replaces_the_saved_one(db):
    with Session(db) as session:
        save_rows(session, [ListRow("id/1", "Old Name", 45.0, -75.0)], "file", NOW)
        assert save_rows(session, [ListRow("id/1", "New Name", 45.1, -75.0)], "file", NOW) == 1
        session.commit()
    entry = saved(db)["id/1"]
    assert (entry.name, entry.latitude) == ("New Name", 45.1)


def test_spaces_after_commas_are_fine(tmp_path):
    path = write(tmp_path, HEADER + "Jami Omar, https://mawaqit.net/en/id/32986, 45.311606, -75.828449\n")
    assert read_file(path) == [ListRow("id/32986", "Jami Omar", 45.311606, -75.828449)]


@pytest.mark.parametrize(
    "line, reason",
    [
        ("Jami Omar,https://example.com/en/id/1,45.3,-75.8", "mawaqit.net"),
        ("Jami Omar,https://mawaqit.net/en/id/abc,45.3,-75.8", "ends in a number"),
        (",https://mawaqit.net/en/id/1,45.3,-75.8", "name is empty"),
        ("Jami Omar,https://mawaqit.net/en/id/1,145.3,-75.8", "latitude"),
        ("Jami Omar,https://mawaqit.net/en/id/1,north,-75.8", "could not convert"),
    ],
)
def test_a_bad_line_says_which_line(tmp_path, line, reason):
    path = write(tmp_path, HEADER + "Kanata Muslim Association,https://mawaqit.net/en/id/9793,45.35,-75.92\n" + line + "\n")
    with pytest.raises(BadListRow, match=f"line 3: .*{reason}"):
        read_file(path)


def test_the_same_masjid_twice_is_refused(tmp_path):
    path = write(tmp_path, HEADER + "A,https://mawaqit.net/en/id/1,45.3,-75.8\nB,https://mawaqit.net/id/1,45.3,-75.8\n")
    with pytest.raises(BadListRow, match="line 3: id/1 is already in the file"):
        read_file(path)


def test_the_header_must_be_right(tmp_path):
    with pytest.raises(BadListRow, match="must start with the line"):
        read_file(write(tmp_path, "name,id,lat,lon\n"))


def test_a_bad_file_doesnt_stop_the_app(db, monkeypatch, caplog):
    import app.masjid_times.auto_link as auto_link

    def broken():
        raise BadListRow("mawaqit_masjids.csv line 5: the name is empty")

    monkeypatch.setattr(auto_link, "read_file", broken)
    load_list_on_start(db)
    assert "Couldn't load the MAWAQIT list" in caplog.text
    assert saved(db) == {}


# ---- A list change ----


def test_a_new_list_links_masjids_users_already_picked(db, fake_google):
    # The test KMA is at 45.4315, -75.6972. Nothing is listed there yet.
    add_user(fake_google, db, "user-a", masjid_name="KMA")
    kma = masjid_id(db, "KMA")
    with Session(db) as session:
        save_rows(session, [ListRow("id/9793", "Kanata Muslim Association", 45.4315 + 40 / 111_195, -75.6972)], "file", NOW)
        session.commit()
    from app.masjid_times.auto_link import rematch_picked

    with Session(db) as session:
        [new] = rematch_picked(session, NOW)
        assert (new.masjid.id, new.found.entry.external_id, new.found.distance_m) == (kma, "id/9793", 40)
    with Session(db) as session:
        source = session.get(MasjidSource, kma)
        assert (source.external_id, source.origin, source.list_external_id, source.match_distance_m) == (
            "id/9793", "auto", "id/9793", 40,
        )
