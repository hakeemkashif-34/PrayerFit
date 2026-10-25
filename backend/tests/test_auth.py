"""Tests for Google sign-in, sessions, sign-out, and the Origin check.

Google is faked (see fake_google.py). These need Postgres.
"""

import base64
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.auth.sessions import hash_session_token
from app.models import Session, User
from tests.conftest import new_client, sign_in, start_sign_in


def test_login_sends_the_browser_to_google_with_pkce(client):
    google_query = start_sign_in(client)

    assert google_query["response_type"] == "code"
    assert google_query["code_challenge_method"] == "S256"
    # A SHA-256 hash in base64url is 43 characters.
    assert len(google_query["code_challenge"]) == 43
    assert len(google_query["state"]) >= 32
    assert google_query["access_type"] == "offline"


def test_login_asks_only_for_the_three_scopes(client):
    google_query = start_sign_in(client)

    assert google_query["scope"].split() == [
        "openid",
        "email",
        "https://www.googleapis.com/auth/calendar.app.created",
    ]
    assert "gmail" not in google_query["scope"]
    assert "https://www.googleapis.com/auth/calendar " not in google_query["scope"] + " "


def test_token_request_sends_a_verifier_that_matches_the_challenge(client, fake_google):
    google_query = start_sign_in(client)
    code = fake_google.issue_code("user-a", "a@example.com", google_query["code_challenge"])

    client.get("/auth/google/callback", params={"code": code, "state": google_query["state"]})

    verifier = fake_google.token_requests[-1]["code_verifier"]
    digest = hashlib.sha256(verifier.encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == google_query["code_challenge"]


def _assert_sent_back_with(response, code: str) -> None:
    """A failed sign-in goes back to the website's sign-in screen with a reason code."""
    assert response.status_code == 303
    assert response.headers["location"] == f"/?sign_in_error={code}"


def test_successful_sign_in_creates_the_user_and_goes_to_the_website(client, fake_google, db):
    response = sign_in(client, fake_google, sub="user-a", email="a@example.com")

    assert response.headers["location"] == "/"
    assert client.get("/me").json() == {
        "email": "a@example.com",
        "google_sign_in_needed": False,
        "calendar_access": True,
        "setup_complete": False,
    }
    with DbSession(db) as session:
        assert session.scalars(select(User.email)).all() == ["a@example.com"]


def test_wrong_state_is_rejected(client, fake_google, db):
    google_query = start_sign_in(client)
    code = fake_google.issue_code("user-a", "a@example.com", google_query["code_challenge"])

    response = client.get("/auth/google/callback", params={"code": code, "state": "not-the-state"})

    _assert_sent_back_with(response, "state")
    assert fake_google.token_requests == []  # the code was never used
    with DbSession(db) as session:
        assert session.scalars(select(User)).all() == []


def test_missing_state_is_rejected(client, fake_google):
    google_query = start_sign_in(client)
    code = fake_google.issue_code("user-a", "a@example.com", google_query["code_challenge"])

    response = client.get("/auth/google/callback", params={"code": code})

    _assert_sent_back_with(response, "state")


def test_callback_without_the_flow_cookie_is_rejected(client, fake_google):
    # A different browser that never visited /auth/google/login.
    google_query = start_sign_in(client)
    code = fake_google.issue_code("user-a", "a@example.com", google_query["code_challenge"])

    with new_client() as other_browser:
        response = other_browser.get(
            "/auth/google/callback", params={"code": code, "state": google_query["state"]}
        )

    _assert_sent_back_with(response, "expired")


def test_a_sign_in_flow_can_only_be_used_once(client, fake_google):
    google_query = start_sign_in(client)
    code = fake_google.issue_code("user-a", "a@example.com", google_query["code_challenge"])
    first = client.get("/auth/google/callback", params={"code": code, "state": google_query["state"]})
    assert first.status_code == 303
    assert client.cookies.get("oauth_flow") is None  # cleared after the callback

    # Same browser, same state, and a fresh code: refused, because the flow is gone.
    code_again = fake_google.issue_code("user-a", "a@example.com", google_query["code_challenge"])
    second = client.get(
        "/auth/google/callback", params={"code": code_again, "state": google_query["state"]}
    )
    _assert_sent_back_with(second, "expired")


def test_failed_callback_also_clears_the_flow(client, fake_google):
    google_query = start_sign_in(client)
    code = fake_google.issue_code("user-a", "a@example.com", google_query["code_challenge"])

    client.get("/auth/google/callback", params={"code": code, "state": "wrong"})
    retry = client.get("/auth/google/callback", params={"code": code, "state": google_query["state"]})

    assert client.cookies.get("oauth_flow") is None
    _assert_sent_back_with(retry, "expired")


def test_cancelled_sign_in_is_rejected_and_clears_the_flow(client):
    start_sign_in(client)

    response = client.get("/auth/google/callback", params={"error": "access_denied"})

    _assert_sent_back_with(response, "cancelled")
    assert client.cookies.get("oauth_flow") is None


def test_session_cookie_is_http_only_and_only_its_hash_is_saved(client, fake_google, db):
    response = sign_in(client, fake_google)

    session_cookie = next(
        header for header in response.headers.get_list("set-cookie") if header.startswith("session=")
    )
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie

    token = client.cookies.get("session")
    with DbSession(db) as session:
        saved = session.scalars(select(Session.token_hash)).all()
    assert saved == [hash_session_token(token)]
    assert token not in saved


def test_me_needs_a_session(client):
    response = client.get("/me")

    assert response.status_code == 401
    assert response.json()["detail"]["login_url"] == "/auth/google/login"
    # The website uses this to show "Sign in with Google".
    assert response.json()["detail"]["reason"] == "not_signed_in"


def test_made_up_session_cookie_is_rejected(client):
    client.cookies.set("session", "made-up-value")

    assert client.get("/me").status_code == 401


def test_logout_ends_the_session(client, fake_google, db):
    sign_in(client, fake_google)
    token = client.cookies.get("session")

    response = client.post("/auth/logout")

    assert response.status_code == 204
    assert client.get("/me").status_code == 401
    # Even if someone kept a copy of the cookie, it no longer works.
    client.cookies.set("session", token)
    assert client.get("/me").status_code == 401
    with DbSession(db) as session:
        assert session.scalars(select(Session)).all() == []


def test_post_from_another_site_is_refused(client, fake_google):
    sign_in(client, fake_google)

    response = client.post("/auth/logout", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403
    assert client.get("/me").status_code == 200  # still signed in


def test_post_without_an_origin_is_refused(db):
    with new_client() as browser:
        del browser.headers["Origin"]
        response = browser.post("/auth/logout")

    assert response.status_code == 403


def test_signing_in_again_reuses_the_same_user(client, fake_google, db):
    sign_in(client, fake_google, sub="user-a", email="a@example.com")
    sign_in(client, fake_google, sub="user-a", email="new-a@example.com")

    with DbSession(db) as session:
        assert session.scalars(select(User.email)).all() == ["new-a@example.com"]


def test_unticked_calendar_access_is_reported(client, fake_google):
    sign_in(client, fake_google, scopes="openid https://www.googleapis.com/auth/userinfo.email")

    assert client.get("/me").json()["calendar_access"] is False
