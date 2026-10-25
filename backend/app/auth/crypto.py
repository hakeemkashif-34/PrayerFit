"""Encrypt Google tokens and addresses before they go in the database.

Fernet is AES encryption plus a signature, from the cryptography package.
If someone copies the database without the key from .env, the tokens are
useless to them. The signature means a changed value fails to decrypt
instead of quietly turning into garbage.
"""

import hashlib
import hmac
from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_google_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_google_settings().token_encryption_key.encode())


def encrypt(plain_text: str) -> bytes:
    return _fernet().encrypt(plain_text.encode())


def decrypt(token: bytes, max_age_seconds: int | None = None) -> str:
    """Raises cryptography.fernet.InvalidToken if the value was changed or is too old."""
    return _fernet().decrypt(token, ttl=max_age_seconds).decode()


def keyed_hash(plain_text: str) -> str:
    """HMAC-SHA256 with the same secret key.

    Gives the same answer for the same text, so it works as a lookup key,
    but nobody without the key can check a guess like "123 Main St".
    """
    key = get_google_settings().token_encryption_key.encode()
    return hmac.new(key, plain_text.encode(), hashlib.sha256).hexdigest()
