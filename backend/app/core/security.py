"""Password hashing and access tokens.

argon2id via argon2-cffi. Chosen over bcrypt because it is memory-hard: an attacker
with a GPU farm gains far less advantage, and bcrypt silently truncates input at 72
bytes, which turns a long passphrase into a shorter one without telling anyone.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings
from app.core.time import utcnow

# Defaults follow the argon2-cffi maintainers' current recommendation. Raising these
# raises login cost for everyone, so they are tuned deliberately rather than guessed.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password, returning False rather than raising on any failure.

    A malformed or truncated stored hash is a data problem, but it must present as a
    failed login -- a 500 on the login route tells an attacker they found something
    interesting.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when a stored hash predates the current cost parameters.

    Cost parameters get raised as hardware improves. Rehashing on next successful
    login upgrades accounts without forcing a password reset.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------

ACCESS_TOKEN_TYPE = "access"


class InvalidTokenError(Exception):
    """Raised for any token that cannot be trusted.

    Deliberately one exception for every failure mode. Distinguishing "expired" from
    "bad signature" in a response tells an attacker which half of a forgery attempt
    worked; the client only ever needs to know it should refresh or re-authenticate.
    """


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    jti: str


def create_access_token(user_id: uuid.UUID, expires_in: timedelta | None = None) -> str:
    settings = get_settings()
    issued_at = utcnow()
    ttl = expires_in or timedelta(seconds=settings.access_token_ttl_seconds)

    return jwt.encode(
        {
            "sub": str(user_id),
            "type": ACCESS_TOKEN_TYPE,
            "iat": issued_at,
            "exp": issued_at + ttl,
            # A per-token id, so a single token can be revoked without invalidating
            # every session the user has.
            "jti": uuid.uuid4().hex,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> AccessTokenClaims:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            # Pinning the algorithm list is what defeats the `alg: none` and
            # HS256-signed-with-the-RSA-public-key attacks. Never pass the algorithm
            # from the token's own header.
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if claims.get("type") != ACCESS_TOKEN_TYPE:
        raise InvalidTokenError("wrong token type")

    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError("subject is not a user id") from exc

    return AccessTokenClaims(user_id=user_id, jti=str(claims["jti"]))
