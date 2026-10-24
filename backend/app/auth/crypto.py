"""Encrypt Google tokens before they go in the database.

Fernet is AES encryption plus a signature, from the cryptography package.
If someone copies the database without the key from .env, the tokens are
useless to them. The signature means a changed value fails to decrypt
instead of quietly turning into garbage.
"""

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
