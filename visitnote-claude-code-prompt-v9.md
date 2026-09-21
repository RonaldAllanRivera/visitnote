# VisitNote AI — Build Specification v9

> **Read this first.** v9 supersedes [`visitnote-claude-code-prompt-v8.md`](visitnote-claude-code-prompt-v8.md).
> Phases 1–4 are built and merged; this specification does **not** ask for them to be
> rebuilt. The reasoning behind every change is recorded in
> [`SPEC-CHANGELOG.md`](SPEC-CHANGELOG.md).

---

## What changed from v8, in one page

v8 described a single-market product: US home care and home health, billed in PHP
through GCash. Those two halves never fit together — the SOAPIE template encoded CMS
home-health survey concepts (homebound status, skilled-necessity rationale,
plan-of-care linkage) while the payment rail was a Philippine consumer wallet.

v9 resolves it by making **jurisdiction an explicit dimension of the product** rather
than an unstated assumption:

1. **Two jurisdictions, `US` and `PH`**, carried on users and on note templates.
2. **Four seeded note templates** instead of two: US Shift Note, US SOAPIE, PH SOAPIE,
   and PH FDAR — the format Filipino ward nurses actually chart in.
3. **A hard v1 scope line.** The Expo mobile client and the PH Endorsement format move
   to a documented roadmap. v1 is the clinical core, the eval suite, **the manual GCash
   billing loop**, and the portfolio packaging.
   **There is no Stripe, and no second payment provider seam.** Manual GCash activation
   is the only payment path, and it ships in v1 because it has to be tested against
   real customers before the product can be sold.
4. **`note_format` moves off the Postgres ENUM.** Formats are now a growing,
   data-driven set; an ENUM is the wrong type for one.
5. **Capture mode is gated by jurisdiction**, because recording a third party on a
   Philippine hospital ward is a criminal-law problem, not a UX preference.
6. **Corrected API constraints** for the current Claude models — sampling parameters
   and assistant prefill are rejected outright, which changes how the pipeline
   enforces deterministic, schema-valid output.

Nothing in this list requires deleting code. The jurisdiction change is one additive
migration; the PH templates are seed rows and prompt modules.

---

## Project Overview

**VisitNote AI** converts recorded audio from nursing work into structured,
compliance-ready documentation, and flags every element a reviewer or auditor would
expect to find and did not.

It serves two markets with one pipeline:

- **United States** — home care and home health. Caregivers, HHAs and CNAs writing
  daily shift notes; RNs and LPNs writing skilled nursing notes under Medicare-style
  documentation standards.
- **Philippines** — hospital bedside nursing. Ward RNs writing FDAR notes, the
  charting format taught in Philippine nursing schools and used on Philippine wards.

Flow: the user records or uploads audio, the backend transcribes it, an LLM structures
it into the note format selected for their jurisdiction and role, a flag engine marks
missing or non-compliant elements, and the user reviews, edits, signs, and exports.

The hard part is not generating text. It is **not generating text that isn't true**,
and proving that property holds across releases.

### The two markets have different jobs

They are not symmetric, and pretending otherwise would produce a confused product:

- **The Philippines is the revenue market.** Pricing is in PHP, payment is manual
  GCash, and the first paying customers are PH ward nurses. The commercial hypothesis
  gets tested here, by hand, at small scale.
- **The United States is the portfolio and validation market.** US templates exist
  because the US RN validates them, because US home health is the documentation domain
  with the richest public compliance standards to build flags against, and because US
  employers read this repository. **US users are trial and demo accounts in v1** —
  GCash is a Philippine wallet, there is no second rail, and no US customer can pay.

Stating this is what keeps "two jurisdictions" from reading as an unfocused product.
One market pays; the other proves the architecture generalizes.

### Why two markets is a feature, not scope creep

Ambient clinical documentation is crowded at the top — Abridge, Suki, DeepScribe,
Ambience, Dragon Copilot — and EHR vendors now bundle ambient AI, some at no extra
cost. Every one of those products targets the US physician encounter inside an EHR.

None of them will ever build FDAR charting for Philippine ward nurses. That is a moat
of **domain knowledge**, not of vendor neglect, and it is more durable than the v8
positioning ("small agencies with no EHR to bundle into") on its own.

The engineering claim the dual market lets the README make is the one a reviewer
actually cares about:

> One pipeline, four note formats, two regulatory regimes — because templates and
> their flag schemas are rows, not code.

---

## The v1 Scope Line

**The product will not be demoed until v1 is complete.** That makes the definition of
"complete" the single most consequential decision in this specification, so it is
stated once, here, and everything else is measured against it.

**In v1:**

- Phases 1–4 (built): scaffold, auth, capture, pipeline
- Phase 4b: the jurisdiction migration and PH template seeding
- Phase 5: review, section editing, sign-off, PDF
- Phase 5b: the eval suite, in both jurisdictions
- Phase 6: **billing — the entitlement engine and the full manual GCash loop**
- Phase 7 (reduced): a minimal review queue and three charts
- Phase 8: share links, audio deletion, audit log, operator console
- Phase 9: landing page, public demo, README, ARCHITECTURE.md, ADRs, demo video

**Not in v1** — listed in the README as a roadmap, with reasons:

- The Expo mobile client
- The PH Endorsement note format
- OASIS assessments

