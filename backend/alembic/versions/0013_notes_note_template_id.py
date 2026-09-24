"""Record which template produced each note.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-23

Templates are resolved by (jurisdiction, format) to the active row with the highest
version. Without this column the editor would render a note against whichever
template is active when it is opened, which stops being the one that produced it the
moment a second version is seeded: stored sections with no schema entry, schema
entries with no stored section.

The backfill takes the highest version regardless of is_active, so a template that
has since been deactivated still resolves the notes it produced. A note that cannot
be resolved stops the migration with the pairs named, rather than letting SET NOT
NULL fail on a constraint violation -- remapping or discarding a clinical record is
not a migration's decision to make.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notes", sa.Column("note_template_id", sa.UUID(), nullable=True))

    op.execute(
        """
        UPDATE notes AS n
        SET note_template_id = (
            SELECT t.id
            FROM note_templates AS t
            WHERE t.jurisdiction = v.jurisdiction
              AND t.format = n.format
            ORDER BY t.version DESC
            LIMIT 1
        )
        FROM visits AS v
        WHERE v.id = n.visit_id
        """
    )

    unresolved = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT DISTINCT v.jurisdiction, n.format
                FROM notes AS n
                JOIN visits AS v ON v.id = n.visit_id
                WHERE n.note_template_id IS NULL
                """
            )
        )
        .fetchall()
    )
    if unresolved:
        pairs = ", ".join(f"({row[0]}, {row[1]})" for row in unresolved)
        raise RuntimeError(
            "Cannot backfill notes.note_template_id: no note_templates row exists for "
            f"{pairs}. Seed the missing template before upgrading; remapping a charted "
            "format is not a migration's decision to make."
        )

    op.alter_column("notes", "note_template_id", nullable=False)
    op.create_index(
        op.f("ix_notes_note_template_id"), "notes", ["note_template_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_notes_note_template_id_note_templates"),
        "notes",
        "note_templates",
        ["note_template_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_notes_note_template_id_note_templates"), "notes", type_="foreignkey"
    )
    op.drop_index(op.f("ix_notes_note_template_id"), table_name="notes")
    op.drop_column("notes", "note_template_id")
