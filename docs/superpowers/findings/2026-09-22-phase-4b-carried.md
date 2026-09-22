# Phase 4b — findings carried into Phase 5

Raised by the final whole-branch review of `feat/phase-4b-jurisdiction` on 2026-09-21.
The Critical finding was resolved before merge by **narrowing the claim** rather than
implementing it: `PATIENT_IDENTIFIER_DETECTED` is now declared only on the two PH
templates, which are the two whose prompts actually instruct it. Everything below is
open.

All six shared one property: each lives *between* tasks, so nine passing per-task
reviews could not see any of them. That is worth knowing before Phase 5 is planned.

## Important

### 2. `render_transcript` injects `UNATTRIBUTED_STATEMENT` into every PH request

`app/llm/prompts/shared.py:98-113` builds the SPEAKER ROLES block of the **user** content
for every generation, and both branches instruct the model to raise
`UNATTRIBUTED_STATEMENT`. For PH the system prompt says never to raise it, the same
request's user content says it must, and the code is not in the template's declared
codes or the JSON Schema enum. If the model follows the user content, `_normalise_flags`
rejects it and burns the single repair attempt; a repeat is a non-retryable
`PipelineError`.

Task 8 audited `SYSTEM_PROMPT` only, and the guard test reads only `system_prompt`. Fix:
make the roles block conditional — for a single-speaker transcript, say so and omit the
clause. Gate on `spec.requires_diarization` if that is cleaner than inspecting the turns.
Then extend the guard test to check the rendered **user** content too, not just the
system prompt.

### 3. The fake LLM provider cannot produce a valid PH FDAR note

`app/llm/providers/fake.py:37` does `dict.fromkeys(keys_of("sections"), PLACEHOLDER)` — a
string for every section, including the repeating one. Against the real seeded FDAR
schema, `focus_entries` is a string and `validate_output` rejects it; the fake is sticky,
so the repair returns the same payload and the run ends non-retryable.

That breaks the promise in the function's own docstring — that this is what makes
`docker compose up` produce a working end-to-end flow with no API key — on the one format
this phase exists to add. Fix: the fake emits a list of entries, each carrying the
declared field keys, for any section the spec marks repeating.

### 4. PH SOAPIE's seeded section descriptions reintroduce the CMS concepts the prompt omits

`ph_soapie_v1.py` states that the CMS concepts "do not appear anywhere in this module,
prompt text included… Omission, not negation, is the only safe way to drop a section."
But `0011_seed_ph_templates.py` keeps `intervention` as "…**and why each required a
licensed nurse**", "ongoing need for **skilled care**", and "progress toward
**plan-of-care** goals". `json_schema_for` puts every `section.description` into the
schema the provider is constrained on, so the model receives all three concepts through
the other channel.

Worse: `MISSING_NECESSITY_RATIONALE` and `MISSING_POC_LINK` were dropped from PH SOAPIE's
flag set, so invented PH-flavoured necessity or plan-of-care content is now unflagged.

Fix: rewrite those three PH SOAPIE section descriptions so they describe the clinical
content without the CMS framing. Keep the US SOAPIE descriptions unchanged.

### 5. Nothing validates `(jurisdiction, note_format)` at visit creation

`app/services/visits.py:75-77`: `note_format=payload.note_format or
user.default_note_format or NoteFormat.SHIFT_NOTE`. A PH user who abandoned onboarding
(NULL default) gets `(PH, shift_note)`, for which no template exists. The visit is
accepted 201, consumes a quota unit, and dies at `Pipeline._template` non-retryably.
`VisitCreate.note_format` is unconstrained, so a PH user can also post `shift_note`
explicitly, and a US user `fdar`.

`AuthService.update_profile` goes to real trouble reconciling a stranded *default*; the
per-visit path bypasses that guard entirely. Fix: validate in `VisitService.create` that
an active template exists for `(user.jurisdiction, resolved_format)` and raise a domain
error the router maps to 422, the same shape as `ProhibitedCaptureModeError`. Check
against `note_templates` via the repository, never a hardcoded map. Place it so a
replayed idempotency key still returns the existing visit.

### 6. `app/models/visit.py:24` disagrees with the database, and `alembic check` proves it

Model says `name="user_id_idempotency_key"`; the DB has
`uq_visits_user_id_idempotency_key`. `alembic check` reports a removed and an added
constraint, so autogenerate would propose dropping and recreating the **idempotency**
constraint. Identical to the defect Task 3 fixed on `note_templates`. One-line model fix,
no migration.

**Also add `alembic check` to CI** (`.github/workflows/ci.yml`, beside the existing
upgrade/downgrade/upgrade step). It catches this whole class, and its absence is why
this survived.

## Minor — fix in the same wave, all cheap

7. `TemplateSpec.jurisdiction` has no reader in `app/`. Add it to the `generate` trace
   span beside `prompt_version`; `eval_runs.jurisdiction` will want it in Phase 5b.
8. **Process references leaked into shipped source, and several are now false**:
   `ph_fdar_v1.py:21` ("from Task 5"), `test_pipeline.py:255` ("not seeded until Task 8"),
   `test_note_templates.py:143,200,222`, `test_llm_prompts.py:191-192` ("Task 9 has not
   seeded the PH template rows yet"), `:197,213` ("the coordinator"). Rewrite each to say
   the durable technical reason instead of naming a task or a process role. This
   repository is read as a portfolio piece.
9. **No pipeline test constructs a PH visit.** Every `Visit(...)` in `test_pipeline.py`,
   `test_job_task.py` and `test_note_persistence.py` is `Jurisdiction.US`, and nothing
   composes seeded FDAR row → `TemplateSpec` → `json_schema_for` → `validate_output`. Add
   that test. It would have caught findings 2 and 3 on its own.
10. `ph_fdar_v1.py:78` instructs "leave the time null and raise `MISSING_VITALS_TIME`",
    but a focus entry's only fields are focus/data/action/response — there is no time
    field to null. Reword to what the model can actually do.

## Deliberately accepted — not defects to fix

- `jurisdiction_for_timezone` defaulting an unmapped zone to US (design decision, stands).
- `0010` backfilling `visits.jurisdiction` from `server_default` rather than per-user
  (no production data; harmless).
- Spec drift on migration numbers / `CHAR(2)` wording — the controller is fixing the spec.
- The Phase 5 fabrication checker and `note_flags.section_key` — later phases.