**Never, unless the business changes**: card processing, Stripe, any second payment
provider. This is not a deferral, it is a decision — see below.

A roadmap that states what was deferred and why reads as scope discipline. A product
that quietly lacks features reads as unfinished. These are the same repository; the
difference is entirely in the documentation.

---

## Jurisdiction Model

Jurisdiction is an ISO 3166-1 alpha-2 code stored as `CHAR(2)` with a check constraint
limiting it to `US` and `PH`. It is **not** a Postgres ENUM, for the same reason
`note_format` stops being one: the set grows.

### What jurisdiction selects

| Concern | US | PH |
|---|---|---|
| Note templates available | `shift_note`, `soapie` | `soapie`, `fdar` |
| Capture modes permitted | `live_audio`, `spoken_recap` | `spoken_recap` only |
| Privacy regime named in the UI | HIPAA posture, state wiretap law | RA 10173 (Data Privacy Act), RA 4200 (Anti-Wiretapping) |
| Currency displayed | `price_usd` | `price_php` |
| Monetized in v1 | no — trial and demo only | yes — manual GCash |
| Diarization | required | off by default |
| Note's legal status | the note **is** the record | the note is a **draft** for the chart |

### Jurisdiction is not the same axis as format

This is the reason it gets its own column rather than being folded into the format
string. **Filipino nurses also chart SOAPIE** — it is taught in PH nursing programs
and used in PH facilities. But PH SOAPIE must not flag homebound status or
skilled-necessity rationale, because those are CMS survey concepts with no PhilHealth
analogue.

That is the same format with a different flag schema. `ph_soapie` as a format value
would conflate two independent dimensions and make the eval suite's per-format
reporting incoherent. One format, two jurisdictions, two `note_templates` rows.

### Resolution

A template is resolved by `(jurisdiction, format)` to the row with `is_active = true`
and the highest `version`. `users.jurisdiction` is captured at onboarding, defaulted
from the user's IANA timezone (`Asia/Manila` → `PH`, US zones → `US`) and editable.
Every note records the template id that produced it, so a note's jurisdiction is a
historical fact rather than a join through the user's current setting.

---

## Architecture (monorepo, one API, one client in v1)

Unchanged from v8 in structure. One FastAPI service owns the database; every client
consumes one versioned REST API and generates its types from that API's OpenAPI
schema, so a backend contract change surfaces as a TypeScript compile error rather
than a runtime surprise.

```
backend/    FastAPI — routers -> services -> repositories, arq worker, Alembic, evals
web/        React 19 + Vite — capture, review, dashboard, ops
deploy/     Caddy, docker-compose.prod.yml, systemd units
mobile/     Expo — DEFERRED, not built in v1
```

**`routers/` → `services/` → `repositories/`.** Routers do HTTP and nothing else and
never touch a database session. Business rules live in services, queries in
repositories. The payoff is that the entitlement engine, the pipeline, and the eval
runner all call the same service code without a request object in sight.

**The pipeline runs in a worker, not a request.** Transcription and generation take
tens of seconds and fail in ways that need retrying. The API enqueues and returns; the
client polls. One worker container, so cron jobs cannot double-fire.

**Providers sit behind protocols.** `LLMProvider` and `TranscriptionProvider` are
`typing.Protocol` definitions. No vendor SDK type is allowed to escape its provider
module — the pipeline, the evals, and the tracing layer only ever see local types.
Tests inject fakes and never call a paid API.

**Notes are stored twice, on purpose.** `notes.sections` is JSONB because its shape
varies per template and nothing queries into it. Flags are *also* written to a
normalized `note_flags` table, because the dashboard aggregates across flag codes and
that promise is not keepable against a JSONB array at volume. Both writes happen in
one transaction, with a test asserting they never diverge.

**Everything is UTC.** All timestamps are `TIMESTAMPTZ`; the capturing user's IANA
timezone rides on the visit. A 22:00–06:00 shift is the normal case in both home care
and hospital nursing, and subtracting clock times to get its duration yields a
negative number and a false "missing shift times" flag. There is a test for it, and
one for a DST crossing.

---

## Core Capture Flow

1. The user starts a visit (or a shift, in PH). Creation is **idempotent** on a
   client-supplied key: a replayed key returns the same visit and consumes one quota
   unit, never two.
2. The client requests upload credentials and uploads to object storage directly —
   single-part or multipart with resume.
3. On upload completion the API enqueues a pipeline job and returns.
4. The worker: download → `ffmpeg` normalize (mono, 16 kHz) → transcription →
   template-driven generation → flag evaluation → persist note and normalized
   `note_flags` rows in one transaction.
5. The client polls a status endpoint reporting the pipeline stage, with backoff,
   stopping at a terminal state.

### Capture mode is a legal boundary, and jurisdiction moves it

`CaptureMode` distinguishes `live_audio` (recording a third party, requiring their
acknowledgment) from `spoken_recap` (the user dictating afterwards, recording nobody
else). v8 treated this as a consent-gate UX decision. In PH it is a criminal-law
constraint:

**The Philippine Anti-Wiretapping Act (RA 4200) requires the consent of *all* parties
to record a private communication, with criminal liability for violations.** A
hospital ward holds twenty to forty patients, their families, and other staff. Consent
from all parties is not obtainable, and "the nurse pressed a consent checkbox" does
not obtain it on their behalf.

