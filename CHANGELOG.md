# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Until
`1.0.0` the public API surface may change between minor versions.

This file tracks the **software**. Changes to the build specification are recorded
separately in [`SPEC-CHANGELOG.md`](SPEC-CHANGELOG.md), which carries the reasoning
behind each design decision.

## [Unreleased]

### Added
- **Phase 4b — jurisdiction.** Built test-first, across nine tasks.
  - `jurisdiction` on users, visits, and note templates, defaulted from the user's
    IANA timezone at onboarding and copied onto each visit at creation so a later
    jurisdiction change cannot retroactively change which template a past visit
    resolves against.
  - `note_templates` re-keyed from `(format, version)` to
    `(jurisdiction, format, version)`, so the same format can carry two different
    flag schemas in two regimes. `note_format` moved off its Postgres ENUM onto
    `VARCHAR(32)` — the set of formats is now a growing one, and `ALTER TYPE ... ADD
    VALUE` cannot run inside a transaction.
  - Diarization requirement (`requires_diarization`) moved onto the template row: a
    US home visit has several speakers and a mis-attributed quote is a fabrication;
    a PH spoken recap is single-speaker under RA 4200, so diarizing it buys nothing.
  - A repeating-section shape in the template contract (`section_schema` entries can
    carry `repeating: true` plus a nested `fields` list), with per-entry validation
    in `app/llm/contract.py` — built for PH FDAR's one Focus-Data-Action-Response
    block per nursing focus, which a flattened prose section could not represent.
  - Two new prompt modules, `ph_soapie_v1` and `ph_fdar_v1`, each overriding
    `SHARED_RULES`' unattributed-statement instruction: PH capture is
    `spoken_recap` only, so the transcript is always single-speaker and the
    condition that flag guards against cannot occur.
  - `PATIENT_IDENTIFIER_DETECTED` (critical), on every template in every
    jurisdiction: a nurse speaking a patient's real name aloud is caught and
    stripped before it reaches a stored note, whatever the pseudonymous label
    scheme in use.
  - Seed migration `0011` adds the `(PH, soapie, 1)` and `(PH, fdar, 1)` template
    rows and backfills `PATIENT_IDENTIFIER_DETECTED` onto the two existing US rows.
  - `default_format_for(jurisdiction, role)` replaces the old role-only lookup —
    role alone cannot pick a format once jurisdiction is also an axis (a Manila
    ward RN charts FDAR, a US home-health RN charts SOAPIE) — and
    `AuthService.update_profile` reconciles a format stranded by a jurisdiction
    change, checked against `note_templates` rather than a hardcoded map so a future
    seeded format needs no code change to become valid.
  - **Timing.** Task 9 — seeding the PH rows and wiring jurisdiction-aware role
    defaults, the last task of the phase — took about 15 minutes wall-clock, start
    to finish. That is the direct evidence behind this phase's central claim: a
    third and fourth note format, across a second regulatory regime, arrived as
    seed data and two prompt modules rather than a pipeline rewrite.

- **Phase 4 — pipeline.** Built test-first.
  - Transcription and LLM providers behind Protocols, with fakes written before the
    live clients so the interfaces are shaped by what the pipeline needs rather than
    by an SDK's return type. No vendor type leaves either provider module.
  - Transcription returns ordered speaker turns, never a flat string. A response with
    no diarization is an error rather than a single unattributed blob: both note
    formats quote the patient, and mis-attributing a quote is a fabrication.
  - The speaker who both opens and dominates a recording is inferred as the
    caregiver, and only when the margin is clear. An ambiguous transcript is sent
    with an explicit instruction not to guess, because an unknown speaker costs one
    flag while a wrong one puts the patient's name on words they never said.
  - Versioned prompt modules with an explicit registry. A change is a new module, not
    an edit — every note records the prompt version that produced it, and that record
    is worthless if the version's text can move underneath it.
  - Output validated with Pydantic against the active template's own schema, and
    repaired once with an instruction naming the specific defect. A retry that repeats
    the original request unchanged is only a second chance at the same mistake.
  - Flag severity is taken from the template, not from the model. Banned phrases are
    rejected in the note's own voice but permitted inside quotations, because what the
    patient actually said is evidence.
  - One pipeline for both note formats: everything format-specific is read from the
    `note_templates` row, so a third format is a data change plus a prompt module.
  - `notes.flags` and the normalized `note_flags` rows are written in one transaction
    from the same validated objects, with a test that they cannot diverge.
  - Failures record the stage they failed at and whether they are worth retrying — a
    file that is not audio will not decode on the third attempt, while a provider
    timeout might. Exponential backoff, three attempts, then failed with the error on
    the job row rather than only in the worker's logs.
  - Per-note cost in Decimal: audio minutes, input and output tokens, computed USD. A
    model with no configured price records no cost rather than a misleading zero.
  - Tracing optional by config and a no-op when off, so no call site is conditional.
    Redaction removes patient content by denylist and keeps everything a regression
    looks like: prompt version, model, tokens, cost, per-stage latency, flag codes,
    schema validity, whether a repair was needed.
  - Status endpoint reporting the pipeline stage, `/ops/jobs` with a failure filter
    and retry, and a web screen that polls with backoff and stops at a terminal state.
  - Object storage now runs locally under MinIO. Presigning uses a separately
    configurable public endpoint, because a presigned URL is signed over the host it
    will be sent to and the browser and the API do not always reach a bucket by the
    same name.

