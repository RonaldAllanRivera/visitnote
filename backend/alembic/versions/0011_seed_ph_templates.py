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
- `PATIENT_IDENTIFIER_DETECTED` is declared on the two PH rows only, not on the
  existing US ones. The flag's intent is universal -- a nurse speaking a patient's
  name aloud is a risk in any jurisdiction -- but `shift_note_v1` and `soapie_v1` are
  immutable modules carrying no name-redaction instruction, so declaring it there
  would put a code in the generation schema that nothing ever asks the model to raise.
  A flag that is declared but never requested produces a clean note rather than a
  missing-control finding, which is worse than not declaring it at all. US enforcement
  arrives with `shift_note_v2` / `soapie_v2`, which carry the instruction.
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
# Philippine analogue. Every retained section keeps US SOAPIE's text verbatim except
# intervention, plan and evaluation, which US phrases in CMS survey and Medicare-claim
# terms (necessity for a licensed nurse, ongoing need for skilled care, progress
# toward plan-of-care goals) that have no PhilHealth analogue either. json_schema_for()
# puts every description into the schema the provider is constrained on, so carrying
# those terms here -- even unreferenced by the prompt -- would hand the model a
# concept it could invent PH-flavoured content to satisfy, with
# MISSING_NECESSITY_RATIONALE and MISSING_POC_LINK both absent from this format's
# flag set to catch it. See ph_soapie_v1.py's docstring for the same reasoning applied
# to the prompt text.
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
        "Plan for the next visit, with rationale and discharge trajectory.",
    ),
    (
        "intervention",
        "Intervention",
        "Skilled nursing services performed, described with enough clinical detail to "
        "stand as a nursing record.",
    ),
    (
        "evaluation",
        "Evaluation",
        "Patient or caregiver response to interventions, measurable where possible.",
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
# PATIENT_IDENTIFIER_DETECTED, new with this phase and declared on the PH rows only --
# see the module docstring for why the US rows do not get it yet.
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


def downgrade() -> None:
    """Remove the PH rows, and deal with the `fdar` value this migration made usable.

    Below 0008 the two-value `note_format` ENUM is restored, so `fdar` stops being
    representable at all. Anything still holding it has to be resolved here -- at the
    migration that owns the concept -- rather than three migrations later as an opaque
    `invalid input value for enum note_format: "fdar"` cast failure with no indication
    of which rows caused it.
    """
    connection = op.get_bind()

    # A stranded default is safe to clear: the column is nullable, and "no default
    # chosen" is the state every account already occupies before onboarding.
    connection.execute(
        sa.text("UPDATE users SET default_note_format = NULL WHERE default_note_format = 'fdar'")
    )

    # A captured visit or a generated note is not safe to clear. Both columns are NOT
    # NULL, and an FDAR note has no honest pre-0011 representation: remapping it to
    # SOAPIE would misstate what was charted, and deleting it would destroy a record
    # this product treats as legally significant (see `Visit.audio_key` and the
    # sign-off lock). So refuse, name the counts, and leave the decision to whoever is
    # rolling back.
    visits_stranded, notes_stranded = connection.execute(
        sa.text(
            """
            SELECT (SELECT count(*) FROM visits WHERE note_format = 'fdar'),
                   (SELECT count(*) FROM notes WHERE format = 'fdar')
            """
        )
    ).one()
    if visits_stranded or notes_stranded:
        raise RuntimeError(
            f"cannot downgrade past 0011: {visits_stranded} visit(s) and "
            f"{notes_stranded} note(s) are recorded as 'fdar', which has no "
            "representation below migration 0008. Export or re-key that data "
            "deliberately first; this migration will not remap it to another format "
            "or delete it on your behalf."
        )

    connection.execute(
        sa.text("DELETE FROM note_templates WHERE jurisdiction = 'PH' AND version = 1")
    )
