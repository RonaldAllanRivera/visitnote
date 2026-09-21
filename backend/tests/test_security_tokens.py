"""Access token issuing and verification."""

import uuid
from datetime import timedelta

import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
)


def test_decoding_a_token_returns_the_subject() -> None:
    user_id = uuid.uuid4()
    assert decode_access_token(create_access_token(user_id)).user_id == user_id


def test_rejects_an_expired_token() -> None:
    token = create_access_token(uuid.uuid4(), expires_in=timedelta(seconds=-1))
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_rejects_a_tampered_payload() -> None:
    header, payload, signature = create_access_token(uuid.uuid4()).split(".")
    with pytest.raises(InvalidTokenError):
        decode_access_token(f"{header}.{payload}x.{signature}")


def test_rejects_a_token_signed_with_another_secret() -> None:
    import jwt

    # 32+ bytes: PyJWT refuses shorter HMAC keys, and our own settings enforce the
    # same minimum. A short key here would test key length, not signature validation.
    other_secret = "a-different-secret-of-sufficient-length-32+"
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access"}, other_secret, algorithm="HS256"
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(forged)


def test_rejects_a_refresh_token_presented_as_an_access_token() -> None:
    """Token confusion: a long-lived refresh token must never authorise a request."""
    import jwt

    from app.core.config import get_settings

    settings = get_settings()
    refresh_shaped = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(refresh_shaped)


def test_rejects_a_token_with_the_none_algorithm() -> None:
    """The classic JWT attack: strip the signature and claim the algorithm is 'none'."""
    import jwt

    unsigned = jwt.encode({"sub": str(uuid.uuid4()), "type": "access"}, key="", algorithm="none")
    with pytest.raises(InvalidTokenError):
        decode_access_token(unsigned)


def test_token_carries_no_authorisation_claims() -> None:
    """Staff status and entitlements are read from the database on every request.

    Embedding them would mean a revoked staff flag stays valid until the token
    expires, which is exactly the window an attacker wants.
    """
    import jwt

    claims = jwt.decode(create_access_token(uuid.uuid4()), options={"verify_signature": False})
    assert not {"is_staff", "agency_id", "plan", "entitlements", "scopes"} & claims.keys()


def test_each_token_has_a_unique_identifier() -> None:
    """A jti gives us a handle for per-token revocation later."""
    import jwt

    user_id = uuid.uuid4()
    first = jwt.decode(create_access_token(user_id), options={"verify_signature": False})
    second = jwt.decode(create_access_token(user_id), options={"verify_signature": False})
    assert first["jti"] != second["jti"]
