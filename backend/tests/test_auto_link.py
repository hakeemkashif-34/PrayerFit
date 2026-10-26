"""Linking masjids to MAWAQIT automatically from my list (app/masjid_times/auto_link.py).

In setup, the fake Photon has "Kanata Muslim Association" at 45.3188,
-75.8987 (see setup_helpers.py). Tests put it on the list at that spot, as
id/9793, and give the fake MAWAQIT a page there with a 1st Jumuah at 1:15.
"""

import uuid
from datetime import date, datetime
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import httpx2
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import admin
from app.masjid_times.auto_link import auto_link, rematch_picked
from app.masjid_times.mawaqit_list import ListRow, save_rows
from app.masjid_times.scan import (
    MapMasjid,
    ScanFailed,
    find_masjids,
    overpass_query,
    scan_lines,
)
from app.models import Masjid, MasjidSource, MawaqitListEntry
from tests.conftest import sign_in
from tests.masjid_helpers import add_user, masjid_id
from tests.mawaqit_pages import conf, page
from tests.setup_helpers import HOME, pick_masjid, setup_through_api

TORONTO = ZoneInfo("America/Toronto")
DAY = date(2026, 10, 25)  # Sunday
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=TORONTO)
KMA_ON_MAP = (HOME[0] + 0.01, HOME[1])
KMA_LABEL = "Kanata Muslim Association"


def put_on_list(db, external_id="id/9793", name=KMA_LABEL, at=KMA_ON_MAP, metres_north=30) -> None:
    with Session(db) as session:
        save_rows(session, [ListRow(external_id, name, at[0] + metres_north / 111_195, at[1])], "file", NOW)
        session.commit()


def source_of(db, masjid) -> MasjidSource | None:
    with Session(db) as session:
        return session.get(MasjidSource, uuid.UUID(str(masjid)))


def mawaqit_paths(fake_mawaqit) -> list[str]:
    return [r.url.path for r in fake_mawaqit.requests]


def slots(client, masjid_id: str) -> dict:
    response = client.post("/jumuah/slots", json={"masjid_id": masjid_id})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def signed_in(client, fake_google, fake_photon, set_today):
    sign_in(client, fake_google)
    set_today(DAY)
    # The location only, so masjid searches work.
    setup_through_api(client, fake_photon, masjid=None, finish=False)
    return client


@pytest.fixture
def kma_page(fake_mawaqit):
    fake_mawaqit.pages["id/9793"] = page(conf(jumua="13:15", jumua2=None))
    return fake_mawaqit


# ---- In setup ----


def test_picking_a_listed_masjid_links_it_and_reads_its_times_straight_away(signed_in, db, kma_page):
    put_on_list(db)
    picked = pick_masjid(signed_in, "Kanata", KMA_LABEL)

    source = source_of(db, picked["id"])
    assert (source.external_id, source.origin, source.list_external_id, source.match_distance_m) == (
        "id/9793", "auto", "id/9793", 30,
    )
    # Read from the share link, during the pick.
    assert mawaqit_paths(kma_page) == ["/en/id/9793"]
    assert picked["iqamah_status"] != "not_linked"
    # So the Jumuah question already has the masjid's real Jumuah.
    data = slots(signed_in, picked["id"])
    assert [datetime.fromisoformat(s["starts_at"]).astimezone(TORONTO).strftime("%H:%M") for s in data["slots"]] == ["13:15"]
    assert data["no_times"] == []


def test_picking_it_again_doesnt_read_mawaqit_again(signed_in, db, kma_page):
    put_on_list(db)
    pick_masjid(signed_in, "Kanata", KMA_LABEL)
    pick_masjid(signed_in, "Kanata", KMA_LABEL)
    assert mawaqit_paths(kma_page) == ["/en/id/9793"]


def test_a_masjid_that_isnt_listed_isnt_linked(signed_in, db, kma_page):
    put_on_list(db, metres_north=250)
    picked = pick_masjid(signed_in, "Kanata", KMA_LABEL)
    assert source_of(db, picked["id"]) is None
    assert kma_page.requests == []


def test_mawaqit_being_down_never_stops_picking_a_masjid(signed_in, db, kma_page):
    put_on_list(db)
    kma_page.failure = 500
    picked = pick_masjid(signed_in, "Kanata", KMA_LABEL)
    assert picked["name"] == KMA_LABEL
    # Still linked, so the worker tries again in the next 6-hour block.
    assert source_of(db, picked["id"]).last_error == "MAWAQIT answered 500"
    assert slots(signed_in, picked["id"])["no_times"] != []


# ---- My links come first ----


