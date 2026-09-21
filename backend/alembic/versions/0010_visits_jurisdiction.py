"""Add jurisdiction to visits.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-21

Copied from the user at creation for the same reason visits.timezone already is: a
user who changes jurisdiction must not change which template resolves for the visits
they captured before the change.

Also fixes forward a naming defect from 0007 and 0009. `base.py`'s `ck` naming
convention is `ck_%(table_name)s_%(constraint_name)s`, which interpolates the name
*we* pass -- unlike `uq`, which interpolates column names and so uses an explicit
`name=` verbatim. Passing `"ck_users_jurisdiction"` as the constraint name therefore
got wrapped again into `ck_users_ck_users_jurisdiction` (and likewise for
note_templates). The constraints work -- `drop_constraint` wraps identically, so the
downgrades in 0007 and 0009 are fine -- but the names contradict the convention's own
stated purpose of producing stable, reviewable names. Renaming in place here rather
than editing already-applied migrations.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "visits",
        sa.Column("jurisdiction", sa.String(length=2), nullable=False, server_default="US"),
    )
    # op.f() marks the name as already-conventionalized, so Alembic does not wrap it
    # a second time the way the bare strings in 0007 and 0009 got wrapped.
    op.create_check_constraint(
        op.f("ck_visits_jurisdiction"), "visits", "jurisdiction IN ('US', 'PH')"
    )
    # Dropped so the service must state it. A server default here would let a missing
    # assignment pass silently as "US".
    op.alter_column("visits", "jurisdiction", server_default=None)

    # Forward fix for the double-prefixing described above.
    op.execute(
        "ALTER TABLE users RENAME CONSTRAINT "
        "ck_users_ck_users_jurisdiction TO ck_users_jurisdiction"
    )
    op.execute(
        "ALTER TABLE note_templates RENAME CONSTRAINT "
        "ck_note_templates_ck_note_templates_jurisdiction TO ck_note_templates_jurisdiction"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE note_templates RENAME CONSTRAINT "
        "ck_note_templates_jurisdiction TO ck_note_templates_ck_note_templates_jurisdiction"
    )
    op.execute(
        "ALTER TABLE users RENAME CONSTRAINT "
        "ck_users_jurisdiction TO ck_users_ck_users_jurisdiction"
    )

    op.drop_constraint(op.f("ck_visits_jurisdiction"), "visits", type_="check")
    op.drop_column("visits", "jurisdiction")
