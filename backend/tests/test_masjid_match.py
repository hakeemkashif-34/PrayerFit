"""Matching a masjid on the map to my MAWAQIT list (app/masjid_times/match.py).

Plain functions, so no database. Distances are made by moving north from a
listed masjid: 1 degree of latitude is about 111,195 m.
"""

import pytest

from app.masjid_times.match import Listed, match, name_words, names_match

KMA = Listed("id/9793", "Kanata Muslim Association", 45.356128, -75.9283718)
MAC_QIC = Listed("id/14718", "MAC QIC", 45.326052, -75.7198339)
OMA = Listed("id/30768", "Ottawa Main Mosque (OMA)", 45.4014817, -75.7413215)
LIST = [KMA, MAC_QIC, OMA]


def north_of(entry: Listed, metres: float) -> tuple[float, float]:
    return entry.latitude + metres / 111_195, entry.longitude


# ---- The rules ----


def test_within_100_m_is_a_match_even_with_a_different_name():
    found = match(*north_of(MAC_QIC, 60), "Muslim Association of Canada", LIST)
    assert (found.status, found.entry, found.distance_m) == ("linked", MAC_QIC, 60)


def test_a_name_match_at_150_m_is_a_match():
    found = match(*north_of(OMA, 150), "Ottawa Main Mosque", LIST)
    assert (found.status, found.entry, found.distance_m) == ("linked", OMA, 150)


def test_a_different_name_at_150_m_is_no_match():
    assert match(*north_of(OMA, 150), "Ottawa South Mosque", LIST).status == "no match"


def test_no_name_at_150_m_is_no_match():
    # Masjids picked by their address have no name.
    assert match(*north_of(OMA, 150), None, LIST).status == "no match"


def test_too_far_is_no_match_even_with_the_same_name():
    found = match(*north_of(KMA, 250), "Kanata Muslim Association", LIST)
    assert (found.status, found.entry) == ("no match", None)


def test_2_close_listed_masjids_are_unclear_so_neither_is_linked():
    # A 2nd listed masjid 80 m south of KMA. A masjid between them is within 100 m of both.
    neighbour = Listed("id/1", "Kanata Islamic Centre", KMA.latitude - 80 / 111_195, KMA.longitude)
    found = match(*north_of(KMA, 10), "Kanata Muslim Association", [KMA, neighbour])
    assert (found.status, found.entry, found.distance_m) == ("unclear", None, None)
    # Both are listed, nearest first, so /stats and scan-area can show them.
    assert [(c.entry.external_id, c.distance_m) for c in found.candidates] == [("id/9793", 10), ("id/1", 90)]


def test_a_close_one_and_a_same_name_one_are_unclear_too():
    same_name_further = Listed("id/2", "Ottawa Main Mosque", OMA.latitude + 180 / 111_195, OMA.longitude)
    assert match(*north_of(OMA, 20), "Ottawa Main Mosque", [OMA, same_name_further]).status == "unclear"


def test_no_location_is_no_match():
    assert match(None, None, "Kanata Muslim Association", LIST).status == "no match"


def test_an_empty_list_is_no_match():
    assert match(*north_of(KMA, 0), "Kanata Muslim Association", []).status == "no match"


@pytest.mark.parametrize("metres, linked", [(100, True), (101, False)])
def test_100_m_is_the_edge_for_any_name(metres, linked):
    assert (match(*north_of(KMA, metres), "Something Else", LIST).status == "linked") is linked


@pytest.mark.parametrize("metres, linked", [(200, True), (201, False)])
def test_200_m_is_the_edge_for_the_same_name(metres, linked):
    assert (match(*north_of(KMA, metres), "Kanata Muslim Association", LIST).status == "linked") is linked


# ---- Names ----


def test_common_words_and_accents_are_ignored():
    assert name_words("Mosquée de Gatineau - CIO") == ["de", "gatineau", "cio"]
    assert name_words("The Ottawa Main Mosque (OMA)") == ["main", "oma"]


@pytest.mark.parametrize(
    "a, b",
    [
        ("Ottawa Main Mosque (OMA)", "Ottawa Main Mosque"),
        ("Kanata Muslim Association", "Kanata Muslim Association Masjid"),
        ("Jami Omar", "Jamia Omar"),
        ("Mosquee de Gatineau - CIO", "Mosquée de Gatineau"),
        ("East Ottawa Masjid and Community Center", "East Ottawa Masjid & Community Centre"),
    ],
)
def test_names_that_match(a, b):
    assert names_match(a, b)
    assert names_match(b, a)


@pytest.mark.parametrize(
    "a, b",
    [
        ("Barrhaven Islamic Centre", "Jami Omar"),
        ("Ottawa South Mosque", "Ottawa Main Mosque"),
        # Nothing left after the common words, so there's nothing to compare.
        ("Ottawa Mosque", "Masjid"),
        ("Kanata Muslim Association", None),
    ],
)
def test_names_that_dont_match(a, b):
    assert not names_match(a, b)
