"""Password hashing (argon2id), session tokens and CSRF tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi defaults (argon2id), as required by section 10.3.
_hasher = PasswordHasher()
# Verifying against this keeps "unknown login" as slow as "wrong password".
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 256


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return False


def new_session_token() -> str:
    """32 random bytes, URL-safe; lives only in the HttpOnly cookie."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token(secret: bytes, session_token: str) -> str:
    """Per-session CSRF value derived from the cookie, so it never needs storage."""
    digest = hmac.new(secret, b"csrf:" + session_token.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def csrf_matches(secret: bytes, session_token: str, supplied: str | None) -> bool:
    if not supplied:
        return False
    return hmac.compare_digest(csrf_token(secret, session_token), supplied)


def throttle_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
