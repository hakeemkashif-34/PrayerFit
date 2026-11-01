"""Setup's masjid search: my MAWAQIT list first, then Photon (app/masjid_search.py).

The bug: a user typed "Barrhaven Islamic Centre" and it didn't show up.
The distance limit wasn't it (Photon already searches 100 km from home, and
Barrhaven is about 15 km from Kanata). Photon only finds what
OpenStreetMap has, under the name and tags it has there, so a masjid that's
missing, named differently, or not tagged as a place of worship can't be found.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.masjid_search import list_score, search_list
from app.masjid_times.match import Listed
from app.masjid_times.mawaqit_list import ListRow, read_file, save_rows
from app.models import Masjid, MasjidSource
from tests.setup_helpers import HOME
from tests.test_auto_link import signed_in  # noqa: F401

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=ZoneInfo("America/Toronto"))
BIC = Listed("id/17559", "Barrhaven Islamic Centre", 45.2364361, -75.7255711, "BIC", "3971 Greenbank Road, Ottawa")
KMA = Listed("id/9793", "Kanata Muslim Association", 45.356128, -75.9283718, "KMA")
OMA = Listed("id/30768", "Ottawa Main Mosque (OMA)", 45.4014817, -75.7413215)
ALSHAREEF = Listed("id/26072", "Alshareef Islamic Centre", 45.3535198, -75.7590002)
DEEP_RIVER = Listed("id/43997", "Ottawa Valley Islamic Centre (Deep River)", 46.0963698, -77.4877557)
ENTRIES = [BIC, KMA, OMA, ALSHAREEF, DEEP_RIVER]


def labels(found) -> list[str]:
    return [s.label for s in found]


# ---- Matching names ----


@pytest.mark.parametrize(
    "typed",
    ["Barrhaven Islamic Centre", "barrhaven", "BIC", "bic", "barhaven islamic", "barr", "Barrhaven Mosque", "barhav islamic"],
)
def test_spelling_mistakes_partial_names_and_the_short_name_all_find_bic(typed):
    assert list_score(typed, BIC) > 0
    assert labels(search_list(typed, ENTRIES, HOME))[0] == "Barrhaven Islamic Centre"


@pytest.mark.parametrize("typed", ["barrhaven omar", "masjid", "centre", "zzz"])
def test_text_that_isnt_bic_doesnt_find_it(typed):
    assert list_score(typed, BIC) == 0


def test_a_short_name_in_brackets_counts_too():
    assert labels(search_list("oma", ENTRIES, HOME)) == ["Ottawa Main Mosque (OMA)"]
    assert labels(search_list("KMA", ENTRIES, HOME)) == ["Kanata Muslim Association"]


def test_equally_good_matches_are_nearest_first_whatever_the_distance():
    found = labels(search_list("islamic centre", ENTRIES, HOME))
    # Deep River is about 170 km away, and still shows, since I listed it by hand.
    # Alshareef is about 12 km from the test home, BIC about 16 km.
    assert found == ["Alshareef Islamic Centre", "Barrhaven Islamic Centre", "Ottawa Valley Islamic Centre (Deep River)"]


def test_bic_is_in_the_real_list_with_its_short_name_and_address():
    by_id = {r.external_id: r for r in read_file()}
    assert by_id["id/17559"] == ListRow(
        "id/17559", "Barrhaven Islamic Centre", 45.2364361, -75.7255711, "BIC", "3971 Greenbank Road, Ottawa"
    )
    entries = [Listed(r.external_id, r.name, r.latitude, r.longitude, r.short_name, r.address) for r in read_file()]
    for typed in ["barrhaven", "BIC", "barhaven islamic"]:
        assert labels(search_list(typed, entries, HOME))[0] == "Barrhaven Islamic Centre"


# ---- Through the API ----


def put_on_list(db, *entries: Listed) -> None:
    with Session(db) as session:
        rows = [ListRow(e.external_id, e.name, e.latitude, e.longitude, e.short_name, e.address) for e in entries]
        save_rows(session, rows, "file", NOW)
        session.commit()


def search(client, query: str) -> list[dict]:
    response = client.post("/setup/masjid/suggest", json={"query": query})
    assert response.status_code == 200, response.text
    return response.json()["suggestions"]


def test_bic_shows_even_when_photon_doesnt_have_it(signed_in, db, fake_photon):
    put_on_list(db, *ENTRIES)
    [bic] = search(signed_in, "Barrhaven Islamic Centre")
    assert (bic["label"], bic["detail"], bic["kind"]) == ("Barrhaven Islamic Centre", "3971 Greenbank Road, Ottawa", "masjid")
    assert 10 < bic["distance_km"] < 25


def test_list_masjids_come_first_then_photon_without_duplicates(signed_in, db, fake_photon):
    put_on_list(db, *ENTRIES)
    # The same masjid on OpenStreetMap: 50 m away, and the same name 1.5 km away.
    fake_photon.add_masjid(201, "Barrhaven Islamic Center", BIC.latitude + 50 / 111_195, BIC.longitude, city="Ottawa")
    fake_photon.add_masjid(202, "Barrhaven Islamic Centre", BIC.latitude + 0.0135, BIC.longitude, city="Ottawa")
    # A different masjid nearby, which stays.
    fake_photon.add_masjid(203, "Barrhaven Masjid", BIC.latitude + 0.02, BIC.longitude + 0.02, city="Ottawa")
    assert [s["label"] for s in search(signed_in, "barrhaven")] == ["Barrhaven Islamic Centre", "Barrhaven Masjid"]


def test_photon_being_down_still_shows_list_masjids(signed_in, db, fake_photon):
    put_on_list(db, *ENTRIES)
    fake_photon.failure = 503
    assert [s["label"] for s in search(signed_in, "BIC")] == ["Barrhaven Islamic Centre"]
    # With nothing on the list, it fails like before.
    response = signed_in.post("/setup/masjid/suggest", json={"query": "Jamia Omar"})
    assert response.status_code == 503


def pick(client, query: str, label: str) -> dict:
    index = next(s["index"] for s in search(client, query) if s["label"] == label)
    response = client.post("/masjids/from-suggestion", json={"query": query, "index": index})
    assert response.status_code == 200, response.text
    return response.json()


def test_picking_bic_from_the_list_links_it_to_its_mawaqit_page(signed_in, db, fake_mawaqit):
    from tests.mawaqit_pages import conf, page

    fake_mawaqit.pages["id/17559"] = page(conf(jumua="12:45", jumua2="14:30"))
    put_on_list(db, *ENTRIES)
    picked = pick(signed_in, "bic", "Barrhaven Islamic Centre")
    assert (picked["source"], picked["address"]) == ("list", "3971 Greenbank Road, Ottawa")
    with Session(db) as session:
        source = session.get(MasjidSource, picked["id"])
        assert (source.external_id, source.origin, source.list_external_id, source.match_distance_m) == (
            "id/17559", "auto", "id/17559", 0,
        )
    # Read straight away, so the Jumuah question has BIC's 2 Jumuah times.
    assert picked["iqamah_status"] != "not_linked"


def test_picking_the_same_list_masjid_again_reuses_its_row(signed_in, db):
    put_on_list(db, *ENTRIES)
    first = pick(signed_in, "bic", "Barrhaven Islamic Centre")
    again = pick(signed_in, "barrhaven", "Barrhaven Islamic Centre")
    assert again["id"] == first["id"]
    with Session(db) as session:
        assert len(session.scalars(select(Masjid).where(Masjid.list_external_id == "id/17559")).all()) == 1


def test_a_pick_from_the_list_reuses_the_openstreetmap_masjid_already_linked_to_it(signed_in, db):
    put_on_list(db, *ENTRIES)
    with Session(db) as session:
        on_map = Masjid(source="openstreetmap", osm_type="node", osm_id=201, name="Barrhaven Islamic Center",
                        latitude=BIC.latitude, longitude=BIC.longitude)
        session.add(on_map)
        session.flush()
        session.add(MasjidSource(masjid_id=on_map.id, source="mawaqit", external_id="id/17559", origin="auto",
                                 list_external_id="id/17559", match_distance_m=10))
        session.commit()
        on_map_id = str(on_map.id)
    assert pick(signed_in, "bic", "Barrhaven Islamic Centre")["id"] == on_map_id


def test_the_list_never_shows_another_users_masjid(signed_in, db):
    # A masjid someone picked by its address is theirs only. The list search never reads the masjids table.
    with Session(db) as session:
        session.add(Masjid(source="user", address="3971 Greenbank Road, Ottawa", latitude=BIC.latitude, longitude=BIC.longitude))
        session.commit()
    assert search(signed_in, "Greenbank") == []
