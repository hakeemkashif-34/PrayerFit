"""One user can never see or change another user's data."""

from datetime import date

from tests.conftest import new_client, sign_in
from tests.setup_helpers import save_setup


def test_users_only_see_their_own_events(fake_google, set_today, db):
    set_today(date(2026, 10, 24))
    with new_client() as alice, new_client() as bob:
        sign_in(alice, fake_google, sub="alice", email="alice@example.com")
        sign_in(bob, fake_google, sub="bob", email="bob@example.com")
        save_setup(db, sub="alice")
        save_setup(db, sub="bob")

        alice_ids = {e["app_event_id"] for e in alice.post("/prayers/today").json()["events"]}

        # Bob hasn't added anything, so he sees nothing, not Alice's events.
        assert bob.get("/prayers/today/events").json() == []
        assert bob.get("/me").json()["email"] == "bob@example.com"

        bob_ids = {e["app_event_id"] for e in bob.post("/prayers/today").json()["events"]}
        assert alice_ids.isdisjoint(bob_ids)
        assert {e["app_event_id"] for e in alice.get("/prayers/today/events").json()} == alice_ids
        assert {e["app_event_id"] for e in bob.get("/prayers/today/events").json()} == bob_ids


def test_each_user_gets_their_own_calendar_with_their_own_token(fake_google, set_today, db):
    set_today(date(2026, 10, 24))
    with new_client() as alice, new_client() as bob:
        sign_in(alice, fake_google, sub="alice", email="alice@example.com")
        sign_in(bob, fake_google, sub="bob", email="bob@example.com")
        save_setup(db, sub="alice")
        save_setup(db, sub="bob")
        alice.post("/prayers/today")
        requests_before_bob = len(fake_google.requests)
        bob.post("/prayers/today")

    alice_calendar = fake_google.calendars_of("alice")[0]
    bob_calendar = fake_google.calendars_of("bob")[0]
    assert alice_calendar.id != bob_calendar.id
    assert len(fake_google.live_events(alice_calendar.id)) == 5
    assert len(fake_google.live_events(bob_calendar.id)) == 5

    # Every request during Bob's run used Bob's token and only touched Bob's calendar.
    for request in fake_google.requests[requests_before_bob:]:
        assert request.sub == "bob"
        assert alice_calendar.id not in request.path


def test_signing_out_one_user_leaves_the_other_signed_in(fake_google, db):
    with new_client() as alice, new_client() as bob:
        sign_in(alice, fake_google, sub="alice", email="alice@example.com")
        sign_in(bob, fake_google, sub="bob", email="bob@example.com")

        alice.post("/auth/logout")

        assert alice.get("/me").status_code == 401
        assert bob.get("/me").status_code == 200
