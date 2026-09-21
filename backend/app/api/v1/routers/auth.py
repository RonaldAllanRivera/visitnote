"""Authentication routes.

Thin by design: parse, delegate to the service, map the outcome to a status code.
Every security decision lives in the service or the token layer, so it is testable
without an HTTP client and reusable from the CLI.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.core.redis import get_redis
from app.schemas.auth import (
    Credentials,
    GoogleSignInRequest,
    LoginRequest,
    OnboardingRequest,
    RefreshRequest,
    TokenPair,
    UserProfile,
)
from app.services.auth import (
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    UnverifiedGoogleEmailError,
)
from app.services.google import GoogleTokenError, GoogleTokenVerifier, get_google_verifier
from app.services.login_throttle import LoginThrottle
from app.services.refresh_tokens import (
    RefreshTokenReuseError,
    RefreshTokenService,
    UnknownRefreshTokenError,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

# One response for every authentication failure. The client cannot act on the
# distinction and an attacker would use it to enumerate accounts.
_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid email or password",
    headers={"WWW-Authenticate": "Bearer"},
)
_INVALID_REFRESH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired refresh token",
)


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(payload: Credentials, session: SessionDep) -> TokenPair:
    try:
        _, tokens = await AuthService(session).register(payload.email, payload.password)
    except EmailAlreadyRegisteredError as exc:
        # 409 rather than a generic error: the address is visibly taken the moment
        # someone tries to sign up, so hiding it here buys nothing and makes the form
        # unusable.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from exc
    return tokens


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, session: SessionDep) -> TokenPair:
    redis = get_redis()
    throttle = LoginThrottle(redis)
    try:
        locked_for = await throttle.seconds_until_unlocked(payload.email)
        if locked_for:
            # Rejected before the password is even checked. A lockout that still
            # admits a correct guess is decorative.
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed attempts. Try again later.",
                headers={"Retry-After": str(locked_for)},
            )

        service = AuthService(session)
        try:
            user = await service.authenticate(payload.email, payload.password)
        except InvalidCredentialsError as exc:
            await throttle.record_failure(payload.email)
            raise _INVALID_CREDENTIALS from exc

        await throttle.reset(payload.email)
        # Each login opens its own token family, so signing out on one device leaves
        # the user's other devices alone.
        return await service.issue_tokens(user.id)
    finally:
        await redis.aclose()


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, session: SessionDep) -> TokenPair:
    from app.core.config import get_settings
    from app.core.security import create_access_token

    try:
        raw, record = await RefreshTokenService(session).rotate(payload.refresh_token)
    except RefreshTokenReuseError as exc:
        # Logged at warning: a replay is either a stolen token or a client bug, and
        # both are worth seeing in production.
        logger.warning("refresh token reuse detected; family revoked")
        raise _INVALID_REFRESH from exc
    except UnknownRefreshTokenError as exc:
        raise _INVALID_REFRESH from exc

    return TokenPair(
        access_token=create_access_token(record.user_id),
        refresh_token=raw,
        expires_in=get_settings().access_token_ttl_seconds,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest, session: SessionDep) -> Response:
    """Revoke the session.

    Idempotent, and silent about whether the token was real. A client retrying over a
    flaky connection must not see an error, and an attacker must not learn from a
    logout whether a token they hold is valid.
    """
    await RefreshTokenService(session).revoke(payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserProfile)
async def me(user: CurrentUser) -> UserProfile:
    return UserProfile.model_validate(user)


@router.patch("/me", response_model=UserProfile)
async def update_me(
    payload: OnboardingRequest, user: CurrentUser, session: SessionDep
) -> UserProfile:
    updated = await AuthService(session).update_profile(user, payload)
    return UserProfile.model_validate(updated)


@router.post("/google", response_model=TokenPair)
async def google_sign_in(
    payload: GoogleSignInRequest,
    session: SessionDep,
    verifier: Annotated[GoogleTokenVerifier, Depends(get_google_verifier)],
) -> TokenPair:
    try:
        identity = await verifier.verify(payload.id_token)
        _, tokens = await AuthService(session).sign_in_with_google(identity)
    except (GoogleTokenError, UnverifiedGoogleEmailError, InvalidCredentialsError) as exc:
        # One response for all three: a bad token, an unverified address, and a
        # disabled account are equally unauthenticated from the client's side.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not sign in with Google",
        ) from exc
    return tokens
