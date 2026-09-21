# Spec changelog

Why each change was made. Entries marked **ADR** should become an Architecture Decision Record in
`docs/adr/` once the repository exists — the reasoning is more valuable than the decision, and it is
the part you will be asked to defend in an interview.

---

## v8 → v9 — 2026-09-21

Review of v8 against a changed goal: the product now serves two markets, and the build
must reach a genuinely finished v1 rather than a broad half-finished one. v8's
architecture survives intact — every change below is a data dimension, a scope
decision, or a correction.

### The incoherence v9 resolves

**v8 was half-US and half-PH and never said so.** The SOAPIE template encoded CMS
home-health survey concepts — homebound status, skilled-necessity rationale,
plan-of-care linkage — while the payment rail was GCash and prices were in PHP. Those
two halves describe different customers. v9 makes jurisdiction explicit and assigns
each market a job: **PH is the revenue market, US is the portfolio and validation
market.** **ADR.**
*Rationale: a spec that is quietly about two countries produces a product that serves
neither. Naming which one pays resolves every downstream question — pricing, consent,
flag semantics, disclaimers.*

### Correctness

**`note_format` was a Postgres ENUM, and formats are now a growing set.** `ALTER TYPE
... ADD VALUE` cannot run inside a transaction block and values can never be removed.
Converted to `VARCHAR(32)` validated against `note_templates`, with `NoteFormat`
retained as a Python `StrEnum`. Done at six migrations with no production data, where
it is free. **ADR.**
*Rationale: an ENUM was the right type for a fixed pair and the wrong one for an
extensible set. The cost of this conversion only ever goes up.*

**Jurisdiction is a separate axis from format, and conflating them would have broken
the eval suite.** Filipino nurses also chart SOAPIE, but PH SOAPIE must not flag
homebound status. That is one format with two flag schemas, which `ph_soapie` as a
format value cannot express without making per-format eval reporting incoherent. Added
`note_templates.jurisdiction` and `users.jurisdiction`, re-keyed the unique constraint
to `(jurisdiction, format, version)`. **ADR.**

**Sampling parameters and assistant prefill are rejected by current models.**
`temperature`, `top_p`, `top_k` and assistant prefill all return 400 on the 4.6+
family. A clinical pipeline's instinct is `temperature=0` for determinism and a prefill
to force JSON — both would have failed at integration time. Determinism now comes from
structured outputs (`output_config.format`) plus `strict: true`. `budget_tokens` is
likewise rejected; use `thinking: {type: "adaptive"}` with `output_config.effort`.
*Rationale: this is the same failure class as v8's stale model IDs. Provider APIs move
faster than specifications, which is the entire argument for the provider layer.*

**`live_audio` is a criminal-law problem in the Philippines, not a UX preference.**
RA 4200 (Anti-Wiretapping) requires all-party consent with criminal liability, and a
ward holds twenty to forty patients, families, and staff. `live_audio` is now rejected
server-side for PH users, with a test. The PH product is a `spoken_recap` product.
**ADR.**
*Rationale: v8 treated capture mode as a consent-gate checkbox. In one jurisdiction it
is a prosecutable act, and a checkbox cannot obtain consent on a bystander's behalf.*

**A pseudonymous label never de-identified the audio, and now something enforces it.**
Added `PATIENT_IDENTIFIER_DETECTED` (critical) across all formats: a detected patient
name is stripped from the generated note and flagged. Sharper in PH, where an
individual staff nurse — not an agency under a data processing agreement — is the one
moving sensitive personal information off their employer's premises under RA 10173.

### Scope

**v1 is now defined, because the product will not be demoed until it is complete.**
That makes the definition of "complete" the most consequential decision in the spec.
The Expo mobile client and the PH Endorsement format move to a documented roadmap; the
dashboard is reduced to a review queue and three charts.
*Rationale: an unshipped project is worth nothing as either a product or a portfolio
piece. A roadmap that states what was deferred and why reads as scope discipline; the
same repository without that section reads as unfinished.*

**PH Endorsement is deferred for a structural reason, not a scheduling one.** An
endorsement covers a nurse's entire assignment — five to fifteen patients in one
document — while `visits` references one client and `notes` references one visit.
It is a data model change, not a template change. **ADR.**

