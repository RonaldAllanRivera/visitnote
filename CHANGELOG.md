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

### Fixed
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
