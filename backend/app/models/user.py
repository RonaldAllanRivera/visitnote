"""User accounts."""

from sqlalchemy import Boolean, Enum, String, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UUIDPrimaryKey
from app.models.enums import Jurisdiction, NoteFormat, RoleTitle, jurisdiction_column
from app.models.enums import note_format_column as _format_column


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
    default_note_format: Mapped[NoteFormat | None] = mapped_column(_format_column(), nullable=True)

    # IANA zone. Every visit this user captures inherits it, and notes render in it.
    #
    # `server_default` is set alongside `default` on this and the three boolean
    # columns below because migration 0003 gave each a server-side default.
    # `default` is what lets the ORM insert a row without a round trip; without a
    # matching `server_default`, Alembic sees a default in the database that the
    # model does not declare and proposes dropping it on every autogenerate run.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )

    # Selects the note templates available, the capture modes permitted, the privacy
    # regime named in the UI, and the currency shown. Defaulted from the timezone at
    # onboarding and editable, because the derivation is a default, not a determination.
    jurisdiction: Mapped[Jurisdiction] = mapped_column(
        jurisdiction_column(),
        nullable=False,
        default=Jurisdiction.US,
        server_default="US",
    )

    is_staff: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # Demo accounts are rejected on every write path, server side. Hiding the buttons
    # is not a control.
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"