Therefore: **`live_audio` is rejected server-side for `PH` users.** Not hidden in the
UI — rejected by the API, with a test asserting the rejection. The PH product is a
`spoken_recap` product: the nurse dictates an end-of-shift recap, recording only
themselves.

This is not a limitation to work around. A dictated recap is the workflow PH ward
nurses would realistically adopt anyway, and it happens to be cheaper to process.

---

## Note Formats

Four templates are seeded by Alembic data migration. Each is a row in `note_templates`
carrying its own `section_schema`, `flag_schema`, `prompt_version`, provider and model
id. The pipeline reads all format-specific behaviour from that row.

### US · Shift Note (caregiver tier)

Sections in order:

1. Shift details: client label, date, start time, end time (extracted if stated, else flagged)
2. Care provided (ADLs): hygiene, toileting, mobility/transfers, meals prepared and eaten, hydration
3. Medications: reminders or administrations, times, missed/refused doses
4. Vitals (only if stated in audio)
5. Observations: mood, mobility, appetite, skin, pain complaints, confusion level; factual only
6. Changes from baseline
7. Incidents: falls, refusals, injuries, unusual events
8. Tasks not completed: what was skipped and the stated reason
9. Handover: forward-looking notes for the next caregiver

Flags: `MISSING_SHIFT_TIMES` (critical), `MISSING_ADLS`, `MISSING_MEDS`,
`MISSING_INTAKE`, `UNREPORTED_CHANGE` (critical), `MISSING_HANDOVER`,
`INCOMPLETE_TASK_UNEXPLAINED`, `VAGUE_LANGUAGE`, `NOTE_CONTAINS_VENTING` (info),
`UNATTRIBUTED_STATEMENT`, `PATIENT_IDENTIFIER_DETECTED` (critical).

### US · Skilled Nursing Note, SOAPIE (nurse tier)

Sections in order:

1. Visit details: patient label, visit date, exact arrival time, exact departure time
2. Subjective: patient/caregiver reported status, symptoms, concerns; patient's own words quoted
3. Objective: vital signs, exam findings, measurable data, home environment/safety observations
4. Assessment: clinical assessment tied to diagnosis; progress or change since last visit
5. Plan: plan for next visit with rationale; discharge trajectory; ongoing need for skilled care
6. Intervention: skilled services performed, and why each required a licensed nurse
7. Evaluation: patient/caregiver response, measurable where possible; progress toward goals
8. Homebound status: patient-specific statement of why the patient cannot leave home
9. Coordination of care: physician/PT/OT/SLP/MSW/aide/family communication; new orders
10. Medication review: medications reviewed or reconciled this visit, plus issues

Flags — critical: `MISSING_VITALS`, `MISSING_VISIT_TIMES`, `MISSING_SKILLED_SERVICE`,
`MISSING_NECESSITY_RATIONALE`, `MISSING_HOMEBOUND`, `UNREPORTED_CHANGE`,
`PATIENT_IDENTIFIER_DETECTED`. Warning: `MISSING_RESPONSE`, `MISSING_MED_REVIEW`,
`MISSING_POC_LINK`, `MISSING_NEXT_VISIT_PLAN`, `MISSING_COORDINATION`,
`VAGUE_LANGUAGE`, `UNATTRIBUTED_STATEMENT`. Info: `MISSING_EDUCATION_RESPONSE`,
`MISSING_PAIN_ASSESSMENT`.

### PH · SOAPIE (variant)

Same sections as US SOAPIE **minus section 8 (Homebound status)**, which has no
Philippine analogue.

Flag schema drops `MISSING_HOMEBOUND`, `MISSING_NECESSITY_RATIONALE` and
`MISSING_POC_LINK` — all three are CMS home-health survey requirements, not clinical
documentation standards. Everything else is retained.

This template exists to prove the jurisdiction axis carries real semantic weight. It
costs one seed row and one prompt module.

### PH · FDAR (hospital ward — the primary PH format)

FDAR — **Focus, Data, Action, Response** — is the charting format taught in Philippine
nursing programs and used on Philippine wards.

**FDAR is structurally different from every other format in this product: a shift
produces *several* FDAR entries, one per focus.** A patient with pain, a fever, and a
scheduled dressing change generates three F-D-A-R blocks in one shift.

This has a direct consequence for Phase 5: **the schema-driven section editor must
support a repeating group**, not only a flat ordered list of sections. `section_schema`
gains a `repeating` section kind whose entries each carry their own sub-sections. This
is the one genuine application-code change the PH market requires, and it is
deliberately called out here so it is not discovered during Phase 5.

Structure:

1. Shift details: unit/ward, bed label, shift (AM/PM/Night), date, time in, time out
2. **Focus entries** (repeating, one or more), each containing:
   - Focus: the nursing problem, concern, or event being charted
   - Data: subjective and objective findings supporting the focus, with times
   - Action: nursing interventions performed, with times
   - Response: patient response and reassessment outcome
3. Medications administered: drug, dose, route, site, time
4. Intake and output
5. Doctor's orders received and carried out
6. Endorsement: carry-forward items for the next shift