**Manual GCash billing ships in full in v1, and Stripe is removed entirely.** v8
deferred a `StripeProvider` to a later phase and kept a `BillingProvider` seam for it.
v9 deletes both: the commercial hypothesis cannot be tested without collecting money
from a real customer, and a protocol with exactly one implementation is an abstraction
paying rent it does not earn. The decoupling that is load-bearing today is kept — the
entitlement engine cannot tell whether a subscription was activated by the ops console,
the staff CLI, or a trial. **ADR.**
*Rationale: this is the deliberate contrast with `LLMProvider` and
`TranscriptionProvider`, which do earn their protocols because the fake is a real
second implementation every test depends on. Knowing which seams to build is worth more
than building all of them.*

**US accounts have no purchase path in v1, and the UI says so.** GCash is a Philippine
wallet and there is no second rail. An expired US trial renders a no-purchase-path
state rather than an Upgrade form that cannot complete.

### Additions

**PH FDAR is the primary PH format, and it needs a repeating section group.** A shift
produces several F-D-A-R entries, one per focus — unlike every other format in the
product, which is a flat ordered list of sections. `section_schema` gains a `repeating`
section kind, and the Phase 5 editor must render it. Called out in the spec so it is
not discovered mid-phase. **ADR.**

**The two licensed RNs are eval authors, not beta testers.** Golden dataset cases
authored and validated by a licensed nurse in the relevant jurisdiction discharge the
clinical-review gate v8 already required before commercial launch, and `EVALS.md`
records who validated what.
*Rationale: clinical access is the scarcest resource on this project. Spending it on UI
feedback instead of on the golden dataset would waste it.*

**Per-note unit economics are now in the spec.** The PH tier leaves roughly ₱10 of room
per note against about ₱1.75 of cost. The margin is real but not large, which is why
per-note cost recording is a v1 requirement rather than an operator nicety.

---

## v7 → v8 — 2026-09-21

Review of v7 against two goals: a portfolio piece that survives senior-engineer scrutiny, and a
product that can lawfully take a real customer. v7's architecture was sound; these are correctness
defects, a resequencing, and a packaging layer.

### Correctness

**Model IDs were stale.** v7 pinned `claude-sonnet-4-6`. Corrected to `claude-sonnet-5`, and the
Deepgram model is now "verify at build time" rather than a copied string. Added a hard rule that no
model identifier appears in pipeline, service, or router code — config and `note_templates` only.
*Rationale: model lineups move faster than specifications. A spec that hardcodes a model ID is
already wrong by the time it is implemented, which is the entire argument for the provider layer.*

**Transcription had no diarization.** Both prompts require the patient's own words quoted; a home
visit has two to four speakers. Without speaker labels, attribution is a guess, and a
mis-attributed quote is a fabrication — the exact failure class the eval suite exists to catch.
Added: diarization on, transcripts persisted as ordered speaker turns, a new
`UNATTRIBUTED_STATEMENT` flag, a fabrication-checker rule for quote attribution, and three
multi-speaker golden dataset cases. **ADR.**
*Rationale: this was the one omission that could have made the eval suite pass while the product
was quietly wrong.*

**Flags were stored only as JSONB, but five dashboard views aggregate across them.** v7 promised
analytics "computed with SQL aggregation, never Python loops" while storing flags in
`notes.flags JSONB`. Those two statements cannot both hold at volume. Added a normalized
`note_flags` table written in the same transaction, with `notes.flags` retained as the note
payload. **ADR.**
*Rationale: one document, two access patterns. JSONB is correct for the note body — shape varies
per template, never queried into. It is wrong for flags, which are the analytics axis.*

**Timezones were absent.** The most severe flag in the product is a missing shift time. Added:
`TIMESTAMPTZ` everywhere, `visits.timezone` (IANA), rendering in the visit's zone, analytics
bucketed in the agency's zone, and required tests for a 22:00–06:00 overnight shift and a DST
crossing.
*Rationale: an overnight shift is the normal case in home care, not an edge case. Subtracting clock
times yields a negative duration and a spurious critical flag.*

**Quota was consumed on visit creation and never refunded on pipeline failure.** Rule now stated
once: quota is consumed when a note reaches `ready`. Added an `idempotency_key` on visit creation
so a retry over cellular cannot double-charge.
*Rationale: charging a user for work the system failed to deliver is both wrong and a support cost.*

**No concurrency control on note editing.** A supervisor in the review queue and the author on their
phone could both hold the same note. Added `notes.version` with a 409 on mismatch.
*Rationale: last-write-wins silently discards corrections to a document that is a legal record and
will be signed.*

