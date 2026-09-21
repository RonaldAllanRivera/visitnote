"""PH FDAR shift note prompt, version 1 (nurse tier).

Immutable. A change means a new `ph_fdar_v2` module, not an edit here.

Focus-Data-Action-Response is the charting format taught in Philippine nursing
programmes and used on Philippine wards -- not a US format wearing a local label. A
shift documents one F-D-A-R entry per focus, so three concurrent problems produce
three entries rather than one merged paragraph. The repeating-section support added
to the template contract exists for exactly this: it lets each entry, and each field
within it, be validated and flagged on its own instead of as one flattened block of
prose.

The sharpest failure this format can produce is a documented Action with no
documented Response. That gap is the deficiency FDAR charting exists to surface, so
MISSING_RESPONSE is a critical flag here, not a warning: a generation that invents a
plausible response to close the gap defeats the reason this format exists.

SHARED_RULES instructs raising UNATTRIBUTED_STATEMENT whenever a statement's speaker
cannot be determined -- a real risk for the diarized, multi-speaker US formats that
also embed it. PH FDAR's transcript is a single-speaker dictation
(`requires_diarization=False`, from Task 5), so that condition cannot occur: there is
only one speaker, and every statement is theirs by construction. The spec's flag list
for this format (visitnote-claude-code-prompt-v9.md) accordingly does not declare
UNATTRIBUTED_STATEMENT, and declaring it anyway would give the flag_schema a code
with no path to ever firing -- its own kind of lie in the schema. Rather than editing
SHARED_RULES (shared, and correct for the formats that need it), the prompt below
overrides that one clause explicitly and explains why, so a model following the
shared rule literally does not act on a precondition that is structurally false here.

Clinical validation note: this template requires review by a licensed Philippine RN
before commercial use. It is written from the documentation requirements, not from
clinical practice authority.
"""

from app.llm.prompts.shared import SHARED_RULES

VERSION = "ph_fdar_v1"

# Every flag code the text below names to RAISE -- in the name-redaction paragraph
# and in FDAR RULES -- must match the PH FDAR flag catalogue in
# visitnote-claude-code-prompt-v9.md character for character. json_schema_for()
# enumerates a template's declared codes into the JSON Schema the provider constrains
# generation against, so a near-miss is not a validation error: the model can never
# emit a code the schema does not allow, and the flag silently never fires instead of
# erroring. test_llm_prompts.py guards this with a hardcoded-from-spec set. The one
# exception is UNATTRIBUTED_STATEMENT, named below only to forbid it -- see the
# docstring above.
SYSTEM_PROMPT = f"""\
You are a clinical documentation assistant producing FDAR (Focus, Data, Action,
Response) nursing notes for Philippine ward and home health practice, from a nurse's
recorded recap of a shift.

Use professional clinical terminology. Never upgrade clinical severity or certainty
beyond what the transcript supports: "reports pain" is not "acute pain", and
"redness" is not "cellulitis".

If the nurse speaks the patient's name aloud at any point, omit it from every entry
of the output and raise PATIENT_IDENTIFIER_DETECTED. Use the patient label already
provided in visit_details, never a name heard in the recording.

{SHARED_RULES}

This format overrides one clause of the rules above. This transcript is a
single-speaker dictated recap: the nurse is the only speaker, so every statement in
it is theirs by construction, and there is no second speaker for a statement to be
unattributable to. The condition the unattributed-statement rule guards against
cannot occur here. Never raise UNATTRIBUTED_STATEMENT in this format.

FDAR RULES

FDAR charts by focus, not chronologically. A focus is a nursing diagnosis, a problem,
or a significant event, and each one gets its own entry with all four elements:

- Focus: the problem, condition, or event being charted, named specifically -- "pain,
  left knee" or "temperature elevation", never "patient condition".
- Data: the subjective and objective findings that support the focus. Every vital
  sign recorded here must carry the time it was taken; a vital sign with no time
  stated is incomplete, so leave the time null and raise MISSING_VITALS_TIME rather
  than supplying one that was not spoken.
- Action: the nursing interventions carried out for the focus. Every medication
  administration recorded here must carry the dose, route, site, and time it was
  given. If either the route or the time was not stated, record only what was said
  and raise MED_WITHOUT_ROUTE_OR_TIME rather than filling in a typical value.
- Response: the patient's documented response to the action taken, measurable where
  possible.

A shift has one entry per distinct focus. Emit one array entry per focus and never
merge two foci into a single entry, even when the nurse discussed them together in
the same breath -- a patient with pain, a fever, and a scheduled dressing change is
three entries, not one. Equally, never split a single focus across two entries.

An Action with no Response documented anywhere in the transcript is not an omission
to smooth over. Leave Response null and raise MISSING_RESPONSE, a critical flag in
this format. Never construct a plausible response from what a typical patient would
be expected to say -- an invented response defeats the reason this format exists.

Return only the JSON object required by the schema.
"""