Flags — critical: `MISSING_SHIFT_TIMES`, `MISSING_FOCUS` (data charted with no focus
named), `MISSING_RESPONSE` (an action with no documented patient response — the
classic FDAR deficiency), `MED_WITHOUT_ROUTE_OR_TIME`, `PRN_WITHOUT_RESPONSE`,
`UNREPORTED_CHANGE` (deterioration mentioned with no escalation documented),
`PATIENT_IDENTIFIER_DETECTED`. Warning: `MISSING_VITALS_TIME` (vitals stated without
the time taken), `MISSING_INTAKE_OUTPUT`, `PAIN_NOT_REASSESSED`,
`ORDER_NOT_ACKNOWLEDGED`, `MISSING_ENDORSEMENT`, `VAGUE_LANGUAGE`. Info:
`MISSING_EDUCATION_RESPONSE`.

`UNATTRIBUTED_STATEMENT` is **not** in the PH FDAR flag set. A spoken recap has one
speaker; there is nothing to attribute.

### Deferred · PH Endorsement

Shift-to-shift endorsement is the most-requested PH nursing artefact and it is
**deliberately out of v1**, for a structural reason worth stating:

An endorsement covers a nurse's **entire patient assignment** — five to fifteen
patients in one document. Every other format in this product is one note about one
care recipient, and the data model encodes that: `visits` references one client, and
`notes` references one visit.

Endorsement is therefore not a template change. It is a data model change. Shipping it
in v1 would mean reworking the visit/note relationship that Phases 3, 4 and 5 all
depend on. It belongs in a version that can afford that, and the README says so.

### `PATIENT_IDENTIFIER_DETECTED` — new, and it applies to every format

Critical severity. Raised when the transcript contains what appears to be a patient's
real name, and the name is stripped from the generated note rather than carried into
it.

Every template in this product uses a **pseudonymous label** — a client label in US
home care, a bed number in a PH ward. A nurse speaking aloud will still say the
patient's name, because that is how people talk. Without this flag the product would
quietly transcribe identifiers into stored notes, which is precisely the exposure the
pseudonymous label was designed to avoid.

This is not a PH-only concern, but it is sharper there. In US home care the **agency**
is the customer and can sign a data processing agreement. A PH staff nurse using this
product is an individual moving their employer's sensitive personal information onto
their own phone and into third-party infrastructure. The flag, and the de-identified
storage it enforces, is what makes that defensible.

---

## Speaker Attribution

A US home visit has at least two speakers — the nurse or caregiver, the client, and
often a family member. Both US prompts require the patient's own words to be quoted,
and the product forbids fabrication. **Attributing a quote to the wrong speaker is a
fabrication, and it is the easiest one to commit.**

Therefore, **for `US` templates**:

- Transcription runs with **diarization enabled**, and the transcript is persisted as
  ordered speaker turns (`speaker_label`, `start_ms`, `end_ms`, `text`), not a flat
  string. `transcripts.raw_text` remains for display and the fabrication checker;
  `transcripts.turns JSONB` carries the structure.
- The LLM receives the turn-structured transcript, with a role hint mapping the
  recording user to their speaker label where confidently inferable.
- **Prompt rule**: a statement whose speaker cannot be determined is never placed in
  Subjective as a patient quote. It becomes an unattributed observation and raises
  `UNATTRIBUTED_STATEMENT`. Guessing is forbidden.
- The fabrication checker fails any quoted string attributed to the patient unless it
  appears in a turn assigned to a non-recording speaker.
- At least three golden dataset cases exercise multi-speaker transcripts, including
  one where a family member reports a symptom the patient does not confirm.

**For `PH` templates**, diarization is **off**. A `spoken_recap` has one speaker, and
paying for diarization on a monologue buys nothing. The transcript is still persisted
as turns — a single turn — so the schema and the checker stay uniform across
jurisdictions.

The diarization requirement therefore lives on the template, not in the pipeline.
`note_templates.requires_diarization` is a boolean, and the transcription call reads
it. A US template receiving an undiarized transcript is an **error**, not a fallback.

---

## LLM Note Generation

One pipeline for all formats. Everything format-specific is read from the resolved
`note_templates` row: the section schema, the flag schema, the prompt module, the
provider, the model id, and now the jurisdiction and diarization requirement.

Output is validated with Pydantic against the active template's own schema. On
validation failure, retry **once** with a repair instruction naming the specific
defect, then mark the job failed. A retry that repeats the original request unchanged
is only a second chance at the same mistake.

Flag severity is taken from the template, never from the model. Banned vague phrases
are rejected in the note's own voice but permitted inside quotations, because what the
patient actually said is evidence.

### Model IDs live in configuration only — this is a hard rule

No model identifier string appears in pipeline, service, or router code. The provider
and model come from `app/core/config.py` defaults, overridden per template by
`note_templates.llm_provider` and `note_templates.model_id`.

Defaults at time of writing — **verify against the live model list at build time**:

| Purpose | Model | Input $/MTok | Output $/MTok |
|---|---|---|---|
| Note generation (default) | `claude-sonnet-5` | $2.00 | $10.00 |
| Cost-floor candidate, PH tier | `claude-haiku-4-5` | $1.00 | $5.00 |

The Haiku option is a **candidate**, not a decision. Which model a template pins is
chosen by eval results, not by price — that is the entire purpose of having both an
eval suite and a per-template `model_id`. A cheaper model that fails the fabrication
checker is not cheaper.

### API constraints that change how this pipeline is written

These are current-generation model behaviours, and each one invalidates an approach
that would otherwise be the obvious choice for a clinical pipeline:

