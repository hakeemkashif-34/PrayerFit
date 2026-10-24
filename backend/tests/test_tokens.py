"""Tests for storing and refreshing Google tokens. Google is faked."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DbSession

from app.auth.crypto import decrypt
from app.auth.tokens import get_access_token
from app.google_errors import ReauthRequired
from app.models import GoogleToken, User
from tests.conftest import sign_in


def _tokens(db) -> GoogleToken:
    with DbSession(db) as session:
        return session.scalars(select(GoogleToken)).one()


def _user_id(db):
    with DbSession(db) as session:
        return session.scalars(select(User.id)).one()


def test_tokens_are_stored_encrypted(client, fake_google, db):
    sign_in(client, fake_google)
    access_token = next(iter(fake_google.access_tokens))
    refresh_token = next(iter(fake_google.accounts["user-a"].refresh_tokens))

    row = _tokens(db)

    # The raw column doesn't contain the token, but decrypts back to it.
    assert access_token.encode() not in row.access_token_encrypted
    assert refresh_token.encode() not in row.refresh_token_encrypted
    assert decrypt(row.access_token_encrypted) == access_token
    assert decrypt(row.refresh_token_encrypted) == refresh_token


def test_no_response_contains_a_token(client, fake_google):
    responses = [sign_in(client, fake_google), client.get("/me")]
    tokens = list(fake_google.access_tokens) + list(fake_google.accounts["user-a"].refresh_tokens)

    for response in responses:
        for token in tokens:
            assert token not in response.text
            assert token not in str(response.headers)


def test_valid_access_token_is_used_without_refreshing(client, fake_google, db):
    sign_in(client, fake_google)
    requests_before = len(fake_google.token_requests)

    with DbSession(db) as session, fake_google.client() as http:
        token = get_access_token(session, http, _user_id(db))

    assert token in fake_google.access_tokens
    assert len(fake_google.token_requests) == requests_before


def test_expired_access_token_is_refreshed(client, fake_google, db):
    sign_in(client, fake_google)
    old_token = next(iter(fake_google.access_tokens))
    with DbSession(db) as session:
        session.execute(
            update(GoogleToken).values(access_token_expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        session.commit()

    with DbSession(db) as session, fake_google.client() as http:
        new_token = get_access_token(session, http, _user_id(db))

    assert new_token != old_token
    assert fake_google.token_requests[-1]["grant_type"] == "refresh_token"
    row = _tokens(db)
    assert decrypt(row.access_token_encrypted) == new_token
    assert row.access_token_expires_at > datetime.now(UTC) + timedelta(minutes=50)


def test_dead_refresh_token_asks_to_sign_in_again(client, fake_google, db):
    sign_in(client, fake_google)
    fake_google.kill_refresh_tokens("user-a")

    with DbSession(db) as session, fake_google.client() as http:
        with pytest.raises(ReauthRequired):
            get_access_token(session, http, _user_id(db), force_refresh=True)

    assert _tokens(db).needs_reauth is True
    assert client.get("/me").json()["google_sign_in_needed"] is True


def test_signing_in_again_clears_needs_reauth(client, fake_google, db):
    sign_in(client, fake_google)
    fake_google.kill_refresh_tokens("user-a")
    with DbSession(db) as session, fake_google.client() as http:
        with pytest.raises(ReauthRequired):
            get_access_token(session, http, _user_id(db), force_refresh=True)

    sign_in(client, fake_google)

    assert _tokens(db).needs_reauth is False
    assert client.get("/me").json()["google_sign_in_needed"] is False
