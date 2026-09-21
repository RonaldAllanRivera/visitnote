"""Shared request dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import InvalidTokenError, decode_access_token
from app.models import User
from app.repositories.users import UserRepository

# auto_error=False so a missing header produces our own 401 with a WWW-Authenticate
# challenge, rather than FastAPI's 403, which is the wrong status for "not
# authenticated" and confuses clients deciding whether to refresh.
_bearer = HTTPBearer(auto_error=False)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Resolve the bearer token to a live user.

    The user is loaded from the database on every request rather than trusted from
    the token's claims. A 15-minute access token would otherwise keep a deactivated
    account working for 15 minutes after it was disabled.
    """
    if credentials is None:
        raise _UNAUTHENTICATED

    try:
        claims = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise _UNAUTHENTICATED from exc

    user = await UserRepository(session).get_by_id(claims.user_id)
    if user is None or not user.is_active:
        raise _UNAUTHENTICATED

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_staff(user: CurrentUser) -> User:
    """Gate for /ops routes.

    Returns 404 rather than 403: a non-staff user should not learn that the operator
    console exists, let alone which paths it occupies.
    """
    if not user.is_staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return user


StaffUser = Annotated[User, Depends(require_staff)]