- **`temperature`, `top_p` and `top_k` are rejected with a 400.** Sampling parameters
  were removed on the 4.6+ family. Determinism cannot be bought with `temperature=0`.
  It comes from **structured outputs** (`output_config: {format: {...}}`) plus
  `strict: true` on tool schemas.
- **Assistant prefill is rejected with a 400.** The other common trick for forcing
  JSON output is unavailable. Use structured outputs.
- **`output_format` is deprecated.** Use `output_config: {format: {...}}`.
- **`budget_tokens` is rejected with a 400.** Use `thinking: {type: "adaptive"}`, and
  control depth with `output_config: {effort: ...}`.
- **Prompt-cache the stable template prefix.** A template's instructions, section
  schema and flag schema are byte-identical across every note it generates. Render
  order is `tools` → `system` → `messages`, so the template prefix is cached and the
  per-note transcript goes after the last breakpoint. Verify with
  `usage.cache_read_input_tokens`; a persistent zero means something volatile leaked
  into the prefix.

### Unit economics, and why they are in this specification

The PH tier prices near ₱199/month against roughly 20 notes, so a note has about ₱10
of room. A ~90-second recap is ~300 transcript tokens on a ~3K-token templated prompt
producing ~1.2K tokens of output:

| Component | Cost |
|---|---|
| Generation (`claude-sonnet-5`, uncached) | ~$0.018 |
| Transcription (~1.5 min) | ~$0.01 |
| **Total per note** | **~$0.03 (~₱1.75)** |

That is roughly 5–6× gross margin before prompt caching, which lands mostly on the
input side and widens it further. The margin is real but not large, which is why
**per-note cost recording is a v1 requirement rather than an operator nicety**: audio
minutes, input and output tokens, and computed USD in `Decimal`, stored on the job. A
model with no configured price records **no cost**, never a misleading zero.

---

## LLM Provider Layer

`LLMProvider` and `TranscriptionProvider` are `typing.Protocol` definitions. The fakes
are written **before** the live clients, so the interface is shaped by what the
pipeline needs rather than by an SDK's return type.

`AnthropicProvider` is the default implementation. The active provider and model come
from config and are stored per template, so different formats can pin different
models. No vendor type leaves the provider module.

---

## Prompt Versioning

A prompt change is a **new module, not an edit**. Every generated note stores the
`prompt_version`, provider and model id that produced it, and that record is worthless
if the version's text can move underneath it.

Prompt modules are registered explicitly. `note_templates.prompt_version` points at the
active version. Promotion to active is gated on a passing eval run — see below.

Prompt modules are named by jurisdiction and format:
`prompts/us_shift_note/v1.py`, `prompts/us_soapie/v1.py`, `prompts/ph_soapie/v1.py`,
`prompts/ph_fdar/v1.py`.

---

## LLM Evaluation Suite

This is the project's strongest differentiator and it is **fully in v1**.

- **Golden dataset**: cases per template, each with a transcript, expected sections,
  and expected flag codes. Covers both jurisdictions.
- **Checkers**, each with its own unit tests: flag precision/recall/F1 per code,
  schema validity, and a **fabrication checker** — no vital sign, measurement, or
  quoted statement may appear in a note without transcript support.
- **Runner**: `python -m evals.run --jurisdiction PH --template fdar --prompt-version v2`
  runs against the real provider, writes a JSON report to `evals/reports/`, a row to
  `eval_runs`, and regenerates `EVALS.md` at the repo root.
- **CI**: `evals.yml` posts results as a PR comment. Prompt promotion is **disabled**
  unless the version has a passing run.
- Zero fabrication failures is a release condition, not a target.

### The two RNs are eval authors, not beta testers

The project has access to a licensed PH RN and a licensed US RN. The highest-value use
of that access is **authoring and validating golden dataset cases**, not clicking
through the UI.

This also discharges the clinical-review gate: the v8 specification already required
licensed-nurse review of the SOAPIE template before commercial launch, and the same
requirement now applies to FDAR. Golden cases authored and signed off by a licensed
nurse in the relevant jurisdiction *are* that review, and `EVALS.md` records it.

---

## LLM Observability

Tracing is optional by config and a **no-op when off**, so no call site is
conditional. With content redaction on, traces keep everything a regression looks like
and none of the patient content: prompt version, jurisdiction, template, model, token
counts, cost, per-stage latency, flag codes raised, schema validity, and whether a
repair was needed.

---

## Data Model

Unchanged from v8 except as listed. All timestamps `TIMESTAMPTZ`.

### Migration `0007` — jurisdiction

Additive, pre-launch, no data loss. Four changes:

1. **`note_templates.jurisdiction`** — `CHAR(2) NOT NULL`, check constraint
   `IN ('US','PH')`. Existing rows backfill to `'US'`.
2. **`note_format` moves off the Postgres ENUM.** `note_templates.format` and
   `users.default_note_format` become `VARCHAR(32)`, and the `note_format` ENUM type is
   dropped. `NoteFormat` remains a Python `StrEnum` for the known set.
3. **Unique constraint re-keyed** from `(format, version)` to
   `(jurisdiction, format, version)`, with the index on `(jurisdiction, format)`.
4. **`users.jurisdiction`** — `CHAR(2) NOT NULL`, same check constraint, defaulted from
   the user's IANA timezone at onboarding.

