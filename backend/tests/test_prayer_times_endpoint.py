"""Tests for GET /prayer-times. These don't need the database."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.prayer_times import PRAYER_NAMES, AsrMethod, CalculationMethod, calculate_prayer_times
from tests.places import EDMONTON, OTTAWA

client = TestClient(app)

OTTAWA_PARAMS = {"latitude": OTTAWA.latitude, "longitude": OTTAWA.longitude, "date": "2026-10-24"}


def test_returns_all_six_times_with_defaults():
    response = client.get("/prayer-times", params=OTTAWA_PARAMS)

    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-10-24"
    assert body["timezone"] == "America/Toronto"
    assert body["method"] == "isna"
    assert body["asr_method"] == "standard"
    assert list(body["times"]) == list(PRAYER_NAMES)  # in order, Fajr first


def test_times_match_the_calculator():
    response = client.get("/prayer-times", params=OTTAWA_PARAMS)
    expected = calculate_prayer_times(OTTAWA.latitude, OTTAWA.longitude, date(2026, 10, 24))

    for name, prayer in expected.in_order():
        assert datetime.fromisoformat(response.json()["times"][name]["time"]) == prayer.time


def test_every_time_says_where_it_came_from():
    params = {**OTTAWA_PARAMS, "method": "mwl", "asr_method": "hanafi"}
    times = client.get("/prayer-times", params=params).json()["times"]

    for name, prayer in times.items():
        assert prayer["source"] == "calculated", name
        assert prayer["method"] == "mwl", name
        assert prayer["asr_method"] == "hanafi", name
        assert prayer["high_latitude_rule"] is None, name


def test_times_have_the_local_offset():
    # Ottawa is on daylight time (UTC-4) on October 24, 2026.
    fajr = client.get("/prayer-times", params=OTTAWA_PARAMS).json()["times"]["fajr"]["time"]
    assert fajr.endswith("-04:00")


@pytest.mark.parametrize("method", list(CalculationMethod))
def test_each_method_works(method):
    response = client.get("/prayer-times", params={**OTTAWA_PARAMS, "method": method.value})
    assert response.status_code == 200
    assert response.json()["method"] == method.value


def test_hanafi_asr_is_later():
    def asr(asr_method):
        params = {**OTTAWA_PARAMS, "asr_method": asr_method}
        return datetime.fromisoformat(client.get("/prayer-times", params=params).json()["times"]["asr"]["time"])

    assert asr(AsrMethod.HANAFI.value) > asr(AsrMethod.STANDARD.value)


def test_takes_a_time_zone():
    params = {
        "latitude": EDMONTON.latitude,
        "longitude": EDMONTON.longitude,
        "date": "2026-01-15",
        "timezone": EDMONTON.timezone,
    }
    body = client.get("/prayer-times", params=params).json()

    assert body["timezone"] == "America/Edmonton"
    assert body["times"]["dhuhr"]["time"].endswith("-07:00")


def test_shows_the_high_latitude_rule():
    params = {
        "latitude": EDMONTON.latitude,
        "longitude": EDMONTON.longitude,
        "date": "2026-06-21",
        "timezone": EDMONTON.timezone,
    }
    times = client.get("/prayer-times", params=params).json()["times"]

    assert times["fajr"]["high_latitude_rule"] == "seventh_of_the_night"
    assert times["isha"]["high_latitude_rule"] == "seventh_of_the_night"
    assert times["dhuhr"]["high_latitude_rule"] is None


def test_date_defaults_to_today_in_that_time_zone():
    params = {"latitude": OTTAWA.latitude, "longitude": OTTAWA.longitude}
    toronto = ZoneInfo("America/Toronto")
    # Check the date before and after, in case the test runs right at midnight.
    before = datetime.now(toronto).date().isoformat()
    body = client.get("/prayer-times", params=params).json()
    after = datetime.now(toronto).date().isoformat()
    assert body["date"] in (before, after)


@pytest.mark.parametrize(
    "bad_params",
    [
        {"latitude": 91},
        {"latitude": -91},
        {"longitude": 181},
        {"latitude": "abc"},
        {"date": "2026-02-30"},
        {"method": "made_up"},
        {"asr_method": "maliki"},
        {"timezone": "Mars/Olympus_Mons"},
        {"timezone": "../../etc/passwd"},
    ],
)
def test_bad_input_gives_422(bad_params):
    response = client.get("/prayer-times", params={**OTTAWA_PARAMS, **bad_params})
    assert response.status_code == 422


def test_latitude_and_longitude_are_required():
    assert client.get("/prayer-times").status_code == 422