def test_a_manual_link_is_never_replaced(signed_in, db, kma_page, fake_google):
    picked = pick_masjid(signed_in, "Kanata", KMA_LABEL)
    with Session(db) as session:
        admin.link_mawaqit(session, picked["id"], "https://mawaqit.net/en/kma-masjid-ottawa", NOW)
    put_on_list(db)
    signed_in.put("/settings/main-masjid", json={"choice": "masjid", "masjid_id": picked["id"]})

    # Not by picking it again in setup,
    pick_masjid(signed_in, "Kanata", KMA_LABEL)
    # nor by a list change,
    with Session(db) as session:
        assert rematch_picked(session, NOW) == []
    # nor by add-mawaqit.
    with Session(db) as session:
        admin.add_mawaqit(session, "https://mawaqit.net/en/id/1", "Kanata Masjid", str(KMA_ON_MAP[0]), str(KMA_ON_MAP[1]), NOW)
    source = source_of(db, picked["id"])
    assert (source.external_id, source.origin, source.list_external_id) == ("kma-masjid-ottawa", "admin", None)


def test_linking_by_hand_replaces_an_automatic_link(signed_in, db, kma_page):
    put_on_list(db)
    picked = pick_masjid(signed_in, "Kanata", KMA_LABEL)
    with Session(db) as session:
        admin.link_mawaqit(session, picked["id"], "https://mawaqit.net/en/kma-masjid-ottawa", NOW)
    source = source_of(db, picked["id"])
    assert (source.external_id, source.origin, source.match_distance_m) == ("kma-masjid-ottawa", "admin", None)


def test_linking_the_same_page_by_hand_makes_it_mine(signed_in, db, kma_page):
    put_on_list(db)
    picked = pick_masjid(signed_in, "Kanata", KMA_LABEL)
    with Session(db) as session:
        message = admin.link_mawaqit(session, picked["id"], "https://mawaqit.net/en/id/9793", NOW)
    assert "already linked to MAWAQIT id/9793" in message
    assert source_of(db, picked["id"]).origin == "admin"


def test_a_masjid_unlinked_by_hand_isnt_linked_again(signed_in, db, kma_page):
    put_on_list(db)
    picked = pick_masjid(signed_in, "Kanata", KMA_LABEL)
    signed_in.put("/settings/main-masjid", json={"choice": "masjid", "masjid_id": picked["id"]})
    with Session(db) as session:
        admin.unlink_mawaqit(session, picked["id"], NOW)

    pick_masjid(signed_in, "Kanata", KMA_LABEL)
    with Session(db) as session:
        assert rematch_picked(session, NOW) == []
    assert source_of(db, picked["id"]) is None
    with Session(db) as session:
        assert "won't be linked automatically" in "\n".join(admin.list_masjids(session))
        # Linking it by hand again clears that.
        admin.link_mawaqit(session, picked["id"], "https://mawaqit.net/en/id/9793", NOW)
        assert session.get(Masjid, uuid.UUID(picked["id"])).no_auto_link is False


def test_a_masjid_with_no_location_is_never_linked(db):
    put_on_list(db)
    with Session(db) as session:
        masjid = Masjid(source="openstreetmap", osm_type="node", osm_id=1, name=KMA_LABEL)
        session.add(masjid)
        session.flush()
        assert auto_link(session, masjid, NOW).status == "no match"


# ---- add-mawaqit ----


def test_add_mawaqit_adds_to_the_list_and_links_users_masjids(db, fake_google):
    # The test KMA from add_user is at 45.4315, -75.6972. Signing in starts the app, which loads
    # the real list, so this uses an ID that isn't on it.
    add_user(fake_google, db, "user-a", masjid_name="KMA")
    with Session(db) as session:
        lines = admin.add_mawaqit(session, "https://mawaqit.net/en/id/99999", " Kanata  Muslim Association ", "45.4316", "-75.6972", NOW)
    assert lines[0] == "Saved Kanata Muslim Association (id/99999) at 45.4316, -75.6972."
    assert lines[1] == "Linked KMA to id/99999 (11 m)."
    assert "app/data/mawaqit_masjids.csv" in lines[-1]
    with Session(db) as session:
        entry = session.get(MawaqitListEntry, "id/99999")
        assert (entry.name, entry.added_by) == ("Kanata Muslim Association", "admin")
    assert source_of(db, masjid_id(db, "KMA")).origin == "auto"

    # The same again changes nothing.
    with Session(db) as session:
        lines = admin.add_mawaqit(session, "https://mawaqit.net/id/99999", "Kanata Muslim Association", "45.4316", "-75.6972", NOW)
    assert lines[0] == "Kanata Muslim Association (id/99999) is already on the list, with the same name and location."


def test_add_mawaqit_takes_page_links_too(db):
    with Session(db) as session:
        admin.add_mawaqit(session, "https://mawaqit.net/en/cio-gatineau", "Mosquee de Gatineau - CIO", "45.4290189", "-75.732133", NOW)
        assert session.get(MawaqitListEntry, "cio-gatineau") is not None


@pytest.mark.parametrize(
    "link, lat, lon, message",
    [
        ("https://example.com/en/id/1", "45.3", "-75.8", "mawaqit.net"),
        ("https://mawaqit.net/en/id/abc", "45.3", "-75.8", "ends in a number"),
        ("https://mawaqit.net/en/id/1", "north", "-75.8", "must be numbers"),
        ("https://mawaqit.net/en/id/1", "95", "-75.8", "latitude must be from -90 to 90"),
    ],
)
def test_add_mawaqit_refuses_bad_details(db, link, lat, lon, message):
    with Session(db) as session, pytest.raises(SystemExit, match=message):
        admin.add_mawaqit(session, link, "A Masjid", lat, lon, NOW)
    with Session(db) as session:
        assert session.scalars(select(MawaqitListEntry)).all() == []