Also on `note_templates`: **`requires_diarization BOOLEAN NOT NULL`** (true for US
rows, false for PH).

**Why the ENUM goes.** A Postgres ENUM was the right type when formats were a fixed
pair. They are now a growing set: `ALTER TYPE ... ADD VALUE` cannot run inside a
transaction block, and values can never be removed. With six migrations and no
production data this conversion is free. After launch it is not.

### Migration `0008` — seed PH templates

Data migration seeding `ph_soapie` and `ph_fdar` v1 rows, in the same style as
`0002_seed_note_templates.py`.

**Time this phase.** If seeding a third and fourth format takes about a day because
the architecture is template-driven, that measurement is the README's evidence and the
answer to the interview question about it.

### Tables of note

- **users**: email, password_hash (nullable for Google-only), google_sub, full_name,
  role_title, default_note_format, **jurisdiction**, timezone (IANA), is_staff,
  is_demo, is_active, agency_id (nullable), agency_role
- **note_templates**: **jurisdiction**, format, version, name, section_schema JSONB,
  flag_schema JSONB, **requires_diarization**, prompt_version, llm_provider, model_id,
  is_active
- **notes**: visit_id, note_template_id, sections JSONB, flags JSONB, version,
  signed_at, signed_by, prompt_version, provider, model_id
- **note_flags**: note_id, code, severity, section — the analytics axis
- **eval_runs**: **jurisdiction**, template format, prompt_version, provider, model_id,
  metrics JSONB, passed, triggered_by, report_key

### Why flags are stored twice

`notes.flags` is the note payload: shape varies per template, never queried into.
`note_flags` is the analytics axis: the dashboard aggregates across flag codes with SQL,
never Python loops, and that promise is not keepable against a JSONB array at volume.
One document, two access patterns. Both written in one transaction, with a test that
they cannot diverge.

### Concurrency on note edits

Section PATCH is version-checked. A stale `notes.version` returns **409**. There is a
test.

---

## Billing — manual GCash activation

**This ships in full in v1.** The commercial hypothesis is untested, and it cannot be
tested without collecting money from a real customer. Manual activation is the whole
mechanism, not a placeholder for a later integration.

Payment happens out of band through GCash and the operator activates the account in the
ops console. **There is no card handling, no checkout SDK, and no webhooks anywhere in
this product.**

### Plans

Stored in the `plans` table, rendered from the API, never hardcoded. Fields: `code`,
`name`, `price_php`, `price_usd`, `billing_period_days`, `note_quota` (null =
unlimited), `allowed_formats`, `features` JSONB, `is_active`. Jurisdiction selects
which price is displayed.

- **Ward Nurse (PH)**: unlimited notes, `fdar` and `soapie`
- **Caregiver (US)**: 25 notes/month, `shift_note` only — priced but not purchasable in
  v1
- **Nurse (US)**: unlimited notes, both US formats — priced but not purchasable in v1
- **Agency** (3 seat minimum): everything plus dashboard, review queue, staff management

Every new account starts a 14-day trial automatically, in both jurisdictions. A US
account's trial simply expires with no purchase path, and the UI says so plainly rather
than offering a checkout that cannot complete.

### Payment flow

1. The user hits a paywall and opens Upgrade.
2. Upgrade shows plan selection, amount due in PHP, the GCash account name and number,
   the GCash QR image, and instructions — all from `payment_settings`.
3. The user pays in GCash, then submits: plan, amount, GCash reference number, date
   paid, sender name and number, and an optional receipt screenshot uploaded via a
   presigned URL.
4. Status becomes `pending_review`. The client shows "Payment submitted, we will
   activate your account shortly (usually within 24 hours)" with the reference echoed
   back.
5. The operator approves or rejects in `/ops/payments`.
6. On approval: subscription `active`,
   `current_period_end = max(now, existing period_end) + billing_period_days` so
   **renewals stack and never reset**, `activated_by` and note recorded, audit log
   entry, confirmation email.
7. On rejection: the reason is shown in-app and the user can resubmit.

A staff CLI activation command also exists, for the operator's own account and for
support cases. It writes the same audit log entry as the console path.

### Tables

- **subscriptions**: user_id or agency_id, plan_id, status
  (`trialing|active|past_due|expired|cancelled`), current_period_end, seats,
  notes_used_this_period, period_reset_at, manual, activated_by, activation_note
- **payment_submissions**: user_id, plan_id, amount, currency, method (`gcash`),
  reference_number (**unique per method; duplicates rejected**), paid_at, sender_name,
  receipt_key, status (`pending_review|approved|rejected`), reviewed_by, reviewed_at,
  rejection_reason
- **payment_settings** (single row): gcash_account_name, gcash_number, qr_image_key,
  instructions_markdown

### Entitlement engine (`app/services/entitlements.py`)

One `get_entitlements(user)` returning active state, plan code, remaining quota,
allowed formats, dashboard access, days remaining, and grace state. **Every gate in the
API and the client reads only this.** FastAPI dependencies
`require_active_subscription` and `require_format(format)`.

**Grace period**: 3 days past period end with a renewal banner; after grace, status
becomes `expired` and note creation blocks, while existing notes stay readable and
exportable. Never hold completed documentation hostage.

### Quota accounting — the rule, stated once

