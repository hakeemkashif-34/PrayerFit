"""The main masjid becomes the first Jumuah masjid, so users don't pick it twice."""

from datetime import date

import pytest

from tests.conftest import sign_in
from tests.setup_helpers import pick_masjid, setup_through_api

DAY = date(2026, 10, 24)


@pytest.fixture
def signed_in(client, fake_google, set_today):
    sign_in(client, fake_google)
    set_today(DAY)
    return client


def jumuah_names(client) -> list[str]:
    return [m["name"] for m in client.get("/settings").json()["jumuah_masjids"]]


def pick_main(client, query: str, name: str) -> dict:
    masjid = pick_masjid(client, query, name)
    response = client.put("/settings/main-masjid", json={"choice": "masjid", "masjid_id": masjid["id"]})
    assert response.status_code == 200, response.text
    return masjid


def test_picking_a_main_masjid_adds_it_as_the_first_jumuah_masjid(signed_in, fake_photon):
    setup_through_api(signed_in, fake_photon, finish=False)
    settings = signed_in.get("/settings").json()
    assert jumuah_names(signed_in) == ["Kanata Muslim Association"]
    assert settings["jumuah_masjids"][0]["id"] == settings["main_masjid"]["id"]
    assert settings["jumuah_saved"] is True


def test_it_can_be_removed_and_others_added(signed_in, fake_photon):
    setup_through_api(signed_in, fake_photon)
    stittsville = pick_masjid(signed_in, "Stittsville", "Stittsville Masjid")
    jamia = pick_masjid(signed_in, "Jamia Omar", "Jamia Omar")
    response = signed_in.put("/settings/jumuah", json={"masjid_ids": [stittsville["id"], jamia["id"]]})
    assert response.status_code == 200
    assert jumuah_names(signed_in) == ["Stittsville Masjid", "Jamia Omar"]
    # Saving the same main masjid again doesn't add it back.
    main = signed_in.get("/settings").json()["main_masjid"]
    signed_in.put("/settings/main-masjid", json={"choice": "masjid", "masjid_id": main["id"]})
    assert jumuah_names(signed_in) == ["Stittsville Masjid", "Jamia Omar"]


def test_removing_it_then_saving_the_same_main_masjid_keeps_it_removed(signed_in, fake_photon):
    setup_through_api(signed_in, fake_photon)
    signed_in.put("/settings/jumuah", json={"masjid_ids": []})
    main = signed_in.get("/settings").json()["main_masjid"]
    signed_in.put("/settings/main-masjid", json={"choice": "masjid", "masjid_id": main["id"]})
    assert jumuah_names(signed_in) == []


def test_a_new_main_masjid_takes_the_old_ones_place(signed_in, fake_photon):
    setup_through_api(signed_in, fake_photon)
    pick_main(signed_in, "Stittsville", "Stittsville Masjid")
    assert jumuah_names(signed_in) == ["Stittsville Masjid"]


def test_a_list_the_user_changed_is_left_alone(signed_in, fake_photon):
    setup_through_api(signed_in, fake_photon)
    kma = signed_in.get("/settings").json()["main_masjid"]
    jamia = pick_masjid(signed_in, "Jamia Omar", "Jamia Omar")
    signed_in.put("/settings/jumuah", json={"masjid_ids": [kma["id"], jamia["id"]]})
    pick_main(signed_in, "Stittsville", "Stittsville Masjid")
    assert jumuah_names(signed_in) == ["Kanata Muslim Association", "Jamia Omar"]

    # A list that's only some other masjid isn't the old main masjid, so it stays too.
    signed_in.put("/settings/jumuah", json={"masjid_ids": [jamia["id"]]})
    pick_main(signed_in, "Kanata Muslim", "Kanata Muslim Association")
    assert jumuah_names(signed_in) == ["Jamia Omar"]


def test_skipping_the_masjid_step_means_no_jumuah(signed_in, fake_photon):
    response = setup_through_api(signed_in, fake_photon, masjid=None)
    assert response.json()["settings"]["jumuah_masjids"] == []


def test_picking_a_masjid_then_going_back_and_skipping_means_no_jumuah(signed_in, fake_photon):
    setup_through_api(signed_in, fake_photon, finish=False)
    assert jumuah_names(signed_in) == ["Kanata Muslim Association"]
    signed_in.put("/settings/main-masjid", json={"choice": "home"})
    assert jumuah_names(signed_in) == []


def test_praying_at_home_keeps_a_list_the_user_chose(signed_in, fake_photon):
    setup_through_api(signed_in, fake_photon)
    jamia = pick_masjid(signed_in, "Jamia Omar", "Jamia Omar")
    kma = signed_in.get("/settings").json()["main_masjid"]
    signed_in.put("/settings/jumuah", json={"masjid_ids": [kma["id"], jamia["id"]]})
    signed_in.put("/settings/main-masjid", json={"choice": "home"})
    assert jumuah_names(signed_in) == ["Kanata Muslim Association", "Jamia Omar"]


def test_home_then_a_masjid_adds_it_when_the_list_is_empty(signed_in, fake_photon):
    setup_through_api(signed_in, fake_photon, masjid=None)
    pick_main(signed_in, "Stittsville", "Stittsville Masjid")
    assert jumuah_names(signed_in) == ["Stittsville Masjid"]
