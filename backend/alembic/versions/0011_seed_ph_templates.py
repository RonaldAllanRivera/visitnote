"""Seed the PH SOAPIE and PH FDAR note templates.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-21

Seeded as a data migration, in the same style as `0002_seed_note_templates.py`, so
every environment -- local, CI, staging, production -- starts with identical template
definitions. This is the row-based proof of the project's central claim: one pipeline,
four note formats, two regulatory regimes, because a format is data rather than code.

Two differences from 0002 beyond the new rows themselves:

- The INSERT carries `jurisdiction` and `requires_diarization`, and no longer casts
  `format` to the `note_format` ENUM -- migration 0008 dropped that type, and the
  column is `VARCHAR(32)` now.
- This migration also backfills `PATIENT_IDENTIFIER_DETECTED` onto the two existing
  US rows. The flag is new with this phase and applies to every format, PH and US
  alike (a nurse speaking a patient's name aloud is a risk regardless of
  jurisdiction), so seeding it only on the two new rows would leave the US templates
  permanently behind the spec they are supposed to satisfy.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sections(*items: tuple[str, str, str] | dict[str, object]) -> dict[str, object]:
    """Ordered section definitions, same shape as 0002's helper.

    Extended to also accept an already-built section dict (from `_repeating_section`
    below) alongside the plain (key, label, description) tuples every flat section
    uses, so PH FDAR's one repeating section can sit in the same ordered list as its
    five flat ones without hand-writing any dict inline.
    """
    sections: list[dict[str, object]] = []
    for i, item in enumerate(items):
        if isinstance(item, dict):
            sections.append({**item, "order": i + 1})
        else:
            key, label, description = item
            sections.append(
                {"key": key, "label": label, "order": i + 1, "description": description}
            )
    return {"sections": sections}


def _repeating_section(
    key: str, label: str, description: str, *fields: tuple[str, str, str]
) -> dict[str, object]:
    """A section whose entries repeat -- FDAR's one F-D-A-R block per focus.

    A shift charts several foci, so `focus_entries` cannot be a single prose block:
    MISSING_RESPONSE (an Action with no documented Response) has to be evaluable per
    entry, not against one flattened paragraph. `order` is assigned by `_sections`
    above, positionally, like every other section; only the nested `fields` are
    ordered here.
    """
    return {
        "key": key,
        "label": label,
        "description": description,
        "repeating": True,
        "fields": [
            {"key": fkey, "label": flabel, "order": i + 1, "description": fdescription}
            for i, (fkey, flabel, fdescription) in enumerate(fields)
        ],
    }


def _flags(*items: tuple[str, str, str]) -> dict[str, object]:
    return {
        "flags": [
            {"code": code, "severity": severity, "description": description}
            for code, severity, description in items
        ]
    }


# Every template in the product uses a pseudonymous label, but a nurse speaking aloud
# still says the patient's name -- that is how people talk. Without this flag the
# product would quietly transcribe identifiers into stored notes, which is exactly
# the exposure the pseudonymous label exists to avoid. One shared description string
# so the four templates that carry it agree on what it means.
_PATIENT_IDENTIFIER_DESCRIPTION = (
    "The transcript names the patient; the name was stripped from the note rather "
    "than carried into it."
)

# PH SOAPIE carries nine of US SOAPIE's ten sections -- homebound status has no
# Philippine analogue -- with identical text for every section that is retained, so
# the two templates read as the same format rather than independently drifting copies.
PH_SOAPIE_SECTIONS = _sections(
    (
        "visit_details",
        "Visit details",
        "Patient label, visit date, exact arrival time, exact departure time.",
    ),
    (
        "subjective",
        "Subjective",
        "Patient or caregiver reported status, symptoms, concerns. Patient's own words quoted.",
    ),
    (
        "objective",
        "Objective",
        "Vital signs, exam findings, measurable data such as wound dimensions, stage and "
        "drainage character, home environment and safety observations.",
    ),
    (
        "assessment",
        "Assessment",
        "Clinical assessment tied to diagnosis; progress or change since the last visit.",
    ),
    (
        "plan",
        "Plan",
        "Plan for the next visit with rationale, discharge trajectory, ongoing need for "
        "skilled care.",
    ),
    (
        "intervention",
        "Intervention",
        "Skilled services performed and why each required a licensed nurse.",
    ),
    (
        "evaluation",
        "Evaluation",
        "Patient or caregiver response to interventions, measurable where possible; "
        "progress toward plan-of-care goals.",
    ),
    (
        "coordination_of_care",
        "Coordination of care",
        "Physician, PT, OT, SLP, MSW, aide or family communication; new orders.",
    ),
    (
        "medication_review",
        "Medication review",
        "Medications reviewed or reconciled this visit, plus any issues identified.",
    ),
)

# Drops MISSING_HOMEBOUND, MISSING_NECESSITY_RATIONALE and MISSING_POC_LINK -- CMS
# home-health survey requirements with no PhilHealth analogue -- and
# UNATTRIBUTED_STATEMENT, which has no path to firing against a single-speaker
# dictated recap (ph_soapie_v1.py carries the explicit prompt override; see its
# docstring). Everything else from US SOAPIE is retained verbatim, plus
# PATIENT_IDENTIFIER_DETECTED, new with this phase and universal to every format.
PH_SOAPIE_FLAGS = _flags(
    ("MISSING_VITALS", "critical", "No vital signs documented for a skilled nursing visit."),
    ("MISSING_VISIT_TIMES", "critical", "Arrival or departure time was not stated."),
    (
        "MISSING_SKILLED_SERVICE",
        "critical",
        "No skilled service documented, which does not support a billable skilled visit.",
    ),
    (
        "UNREPORTED_CHANGE",
        "critical",
        "Transcript indicates a clinical change that is not documented in the note.",
    ),
    ("PATIENT_IDENTIFIER_DETECTED", "critical", _PATIENT_IDENTIFIER_DESCRIPTION),
    ("MISSING_RESPONSE", "warning", "No patient response to the interventions performed."),
    ("MISSING_MED_REVIEW", "warning", "No medication review or reconciliation documented."),
    ("MISSING_NEXT_VISIT_PLAN", "warning", "No plan stated for the next visit."),
    (
        "MISSING_COORDINATION",
        "warning",
        "Transcript indicates a reportable change but no physician or team communication "
        "is documented.",
    ),
    (
        "VAGUE_LANGUAGE",
        "warning",
        "The audio contained only vague phrasing where measurable data is required.",
    ),
    (
        "MISSING_EDUCATION_RESPONSE",
        "info",
        "Teaching was documented without the learner's response or return demonstration.",
    ),
    ("MISSING_PAIN_ASSESSMENT", "info", "No pain assessment documented."),
)

# Focus-Data-Action-Response: the charting format taught in Philippine nursing
# programmes. A shift produces one F-D-A-R entry per focus, hence `focus_entries`
# below being the one repeating section this product has.
PH_FDAR_SECTIONS = _sections(
    (
        "shift_details",
        "Shift details",
        "Unit or ward, bed label, shift (AM/PM/Night), date, time in, time out.",
    ),
    _repeating_section(
        "focus_entries",
        "Focus entries",
        "One F-D-A-R entry per nursing focus charted this shift.",
        ("focus", "Focus", "The nursing problem, concern, or event being charted."),
        ("data", "Data", "Subjective and objective findings supporting the focus, with times."),
        ("action", "Action", "Nursing interventions performed for the focus, with times."),
        ("response", "Response", "Patient response and reassessment outcome."),
    ),
    ("medications_administered", "Medications administered", "Drug, dose, route, site, time."),
    (
        "intake_output",
        "Intake and output",
        "Fluid or nutritional intake and output recorded for the shift.",
    ),
    (
        "doctors_orders",
        "Doctor's orders",
        "Orders received this shift and confirmation each was carried out.",
    ),
    ("endorsement", "Endorsement", "Carry-forward items for the next shift."),
)

# Exactly the spec's PH FDAR flag list. Does not include UNATTRIBUTED_STATEMENT, for
# the same reason PH SOAPIE's does not -- see ph_fdar_v1.py's docstring.
# MISSING_RESPONSE is critical here (not the warning severity it carries in SOAPIE):
# an Action with no documented Response is the deficiency FDAR charting exists to
# surface, and a generation that invents one to close the gap defeats the format.
PH_FDAR_FLAGS = _flags(
    ("MISSING_SHIFT_TIMES", "critical", "Start or end time was not stated."),
    ("MISSING_FOCUS", "critical", "Data, action, or response was charted with no focus named."),
    (
        "MISSING_RESPONSE",
        "critical",
        "An action was documented with no patient response recorded anywhere in the "
        "transcript -- the classic FDAR deficiency.",
    ),
    (
        "MED_WITHOUT_ROUTE_OR_TIME",
        "critical",
        "A medication administration was recorded without its route or the time it was given.",
    ),
    (
        "PRN_WITHOUT_RESPONSE",
        "critical",
        "A PRN medication was given with no documented patient response.",
    ),
    (
        "UNREPORTED_CHANGE",
        "critical",
        "Transcript indicates deterioration with no escalation documented.",
    ),
    ("PATIENT_IDENTIFIER_DETECTED", "critical", _PATIENT_IDENTIFIER_DESCRIPTION),
    ("MISSING_VITALS_TIME", "warning", "Vital signs were stated without the time they were taken."),
    ("MISSING_INTAKE_OUTPUT", "warning", "No intake or output documented for the shift."),
    (
        "PAIN_NOT_REASSESSED",
        "warning",
        "Pain was documented with no reassessment after an intervention.",
    ),
    (
        "ORDER_NOT_ACKNOWLEDGED",
        "warning",
        "A doctor's order was mentioned with no acknowledgement that it was carried out.",
    ),
    ("MISSING_ENDORSEMENT", "warning", "No endorsement documented for the next shift."),
    (
        "VAGUE_LANGUAGE",
        "warning",
        "The audio contained only vague phrasing where specifics are required.",
    ),
    (
        "MISSING_EDUCATION_RESPONSE",
        "info",
        "Teaching was documented without the learner's response or return demonstration.",
    ),
)

TEMPLATES = [
    {
        "jurisdiction": "PH",
        "format": "soapie",
        "version": 1,
        "name": "PH Skilled Nursing Note (SOAPIE)",
        "section_schema": PH_SOAPIE_SECTIONS,
        "flag_schema": PH_SOAPIE_FLAGS,
        "prompt_version": "ph_soapie_v1",
    },
    {
        "jurisdiction": "PH",
        "format": "fdar",
        "version": 1,
        "name": "PH Ward Note (FDAR)",
        "section_schema": PH_FDAR_SECTIONS,
        "flag_schema": PH_FDAR_FLAGS,
        "prompt_version": "ph_fdar_v1",
    },
]

# Defaults only. The active provider and model for a template are configuration, and
# are changed by updating the row -- not by editing a migration or shipping code.
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL_ID = "claude-sonnet-5"


def upgrade() -> None:
    connection = op.get_bind()
    statement = sa.text(
        """
        INSERT INTO note_templates (
            jurisdiction, format, version, name, section_schema, flag_schema,
            requires_diarization, prompt_version, llm_provider, model_id, is_active
        ) VALUES (
            :jurisdiction, :format, :version, :name,
            CAST(:section_schema AS jsonb), CAST(:flag_schema AS jsonb),
            false, :prompt_version, :llm_provider, :model_id, true
        )
        ON CONFLICT (jurisdiction, format, version) DO NOTHING
        """
    )
    for template in TEMPLATES:
        connection.execute(
            statement,
            {
                **template,
                "section_schema": json.dumps(template["section_schema"]),
                "flag_schema": json.dumps(template["flag_schema"]),
                "llm_provider": DEFAULT_PROVIDER,
                "model_id": DEFAULT_MODEL_ID,
            },
        )

    # PATIENT_IDENTIFIER_DETECTED is universal, not PH-specific: a US home visit
    # names the client just as readily as a PH ward recap names the patient. Without
    # this, the two rows seeded in 0002 would permanently lag the spec every
    # template -- theirs included -- is now supposed to satisfy.
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

    # Reverse the US backfill by filtering the flag out of the stored array, rather
    # than assuming its position -- the array's order is not part of the contract.
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
    connection.execute(
        sa.text("DELETE FROM note_templates WHERE jurisdiction = 'PH' AND version = 1")
    )