**Quota is consumed when a note reaches `ready`, not when a visit is created.**

A visit that fails the pipeline after three attempts costs the user nothing. Charging
at visit creation would mean a user on a 25-note plan pays for work the system failed
to deliver, which is both wrong and a support burden. Combined with the idempotency key
on visit creation, a network retry cannot double-charge either.

Quota resets at each period boundary via the daily arq cron.

### Why there is no `BillingProvider` protocol

v8 specified a provider seam so a second payment rail could be added later without
touching entitlement code. **v9 removes it.** There is no second rail planned, and a
protocol with exactly one implementation is an abstraction paying rent it does not
earn.

The decoupling that actually matters is kept, because it is load-bearing today: **the
entitlement engine knows nothing about how payment happened.** A subscription is
activated by the ops console, by the staff CLI, or by a trial starting, and the engine
cannot tell the difference. That is what makes all three paths testable against one
set of state transitions.

This is a deliberate contrast with `LLMProvider` and `TranscriptionProvider`, which
*do* earn their protocols — each has a real second implementation (the fake) that every
test in the suite depends on. The difference between those two cases is the ADR.

---

## Web App

Five zones, code-split, in v1:

1. **Public marketing** — landing, pricing from the API, FAQ, demo entry
2. **Public share pages** — read-only note by share token
3. **Capture and review** — the field client, mobile-first
4. **Minimal dashboard** — review queue plus three charts (reduced from v8's five
   analytics endpoints with URL-synced filters)
5. **Operator console** — staff only, returns a 404-style not found for non-staff

The dashboard survives the v1 cut, in reduced form, for an architectural reason: the
normalized `note_flags` table exists *because* views aggregate across flag codes. Cut
the dashboard entirely and that design decision becomes unmotivated, which weakens
both the product and the README's account of it.

**The section editor renders from `section_schema` with no format-specific
components**, and in v9 it must additionally handle the `repeating` section kind that
PH FDAR requires.

Access token in memory, refresh handled via a secure refresh flow with silent refresh
and request retry on 401. Route guards for auth, entitlement, and staff role. Empty,
loading and error states everywhere.

---

## Security, Privacy, and Compliance Posture

Two regimes, documented explicitly in the README, because the product now operates
under both.

### United States

HIPAA posture, BAA checklist, and the note that some US states impose all-party
consent for recording beyond the federal baseline. `live_audio` requires recorded
acknowledgment from the third party.

### Philippines

- **RA 10173, the Data Privacy Act of 2012.** Health information is *sensitive personal
  information*, with criminal penalties and a real regulator in the National Privacy
  Commission.
- **RA 4200, the Anti-Wiretapping Act.** All-party consent, criminal liability.
  `live_audio` is rejected server-side for PH users, as described above.
- **A pseudonymous label does not de-identify a recording.** This was true in v8 and is
  sharper here: the audio contains whatever the nurse said aloud. This is what
  `PATIENT_IDENTIFIER_DETECTED` and the audio deletion policy exist for.

### The note is not always the legal record

In US home health the note **is** the record the agency keeps and signs. On a PH
hospital ward the legal record is the hospital chart, and this product produces a
**draft the nurse transcribes into it**.

That difference is jurisdictional and belongs in the disclaimer, which is selected by
template:

- US: *"Drafts must be reviewed by the responsible caregiver or clinician before use.
  Not medical advice or a medical device."* SOAPIE adds: *"Final responsibility for
  clinical documentation accuracy rests with the signing clinician."*
- PH: *"This is a drafting aid. The patient's chart remains the legal record. Review
  every entry before transcribing it."*

Sign-off still exists for PH — it locks the draft and stamps it — but it is not
claimed to be a legal signature.

---

## Build Order

Commit after each phase.

| Phase | Content | State |
|---|---|---|
| 1 | Monorepo scaffold, FastAPI layers, Alembic, arq worker, web shell, CI | **done** |
| 2 | Auth: argon2, JWT access + rotating refresh with reuse detection, Google OAuth | **done** |
| 3 | Capture on web: idempotent visits, resumable upload, `MediaRecorder`, consent gate | **done** |
| 4 | Pipeline: provider protocols, ffmpeg → transcription → generation, retries, cost, tracing | **done** |
| **4b** | **Migrations `0007`/`0008`; jurisdiction-aware template resolution; onboarding captures jurisdiction; PH prompt modules; `live_audio` rejected for PH** | next |
| 5 | Review: schema-driven section editor **including repeating groups**, flags panel, version-checked PATCH, sign-off lock, WeasyPrint PDF, per-jurisdiction disclaimer | |
| 5b | Evals: golden dataset in both jurisdictions, checkers, runner, `eval_runs`, CI workflow, promotion gating, generated `EVALS.md` | |
| 6 | Billing: plans, subscriptions, entitlement engine with grace and quota-on-ready, cron resets, payment settings, Upgrade + GCash submission screens, receipt upload, `/ops/payments` approve/reject with stacking period extension, staff CLI activation | |
| 7 | Minimal dashboard: roster, review queue, three charts over `note_flags` | reduced |
| 8 | Share links, audio deletion, audit log, the remaining `/ops/*` screens (users, prompts, costs, settings — `/ops/payments` and `/ops/jobs` already exist), user settings | |
| 9 | Landing, public demo login, README, ARCHITECTURE.md, ADRs, demo video | **v1 complete** |