**Single presigned PUT for files up to 200MB.** Added R2 multipart upload with per-part retry and
resume for files over ~10MB.
*Rationale: field staff upload over cellular. A 90-minute recording failing at 95% of a single PUT
loses the visit.*

**Tracing redaction made traces near-worthless without saying so.** Redaction stays on by default;
v8 now enumerates exactly what *is* captured — prompt version, model, tokens, cost, per-span
latency, flag codes, schema outcome, repair retries, speaker count, confidence.
*Rationale: "we trace everything but redact everything" is not an observability story. Naming the
non-content signal is.*

**`max_jobs=2` had the wrong rationale.** v7 said audio jobs are memory-heavy; ffmpeg streams. The
real constraints are CPU contention with the API container and upstream provider concurrency limits.
*Rationale: a reviewer who knows ffmpeg reads the original sentence as a guess.*

### Infrastructure

**Langfuse default flipped from self-hosted to Cloud free tier.** Self-hosting is now the documented
optional path. **ADR.**
*Rationale: the self-hosted stack wants Postgres, ClickHouse, Redis and object storage. Running it
beside api/worker/redis/Caddy on an Always Free VM means an OOM takes down the product, not just the
tracing.*

**Named a paid hosting fallback and required it be tested once.** Oracle Always Free ARM capacity is
often unavailable and idle instances get reclaimed.
*Rationale: v7 asserted provider portability. v8 verifies it. A demo link that 404s during a job
application is a total loss, and the failure mode is silent until it matters.*

### Sequencing

**Web gets audio capture first via `MediaRecorder`; mobile moves to phase 10.** Scope is unchanged —
both clients still ship. **ADR.**
*Rationale: v7 produced nothing demoable until phase 9 of 9. v8 produces a working
record → transcribe → generate → review → sign → PDF path at phase 5, and every later phase adds to
something that already works. It also matches the stated portfolio target of FastAPI + React + Vite,
and a reviewer can open a URL instead of installing an APK.*

**Added phase 11: `StripeProvider` against the existing `BillingProvider` protocol.**
*Rationale: turns "I designed an abstraction" into "I swapped the implementation without touching
entitlements, gates, or UI." A seam that is never exercised is a claim; one that is exercised is
evidence.*

### Packaging

**Public demo login** (`POST /auth/demo`) into a read-only seeded agency, enforced server side via
`users.is_demo`, plus one permanent public sample share link.
*Rationale: nobody signs up to evaluate a portfolio project. The seed data already existed; only the
door was missing.*

**`EVALS.md`, generated by the eval runner**, with an honest note that 30 cases give wide confidence
intervals per flag code.
*Rationale: the highest-signal artifact in the repository, and stating the sample-size limitation is
itself a signal.*

**`ARCHITECTURE.md` + 6–8 ADRs, README reordered** to put AI Reliability above local setup.
*Rationale: reviewers do not scroll past setup instructions.*

### Commercial

**Two operating modes defined explicitly: Demo (free tier, fictional audio only) and Pilot (paid
tiers with executed BAAs).**
*Rationale: free tiers do not come with BAAs, and a missing BAA is a violation regardless of
encryption quality. v7 gestured at this in one README line; v8 makes the cost floor of going live
visible before it is discovered.*

**Stated that a pseudonymous client label does not de-identify audio.**
*Rationale: the recording carries the patient's voice, conditions, medications and household
details. The label reduces database exposure and nothing else. Implying otherwise is the kind of
claim that does not survive a compliance review.*

**Added CMIA and CCPA/CPRA for California customers.**
*Rationale: CMIA is stricter than HIPAA in places and carries a private right of action.*

**Positioned the wedge in the README**: the incumbents chase physicians and health systems, and EHR
vendors are bundling ambient AI. Non-medical home care shift notes for small agencies is what nobody
serious is chasing. **OASIS reframed** from an omission to a deliberate deferral with a stated
rationale.
*Rationale: "another AI scribe" and "a considered market choice" are the same product described two
ways, and only one of them survives the first question.*

### Tests added to the Quality Bar

Quota on `ready` / not on `failed`; idempotent visit replay; 409 on stale note version; overnight and
DST shift durations; multi-speaker attribution with no cross-speaker quoting; `notes.flags` and
`note_flags` never diverging; multipart upload resume; demo-user write rejection.
