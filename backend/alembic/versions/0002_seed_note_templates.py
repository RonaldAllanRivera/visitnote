"""Seed both note templates.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-21

Seeded as a data migration rather than a fixture so that every environment -- local,
CI, staging, production -- starts with identical template definitions. The review
editor renders from `section_schema` and the flag engine validates against
`flag_schema`, so these rows are the contract both clients and the LLM layer share.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _sections(*items: tuple[str, str, str]) -> dict[str, object]:
    return {
        "sections": [
            {"key": key, "label": label, "order": i + 1, "description": description}
            for i, (key, label, description) in enumerate(items)
        ]
    }


def _flags(*items: tuple[str, str, str]) -> dict[str, object]:
    return {
        "flags": [
            {"code": code, "severity": severity, "description": description}
            for code, severity, description in items
        ]
    }


SHIFT_NOTE_SECTIONS = _sections(
    ("shift_details", "Shift details", "Client label, date, start time, end time."),
    ("care_provided_adls", "Care provided (ADLs)",
     "Hygiene, toileting, mobility and transfers, meals prepared and eaten, hydration."),
    ("medications", "Medications",
     "Reminders or administrations, times, missed or refused doses."),
    ("vitals", "Vitals", "Only if explicitly stated in the audio."),
    ("observations", "Observations",
     "Mood, mobility, appetite, skin, pain, confusion. Factual only, never interpretive."),
    ("changes_from_baseline", "Changes from baseline",
     "Anything different from this client's normal presentation."),
    ("incidents", "Incidents", "Falls, refusals, injuries, unusual events."),
    ("tasks_not_completed", "Tasks not completed",
     "What was skipped and the reason the caregiver stated."),
    ("handover", "Handover", "Forward-looking notes for the next caregiver."),
)

SHIFT_NOTE_FLAGS = _flags(
    ("MISSING_SHIFT_TIMES", "critical", "Start or end time was not stated."),
    ("UNREPORTED_CHANGE", "critical",
     "Transcript mentions a fall, new pain, new confusion, or a skin change that is not "
     "captured in the incidents or changes sections."),
    ("MISSING_ADLS", "warning", "No hygiene, meals, or mobility assistance mentioned."),
    ("MISSING_MEDS", "warning", "No medication statement of any kind."),
    ("MISSING_INTAKE", "warning", "No food or fluid intake mentioned."),
    ("MISSING_HANDOVER", "warning", "No forward-looking note for the next caregiver."),
    ("INCOMPLETE_TASK_UNEXPLAINED", "warning",
     "A task was described as not done with no reason given."),
    ("VAGUE_LANGUAGE", "warning",
     "The audio contained only vague phrasing where specifics are required."),
    ("UNATTRIBUTED_STATEMENT", "warning",
     "A reported statement could not be attributed to a speaker and was not quoted."),
    ("NOTE_CONTAINS_VENTING", "info",
     "Interpersonal complaints were detected and omitted from the note."),
)

SOAPIE_SECTIONS = _sections(
    ("visit_details", "Visit details",
     "Patient label, visit date, exact arrival time, exact departure time."),
    ("subjective", "Subjective",
     "Patient or caregiver reported status, symptoms, concerns. Patient's own words quoted."),
    ("objective", "Objective",
     "Vital signs, exam findings, measurable data such as wound dimensions, stage and "
     "drainage character, home environment and safety observations."),
    ("assessment", "Assessment",
     "Clinical assessment tied to diagnosis; progress or change since the last visit."),
    ("plan", "Plan",
     "Plan for the next visit with rationale, discharge trajectory, ongoing need for "
     "skilled care."),
    ("intervention", "Intervention",
     "Skilled services performed and why each required a licensed nurse."),
    ("evaluation", "Evaluation",
     "Patient or caregiver response to interventions, measurable where possible; "
     "progress toward plan-of-care goals."),
    ("homebound_status", "Homebound status",
     "Patient-specific statement of why the patient cannot leave home. Never boilerplate."),
    ("coordination_of_care", "Coordination of care",
     "Physician, PT, OT, SLP, MSW, aide or family communication; new orders."),
    ("medication_review", "Medication review",
     "Medications reviewed or reconciled this visit, plus any issues identified."),
)

SOAPIE_FLAGS = _flags(
    ("MISSING_VITALS", "critical", "No vital signs documented for a skilled nursing visit."),
    ("MISSING_VISIT_TIMES", "critical", "Arrival or departure time was not stated."),
    ("MISSING_SKILLED_SERVICE", "critical",
     "No skilled service documented, which does not support a billable skilled visit."),
    ("MISSING_NECESSITY_RATIONALE", "critical",
     "An intervention was named with no statement of why a licensed nurse was required."),
    ("MISSING_HOMEBOUND", "critical", "No patient-specific homebound justification."),
    ("UNREPORTED_CHANGE", "critical",
     "Transcript indicates a clinical change that is not documented in the note."),
    ("MISSING_RESPONSE", "warning", "No patient response to the interventions performed."),
    ("MISSING_MED_REVIEW", "warning", "No medication review or reconciliation documented."),
    ("MISSING_POC_LINK", "warning", "Assessment is not tied to the plan of care."),
    ("MISSING_NEXT_VISIT_PLAN", "warning", "No plan stated for the next visit."),
    ("MISSING_COORDINATION", "warning",
     "Transcript indicates a reportable change but no physician or team communication "
     "is documented."),
    ("VAGUE_LANGUAGE", "warning",
     "The audio contained only vague phrasing where measurable data is required."),
    ("UNATTRIBUTED_STATEMENT", "warning",
     "A reported statement could not be attributed to a speaker and was not quoted."),
    ("MISSING_EDUCATION_RESPONSE", "info",
     "Teaching was documented without the learner's response or return demonstration."),
    ("MISSING_PAIN_ASSESSMENT", "info", "No pain assessment documented."),
)

TEMPLATES = [
    {
        "format": "shift_note",
        "version": 1,
        "name": "Shift Note",
        "section_schema": SHIFT_NOTE_SECTIONS,
        "flag_schema": SHIFT_NOTE_FLAGS,
        "prompt_version": "shift_note_v1",
    },
    {
        "format": "soapie",
        "version": 1,
        "name": "Skilled Nursing Note (SOAPIE)",
        "section_schema": SOAPIE_SECTIONS,
        "flag_schema": SOAPIE_FLAGS,
        "prompt_version": "soapie_v1",
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
            format, version, name, section_schema, flag_schema,
            prompt_version, llm_provider, model_id, is_active
        ) VALUES (
            CAST(:format AS note_format), :version, :name,
            CAST(:section_schema AS jsonb), CAST(:flag_schema AS jsonb),
            :prompt_version, :llm_provider, :model_id, true
        )
        ON CONFLICT (format, version) DO NOTHING
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
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM note_templates "
            "WHERE prompt_version IN ('shift_note_v1', 'soapie_v1') AND version = 1"
        )
    )
