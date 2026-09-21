"""Add jurisdiction to users.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-21

CHAR(2) with a check constraint rather than a Postgres ENUM. The set of jurisdictions
grows, and ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("jurisdiction", sa.String(length=2), nullable=False, server_default="US"),
    )
    op.create_check_constraint("ck_users_jurisdiction", "users", "jurisdiction IN ('US', 'PH')")


def downgrade() -> None:
    op.drop_constraint("ck_users_jurisdiction", "users", type_="check")
    op.drop_column("users", "jurisdiction")
