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
