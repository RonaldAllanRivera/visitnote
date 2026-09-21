"""Authentication business rules.

Routers translate these outcomes into HTTP. The rules themselves know nothing about
requests, which is what lets the CLI and the seed tooling reuse them.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.jurisdiction import jurisdiction_for_timezone
from app.core.security import create_access_token, hash_password, needs_rehash, verify_password
from app.models import User
from app.repositories.note_templates import NoteTemplateRepository
from app.repositories.users import UserRepository
from app.schemas.auth import OnboardingRequest, TokenPair, default_format_for
from app.services.google import GoogleIdentity
from app.services.refresh_tokens import RefreshTokenService

# A hash of a value no one can supply, used to burn the same CPU time on a login for
# an address that does not exist as on one that does. Without it, response time tells
# an attacker which addresses are registered.
_DUMMY_HASH = hash_password("timing-equalisation-placeholder")


class EmailAlreadyRegisteredError(Exception):
    """Signup collided with an existing account."""


class UnverifiedGoogleEmailError(Exception):
    """Google has not confirmed the user controls this address.

    Linking or creating an account on an unverified address would let anyone who can
    assert an address take over the account that already owns it.
    """


class InvalidCredentialsError(Exception):
    """Wrong password, unknown address, disabled account, or no password set.

    One exception for every case on purpose: the caller must not be able to tell them
    apart, because the client cannot act differently and an attacker would.
    """


@dataclass(slots=True)
class AuthService:
    session: AsyncSession

    @property
    def users(self) -> UserRepository:
        return UserRepository(self.session)

    @property
    def refresh_tokens(self) -> RefreshTokenService:
        return RefreshTokenService(self.session)

    async def register(self, email: str, password: str) -> tuple[User, TokenPair]:
        if await self.users.exists_by_email(email):
            raise EmailAlreadyRegisteredError(email)

        user = User(email=email.lower(), password_hash=hash_password(password))
        self.users.add(user)
        await self.session.commit()
        await self.session.refresh(user)

        return user, await self.issue_tokens(user.id)

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.users.get_by_email(email)

        if user is None or user.password_hash is None:
            # Still verify, against a fixed hash, so an unknown address costs the same
            # wall-clock time as a known one. A Google-only account has no password
            # and takes this path too.
            verify_password(password, _DUMMY_HASH)
            raise InvalidCredentialsError

        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError

        if not user.is_active:
            raise InvalidCredentialsError

        # Cost parameters rise over time. Upgrading on a successful login keeps old
        # accounts current without a forced password reset.
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
            await self.session.commit()

        return user

    async def issue_tokens(self, user_id: uuid.UUID) -> TokenPair:
        settings = get_settings()
        raw_refresh, _ = await self.refresh_tokens.issue(user_id)
        return TokenPair(
            access_token=create_access_token(user_id),
            refresh_token=raw_refresh,
            expires_in=settings.access_token_ttl_seconds,
        )

    async def update_profile(self, user: User, payload: OnboardingRequest) -> User:
        """Apply an onboarding update.

        Fields are assigned by name, never by iterating the payload, so adding a
        column to User can never accidentally make it client-writable.
        """
        if payload.full_name is not None:
            user.full_name = payload.full_name
        if payload.timezone is not None:
            user.timezone = payload.timezone
            # Derive unless the user says otherwise, so onboarding asks one question
            # instead of two. The explicit field below still wins.
            if payload.jurisdiction is None:
                user.jurisdiction = jurisdiction_for_timezone(payload.timezone)
        if payload.jurisdiction is not None:
            user.jurisdiction = payload.jurisdiction
        if payload.role_title is not None:
            user.role_title = payload.role_title
            # Derive from role AND jurisdiction unless the user overrides it. Read
            # user.jurisdiction, not the payload's -- the timezone branch above has
            # already applied any change, so this sees the final value.
            if payload.default_note_format is None:
                user.default_note_format = default_format_for(user.jurisdiction, payload.role_title)
        if payload.default_note_format is not None:
            user.default_note_format = payload.default_note_format

        # A jurisdiction change can strand the user's format: a PH RN defaults to
        # fdar, and there is no (US, fdar) template. Left alone, their next visit
        # would resolve to None and fail in the pipeline minutes later, for a mistake
        # made here. Checked against note_templates rather than a hardcoded map, so
        # seeding a PH shift_note later makes it valid with no code change.
        if user.role_title is not None and user.default_note_format is not None:
            templates = NoteTemplateRepository(self.session)
            if await templates.get_active(user.jurisdiction, user.default_note_format) is None:
                user.default_note_format = default_format_for(user.jurisdiction, user.role_title)

        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def sign_in_with_google(self, identity: GoogleIdentity) -> tuple[User, TokenPair]:
        """Sign in, link, or create -- in that order of preference."""
        if not identity.email_verified:
            raise UnverifiedGoogleEmailError(identity.email)

        existing = await self.users.get_by_email(identity.email)

        if existing is not None:
            if not existing.is_active:
                raise InvalidCredentialsError
            # Link on first Google sign-in for an address that already has a
            # password account. Safe only because Google verified the address.
            if existing.google_sub is None:
                existing.google_sub = identity.sub
                await self.session.commit()
            return existing, await self.issue_tokens(existing.id)

        # No password hash: this account has no password to guess, and the password
        # login route treats "no password set" as a failed login.
        user = User(
            email=identity.email.lower(),
            google_sub=identity.sub,
            full_name=identity.name,
            password_hash=None,
        )
        self.users.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user, await self.issue_tokens(user.id)
