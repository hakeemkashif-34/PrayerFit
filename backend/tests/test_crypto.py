"""Tests for token encryption. These don't need the database."""

import pytest
from cryptography.fernet import InvalidToken

from app.auth.crypto import decrypt, encrypt


def test_round_trip():
    assert decrypt(encrypt("ya29.secret-access-token")) == "ya29.secret-access-token"


def test_encrypted_value_does_not_contain_the_token():
    assert b"ya29.secret-access-token" not in encrypt("ya29.secret-access-token")


def test_same_token_encrypts_differently_each_time():
    # Fernet adds a random IV, so two copies of a token can't be matched up.
    assert encrypt("same") != encrypt("same")


def test_changed_value_fails_to_decrypt():
    encrypted = bytearray(encrypt("ya29.secret-access-token"))
    encrypted[20] ^= 1  # flip one bit

    with pytest.raises(InvalidToken):
        decrypt(bytes(encrypted))