- **Phase 3 — capture.** Built test-first.
  - Care recipient records: a pseudonymous label and nothing else. Deactivated rather
    than deleted, because visits reference them and a signed note is a legal record.
  - Tenant scoping applied in the repository rather than checked in handlers, so a new
    route cannot forget it. Another user's record reports 404, never 403.
  - Idempotent visit creation keyed per user, so a retry over a dropped connection
    resolves to the existing visit instead of consuming a second unit of quota.
  - Server-enforced consent gate: a live recording is refused without an
    acknowledgment, and the acknowledgment is written in the same transaction as the
    visit so a recording cannot exist without its record.
  - Visits carry the timezone they were captured in, so a user who later moves does
    not retro-date notes they have already written.
  - Object storage behind a Protocol with an in-memory fake, matching the LLM and
    transcription provider pattern. Presigned single PUT below 8MB, resumable
    multipart above it; bytes never pass through the API.
  - Web: a recorder state machine separate from `MediaRecorder`, a resumable uploader
    that retries individual parts and recovers from expired signatures, and a capture
    page with a consent step and upload progress.
- **Phase 2 — authentication.** Built test-first.
  - argon2id password hashing with rehash-on-login, so cost parameters can be raised
    without forcing a password reset.
  - Short-lived JWT access tokens carrying no authorisation claims: staff status is
    read from the database on every request, so revoking it takes effect immediately
    rather than when the token expires.
  - Rotating single-use refresh tokens stored as SHA-256 hashes and grouped into
    per-login families. Replaying a rotated token revokes the entire family; a token
    from an already-closed session is reported as unknown rather than as an attack.
  - Login throttling with a short, self-clearing lockout, applied to unknown
    addresses too so the endpoint cannot be used to enumerate accounts.
  - Google sign-in by ID token, verified against Google's published keys with
    audience and issuer pinned, behind a Protocol with a fake for tests. Links to an
    existing password account only when Google reports the address verified.
  - Onboarding that derives a default note format from the user's role and validates
    the IANA timezone at the edge.
  - `create-staff-user` CLI. Staff privilege is granted out of band only; no API
    route sets `is_staff`.
  - Web: access token held in memory, refresh token persisted and survivable across
    reloads, a single-flight refresh coordinator, and a fetch layer that recovers
    from an expired token without replaying a rotated one.

- **Phase 1 — monorepo scaffold.**
  - FastAPI service with a layered structure (`routers` → `services` → `repositories`),
    settings sourced entirely from the environment, structured JSON logging to stdout,
    and a `/healthz` endpoint that exercises both PostgreSQL and Redis rather than
    returning a static 200.
  - UTC time discipline: `TIMESTAMPTZ` throughout, a `UtcDateTime` column alias, helpers
    that reject naive datetimes, and ruff's `DTZ` rules enforcing it at lint time.
  - SQLAlchemy 2.0 declarative base with constraint naming conventions, UUID primary
    keys, and database-maintained timestamps.
  - Alembic with an async environment; `note_templates` schema plus a data migration
    seeding both note formats — Shift Note (9 sections, 10 flags) and SOAPIE
    (10 sections, 15 flags).
  - arq worker sharing the API image, with a `ping` job proving the queue round-trips.
  - Docker Compose for local development; migrations run as an explicit one-off step,
    never at container startup.
  - React 19 + Vite web client with React Router v7, TanStack Query, Zustand, and
    Tailwind v4, consuming API types generated from the OpenAPI schema.
  - CI running ruff, mypy strict, and pytest against real PostgreSQL and Redis, plus a
    step asserting migrations are reversible.
- Repository documentation: `README.md`, this changelog, and `.gitignore`.
- Build specification v8 and its decision log.

### Changed
- Google ID token verification uses PyJWT rather than `authlib.jose`, which is
  deprecated. `authlib` is no longer a dependency.

### Fixed
- Object storage selection falls back to the in-memory provider outside production
  when credentials are absent, and refuses to start in production without them. The
  test suite's fake had been hiding that the live endpoint returned 500 locally.
- `/healthz` now declares its 503 response in the OpenAPI schema. Without it the
  generated client typed the error branch as `never`, so a client written against
  those types could not handle a degraded API — the case the endpoint exists for.

<!--
Phase entries are appended here as they land. Each phase is a single commit and
adds one section below, oldest last.

Template:

## [0.1.0] — YYYY-MM-DD
### Added
### Changed
### Fixed
### Security
-->
