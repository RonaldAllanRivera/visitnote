"""Google sign-in.

The client obtains an ID token from Google and posts it here. We verify the signature
against Google's published keys, check the audience, and trust only what the token
asserts.

Verification sits behind a Protocol with a fake implementation, matching the
LLMProvider and TranscriptionProvider pattern elsewhere in the codebase. Tests inject
the fake and never reach the network, which is what keeps the auth suite fast and
offline.
"""

from dataclasses import dataclass
from typing import Protocol

import httpx
import jwt

from app.core.config import get_settings

GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"


class GoogleTokenError(Exception):
    """The ID token is missing, malformed, expired, or not intended for us."""


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str | None = None


class GoogleTokenVerifier(Protocol):
    async def verify(self, id_token: str) -> GoogleIdentity: ...


class LiveGoogleTokenVerifier:
    """Verifies against Google's published signing keys."""

    async def verify(self, id_token: str) -> GoogleIdentity:
        settings = get_settings()
        if not settings.google_client_id:
            raise GoogleTokenError("Google sign-in is not configured")

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                jwks = (await client.get(GOOGLE_JWKS_URL)).json()

            # Google rotates signing keys, so the correct key is selected by the
            # token's own `kid`. The signature is still verified against the fetched
            # key set -- nothing from the token header is trusted except which key
            # to look up.
            key_id = jwt.get_unverified_header(id_token).get("kid")
            signing_key = next(
                (k for k in jwt.PyJWKSet.from_dict(jwks).keys if k.key_id == key_id),
                None,
            )
            if signing_key is None:
                raise GoogleTokenError("no matching Google signing key")

            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                # Audience and issuer are the checks that matter most. A validly
                # signed Google token issued for someone else's application would
                # otherwise authenticate here: the token is genuine, just not ours.
                audience=settings.google_client_id,
                issuer=list(GOOGLE_ISSUERS),
                options={"require": ["exp", "iat", "aud", "iss", "sub"]},
            )
        except (jwt.PyJWTError, httpx.HTTPError, ValueError, KeyError) as exc:
            raise GoogleTokenError("could not verify Google ID token") from exc

        email = claims.get("email")
        sub = claims.get("sub")
        if not email or not sub:
            raise GoogleTokenError("token is missing required claims")

        return GoogleIdentity(
            sub=str(sub),
            email=str(email).lower(),
            email_verified=bool(claims.get("email_verified", False)),
            name=claims.get("name"),
        )


def get_google_verifier() -> GoogleTokenVerifier:
    """FastAPI dependency. Overridden with a fake in tests."""
    return LiveGoogleTokenVerifier()
