"""Repoint the two US templates onto v2 prompts and declare the identifier flag.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-22

0011 declared `PATIENT_IDENTIFIER_DETECTED` on the two PH rows only, because
`shift_note_v1` and `soapie_v1` are immutable prompt modules carrying no
name-redaction instruction -- declaring the code there would have put it in the
generation schema with nothing ever asking the model to raise it, which is worse
than not declaring it at all. `shift_note_v2` and `soapie_v2` now exist and carry
that instruction, so this migration does the two things 0011 deferred, to the same
two rows (`jurisdiction = 'US'`, `version = 1`):

- repoint `prompt_version` from `shift_note_v1` / `soapie_v1` to `shift_note_v2` /
  `soapie_v2`
- append `PATIENT_IDENTIFIER_DETECTED` (critical) to `flag_schema -> 'flags'`, using
  the same description text the PH rows already carry for it, so all four templates
  agree on what the flag means

The row's `prompt_version` is a plain string, not a foreign key, so this is a data
update rather than a schema change -- and it does not touch `section_schema`, which
is unaffected by either change.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Identical to 0011's _PATIENT_IDENTIFIER_DESCRIPTION. Duplicated rather than
# imported -- migrations are independent, frozen snapshots, and importing from a
# sibling revision module would tie this one's behaviour to that file never
# changing. All four templates carrying the same literal text is what matters, and
# a test (test_note_templates.py) asserts the four descriptions agree.
_PATIENT_IDENTIFIER_DESCRIPTION = (
    "The transcript names the patient; the name was stripped from the note rather "
    "than carried into it."
)

_PROMPT_VERSIONS_V2 = {
    "shift_note": "shift_note_v2",
    "soapie": "soapie_v2",
}
_PROMPT_VERSIONS_V1 = {
    "shift_note": "shift_note_v1",
    "soapie": "soapie_v1",
}


def upgrade() -> None:
    connection = op.get_bind()

    for note_format, prompt_version in _PROMPT_VERSIONS_V2.items():
        connection.execute(
            sa.text(
                """
                UPDATE note_templates
                SET prompt_version = :prompt_version
                WHERE jurisdiction = 'US' AND format = :format AND version = 1
                """
            ),
            {"prompt_version": prompt_version, "format": note_format},
        )

    # Same jsonb_set-append shape 0011 originally used for this backfill (see that
    # file's git history): read the existing array out, concatenate the one new
    # flag object, and write the result back. `||` on two jsonb arrays concatenates
    # them rather than merging by key, which is exactly "append" here.
    connection.execute(
        sa.text(
            """
            UPDATE note_templates
            SET flag_schema = jsonb_set(
                flag_schema,
                '{flags}',
                (flag_schema -> 'flags') || CAST(:new_flag AS jsonb)
            )
            WHERE jurisdiction = 'US' AND format IN ('shift_note', 'soapie') AND version = 1
            """
        ),
        {
            "new_flag": json.dumps(
                {
                    "code": "PATIENT_IDENTIFIER_DETECTED",
                    "severity": "critical",
                    "description": _PATIENT_IDENTIFIER_DESCRIPTION,
                }
            )
        },
    )


def downgrade() -> None:
    connection = op.get_bind()

    # Reverse the append by set difference, not by overwriting with a fixed array --
    # an overwrite would silently discard any other flag added to these rows since
    # this migration ran. Same shape 0011 originally used for the same backfill.
    connection.execute(
        sa.text(
            """
            UPDATE note_templates
            SET flag_schema = jsonb_set(
                flag_schema,
                '{flags}',
                (
                    SELECT COALESCE(jsonb_agg(flag), '[]'::jsonb)
                    FROM jsonb_array_elements(flag_schema -> 'flags') AS flag
                    WHERE flag ->> 'code' != 'PATIENT_IDENTIFIER_DETECTED'
                )
            )
            WHERE jurisdiction = 'US' AND format IN ('shift_note', 'soapie') AND version = 1
            """
        )
    )

    for note_format, prompt_version in _PROMPT_VERSIONS_V1.items():
        connection.execute(
            sa.text(
                """
                UPDATE note_templates
                SET prompt_version = :prompt_version
                WHERE jurisdiction = 'US' AND format = :format AND version = 1
                """
            ),
            {"prompt_version": prompt_version, "format": note_format},
        )
