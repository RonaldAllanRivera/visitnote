"""User accounts."""

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UUIDPrimaryKey
from app.models.enums import NoteFormat, RoleTitle


class User(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)

    # Null for Google-only accounts, which have no password to verify. The login
    # route must treat "no password set" as a failed login rather than as a match.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)

    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Set at onboarding, not registration -- a user who abandons onboarding still has
    # a usable account.
    role_title: Mapped[RoleTitle | None] = mapped_column(
        Enum(RoleTitle, name="role_title", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )
    default_note_format: Mapped[NoteFormat | None] = mapped_column(
        Enum(NoteFormat, name="note_format", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )

    # IANA zone. Every visit this user captures inherits it, and notes render in it.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")

    is_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Demo accounts are rejected on every write path, server side. Hiding the buttons
    # is not a control.
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<User {self.email}>"
