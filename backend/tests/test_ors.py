"""The OpenRouteService adapter and saved drive times, against a fake ORS."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.drive_times import drive_seconds
from app.geo.ors import NO_ROUTE, Route, drive_time
from app.models import UserDriveTime
from tests.masjid_helpers import add_masjid, add_user, masjid_id

NOW = datetime(2026, 10, 25, 17, 0, tzinfo=UTC)
HOME = (45.308812, -75.898734)
MASJID = (45.318791, -75.886512)


def test_success_sends_rounded_coordinates_and_the_key_in_a_header(db, http, fake_ors, ors_key):
    with Session(db) as session:
        assert drive_time(session, http, HOME, MASJID) == Route(seconds=840)
    request = fake_ors.requests[0]
    assert fake_ors.bodies[0] == {"coordinates": [[-75.899, 45.309], [-75.887, 45.319]]}
    assert request.headers["authorization"] == ors_key
    assert ors_key not in str(request.url)
    assert "45.3088" not in request.content.decode()


def test_an_empty_key_skips_quietly(db, http, fake_ors):
    with Session(db) as session:
        assert drive_time(session, http, HOME, MASJID) is None
    assert fake_ors.requests == []


@pytest.mark.parametrize("failure", ["timeout", 429, 500])
def test_timeouts_and_errors_give_no_drive_time(db, http, fake_ors, ors_key, failure, caplog):
    fake_ors.failure = failure
    with caplog.at_level(logging.WARNING), Session(db) as session:
        assert drive_time(session, http, HOME, MASJID) is None
    assert "OpenRouteService failed" in caplog.text
    assert "45.3" not in caplog.text and "75.8" not in caplog.text


def test_no_route(db, http, fake_ors, ors_key):
    fake_ors.failure = "no_route"
    with Session(db) as session:
        assert drive_time(session, http, HOME, MASJID) is NO_ROUTE


@pytest.fixture
def user_and_masjid(db, fake_google):
    user = add_user(fake_google, db, "user-a", masjid_name="KMA", at_masjid={0: {"isha"}})
    return user, masjid_id(db, "KMA")


def seconds(db, http, user, masjids, now=NOW, home=HOME):
    from app.models import Masjid

    with Session(db, expire_on_commit=False) as session:
        rows = [session.get(Masjid, m) for m in masjids]
        return drive_seconds(session, http, user, home, rows, now)


def test_drive_times_are_saved_and_reused(db, http, fake_ors, ors_key, user_and_masjid):
    user, kma = user_and_masjid
    assert seconds(db, http, user, [kma]) == {kma: 840}
    assert seconds(db, http, user, [kma], NOW + timedelta(days=29)) == {kma: 840}
    assert len(fake_ors.requests) == 1
    with Session(db) as session:
        row = session.get(UserDriveTime, (user, kma))
        # Only a keyed hash of the route, never the points.
        assert len(row.route_key) == 64
        assert row.seconds == 840 and row.status == "ok"


def test_asked_again_after_30_days(db, http, fake_ors, ors_key, user_and_masjid):
    user, kma = user_and_masjid
    seconds(db, http, user, [kma])
    fake_ors.seconds = 900
    assert seconds(db, http, user, [kma], NOW + timedelta(days=30)) == {kma: 900}
    assert len(fake_ors.requests) == 2


def test_asked_again_when_home_moves(db, http, fake_ors, ors_key, user_and_masjid):
    user, kma = user_and_masjid
    seconds(db, http, user, [kma])
    seconds(db, http, user, [kma], home=(45.35, -75.75))
    assert len(fake_ors.requests) == 2


def test_no_route_is_saved_too(db, http, fake_ors, ors_key, user_and_masjid):
    user, kma = user_and_masjid
    fake_ors.failure = "no_route"
    assert seconds(db, http, user, [kma]) == {kma: None}
    assert seconds(db, http, user, [kma]) == {kma: None}
    assert len(fake_ors.requests) == 1


def test_a_failure_keeps_the_old_answer_for_the_same_route(db, http, fake_ors, ors_key, user_and_masjid):
    user, kma = user_and_masjid
    seconds(db, http, user, [kma])
    fake_ors.failure = 429
    assert seconds(db, http, user, [kma], NOW + timedelta(days=31)) == {kma: 840}


def test_one_call_per_masjid(db, http, fake_ors, ors_key, user_and_masjid):
    user, kma = user_and_masjid
    other = add_masjid(db, "Jamia Omar", 45.4, -75.7)
    assert seconds(db, http, user, [kma, other]) == {kma: 840, other: 840}
    assert len(fake_ors.requests) == 2