---

## Documentation and Portfolio Packaging

The strongest engineering here is invisible to anyone who does not clone the
repository, and a reviewer gives it a few minutes. These are build items.

- **README ordering**: problem statement → 90-second demo video → live demo link →
  architecture diagram → **AI Reliability** → **Two markets, one pipeline** → local
  setup → deploy guide → compliance posture → roadmap. AI Reliability goes above setup
  instructions, because it is the differentiator and almost nobody scrolls past setup.
- **AI Reliability section**: provider layer, prompt versioning, eval methodology and
  current scores, fabrication policy, what tracing captures under redaction.
- **Two markets, one pipeline section**: the jurisdiction model, the four templates,
  and the measured cost of adding the third and fourth. This is the configuration-over-
  branching argument, made with evidence.
- **`EVALS.md`**, generated: per-flag-code precision, recall and F1 **per jurisdiction**;
  fabrication failures; schema validity; cost and latency per note; pass thresholds; an
  honest note on sample size; and who validated the golden cases.
- **`ARCHITECTURE.md` plus 8–10 short ADRs** (~200 words each): arq rather than Celery;
  the repository layer; provider protocols; JSONB notes alongside normalized
  `note_flags`; prompt promotion gated on evals; **jurisdiction as a data dimension**;
  **`note_format` off the Postgres ENUM**; **`live_audio` prohibited under RA 4200**;
  **Endorsement deferred as a data-model change**; **manual billing with no provider
  protocol, and why that differs from the LLM and transcription seams**; web capture
  before native. ADRs demonstrate judgment, which is what an interviewer actually
  probes.
- **90-second demo video**: record → processing states → note with flags → fix a flag →
  sign off → PDF. Show one US note and one PH FDAR note.
- **Roadmap section** listing every deferred item with its reason.

---

## Quality Bar

**Backend**: ruff + mypy strict, pytest + pytest-asyncio + httpx AsyncClient against a
real Postgres, covering:

- auth and refresh rotation, cross-tenant denial, staff-route protection, demo-user
  write rejection
- **template resolution by `(jurisdiction, format)`, including that a US user cannot
  select a PH template and vice versa**
- **`live_audio` rejected for a PH user, accepted for a US user**
- **PH SOAPIE does not raise `MISSING_HOMEBOUND` on a transcript that would raise it
  under US SOAPIE** — the single test that proves jurisdiction carries semantic weight
- **an FDAR transcript with three foci produces three focus entries**, and one with an
  action but no stated patient response raises `MISSING_RESPONSE`
- **`PATIENT_IDENTIFIER_DETECTED` raised and the name absent from stored sections**
- entitlement states: trial, active, grace, expired, quota exhausted, format gated
- **payment approval extends a live period rather than resetting it** (stacking), and a
  duplicate GCash reference number is rejected
- **a US account cannot reach a purchase path**, and its expired trial renders the
  no-purchase-path state rather than an Upgrade form
- **quota consumed on `ready` and NOT consumed on `failed`**
- **idempotent visit creation: a replayed key returns the same visit and consumes one
  quota unit**
- **409 on a stale `notes.version` during section PATCH**
- **overnight shift duration (22:00–06:00) and a shift crossing a DST transition**
- pipeline tasks with fake providers, including a multi-speaker US transcript asserting
  no cross-speaker quote attribution, and a US template rejecting an undiarized
  transcript
- flag evaluation, and that `notes.flags` and `note_flags` never diverge
- analytics aggregation against a seeded fixture with known counts — **write that test
  first**
- multipart upload resume after a simulated part failure

**Web**: `tsc --noEmit` strict; Vitest + React Testing Library for guards, query hooks,
chart transforms, the recorder state machine, and **the repeating-group section
editor**; Playwright E2E for record → upload → processing → review → sign → PDF, in
both a US and a PH flow.

**Seed CLI** (`python -m app.cli seed-demo`): a US agency with staff and notes over
several weeks with a realistic flag distribution, **plus a PH ward nurse with FDAR
notes**, so every chart renders meaningfully and the public demo shows both markets.
At least one note per template triggers three or more flags including one critical.
Also seeds **three pending GCash payment submissions** — one with a receipt image, one
without, one carrying a duplicate reference number — so `/ops/payments` has a real
queue to approve, reject, and reject-for-duplication against. This same data backs the
public demo login.

The eval suite must pass on the active prompt versions before v1 is considered done;
zero fabrication failures.

---

## Roadmap (post-v1, documented in the README)

| Item | Why deferred |
|---|---|
| Expo mobile client with background recording | An entire second client; the web app already demonstrates the product end to end |
| PH Endorsement format | Multi-patient; a data model change, not a template change |
| OASIS assessments | A large, separately-regulated assessment instrument |
| A US purchase path | GCash is a Philippine wallet. US accounts are trial and demo in v1, and adding a second rail is a business decision that has not been made |

**Not on the roadmap at all**: Stripe, card processing, checkout SDKs, payment
webhooks. Manual GCash activation is the payment model. If that changes, it changes
because the manual loop was tested and found wanting — which is exactly what v1 is for.

---

## Out of Scope (do not build)

EHR integrations, meeting bots, real-time transcription, note-similarity clone
detection, multi-language, push notifications, offline note generation, app store
submission automation, iOS distribution.