def test_the_add_mawaqit_command(db, monkeypatch, capsys):
    monkeypatch.setattr(admin, "get_engine", lambda: db)
    admin.main(["add-mawaqit", "https://mawaqit.net/en/id/9793", "--name", "Kanata Muslim Association", "--lat", "45.356128", "--lon", "-75.9283718"])
    assert "Saved Kanata Muslim Association (id/9793)" in capsys.readouterr().out


# ---- list-masjids ----


def test_list_masjids_says_which_links_are_automatic(signed_in, db, kma_page):
    put_on_list(db)
    pick_masjid(signed_in, "Kanata", KMA_LABEL)
    with Session(db) as session:
        assert "[MAWAQIT id/9793 (automatic)" in "\n".join(admin.list_masjids(session))


# ---- scan-area ----

OVERPASS_ANSWER = {
    "elements": [
        {"type": "node", "id": 1, "lat": 45.3562, "lon": -75.9284, "tags": {"name": "Kanata Masjid", "amenity": "place_of_worship"}},
        {"type": "way", "id": 2, "center": {"lat": 45.5, "lon": -75.5}, "tags": {"name": "Far Away Masjid"}},
        {"type": "node", "id": 3, "lat": 45.3265, "lon": -75.72, "tags": {}},
        {"type": "relation", "id": 4, "tags": {"name": "No Point"}},
    ]
}


class FakeOverpass:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx2.Request] = []

    def client(self) -> httpx2.Client:
        def route(request: httpx2.Request) -> httpx2.Response:
            assert request.url.host == "overpass-api.de"
            self.requests.append(request)
            return httpx2.Response(self.status, json=OVERPASS_ANSWER)

        return httpx2.Client(transport=httpx2.MockTransport(route))


def test_the_overpass_query_asks_for_masjids_within_40_km():
    assert overpass_query(45.4215, -75.6972, 40) == (
        '[out:json][timeout:60];nwr["amenity"="place_of_worship"]["religion"="muslim"](around:40000,45.4215,-75.6972);'
        "out center tags;"
    )


def test_find_masjids_reads_points_and_outlines():
    fake = FakeOverpass()
    with fake.client() as http:
        found = find_masjids(http, 45.4215, -75.6972, 40)
    assert found == [
        MapMasjid("Kanata Masjid", 45.3562, -75.9284),
        MapMasjid("Far Away Masjid", 45.5, -75.5),
        MapMasjid(None, 45.3265, -75.72),
    ]
    assert "PrayerFit" in fake.requests[0].headers["user-agent"]


def test_an_overpass_error_is_a_clear_message():
    with FakeOverpass(504).client() as http, pytest.raises(ScanFailed, match="answered 504"):
        find_masjids(http, 45.4215, -75.6972, 40)


def test_scan_lines_say_linked_no_match_or_unclear():
    from app.masjid_times.match import Listed

    listed = [
        Listed("id/9793", "Kanata Muslim Association", 45.356128, -75.9283718),
        Listed("id/14718", "MAC QIC", 45.326052, -75.7198339),
        Listed("id/2", "Second Masjid", 45.3266, -75.7199),
    ]
    found = [MapMasjid("Kanata Masjid", 45.3562, -75.9284), MapMasjid("Far Away Masjid", 45.5, -75.5), MapMasjid(None, 45.3263, -75.7199)]
    assert scan_lines(found, listed) == [
        "linked     Kanata Masjid -> id/9793 Kanata Muslim Association (8 m)",
        "unclear    (no name): id/14718 MAC QIC (28 m), id/2 Second Masjid (33 m)",
        "no match   Far Away Masjid (45.50000, -75.50000)",
        "3 masjids on OpenStreetMap: 1 linked, 1 no match, 1 unclear.",
    ]


def test_the_scan_area_command_saves_nothing(db, monkeypatch, capsys):
    put_on_list(db, at=(45.356128, -75.9283718), metres_north=0)
    fake = FakeOverpass()
    monkeypatch.setattr(admin, "get_engine", lambda: db)
    monkeypatch.setattr(admin, "new_http_client", fake.client)
    admin.main(["scan-area"])
    out = capsys.readouterr().out
    assert "linked     Kanata Masjid -> id/9793" in out
    # Ottawa and 40 km when no point is given.
    assert "around:40000,45.4215,-75.6972" in parse_qs(fake.requests[0].content.decode())["data"][0]
    with Session(db) as session:
        assert session.scalars(select(MasjidSource)).all() == []


@pytest.mark.parametrize("km", ["0", "150"])
def test_scan_area_keeps_to_a_city_size(db, monkeypatch, km):
    monkeypatch.setattr(admin, "get_engine", lambda: db)
    with pytest.raises(SystemExit, match="--km must be"):
        admin.main(["scan-area", "--km", km])
