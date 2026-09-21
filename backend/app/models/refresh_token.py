"""Refresh tokens, stored hashed and grouped into families.

A family is one login session. Rotation replaces a token with its successor inside the
same family; presenting a token that has already been rotated means two parties hold
the same secret, and the family is destroyed.
"""

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UtcDateTime, UUIDPrimaryKey


class RefreshToken(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        # Reuse detection looks up by hash on every refresh; family revocation sweeps
        # by family. Both are hot paths on every authenticated session.
        Index("ix_refresh_tokens_family_id", "family_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # SHA-256 of the raw token. A fast hash is correct here, unlike for passwords:
    # the token is 256 bits of randomness, so there is no dictionary to attack and
    # nothing for argon2's work factor to defend against.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # One family per login. Revoking a family logs out that session only, leaving the
    # user's other devices alone.
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    expires_at: Mapped[UtcDateTime] = mapped_column(nullable=False)
    revoked_at: Mapped[UtcDateTime | None] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        return f"<RefreshToken family={self.family_id} revoked={self.revoked_at is not None}>"
