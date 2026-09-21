"""Care recipients.

A pseudonymous label and nothing else. Users are instructed not to enter full names,
and the schema gives them nowhere to put one -- no name fields, no date of birth, no
address. That limits what a database leak exposes.

It does not make the system PHI-free. The audio of a visit carries the patient's
voice, conditions, medications and often their household; the label only limits the
*database's* exposure.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UUIDPrimaryKey


class Client(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "clients"
    __table_args__ = (
        # Every query is scoped to the owner, and the list view orders by label.
        Index("ix_clients_owner_id_label", "owner_id", "label"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)

    # Deactivated rather than deleted: visits reference this row, and a signed note is
    # a legal record that must stay readable after the assignment ends.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<Client {self.label!r} owner={self.owner_id}>"
