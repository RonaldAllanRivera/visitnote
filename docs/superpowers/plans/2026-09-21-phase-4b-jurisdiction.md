# Phase 4b — Jurisdiction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make jurisdiction (`US` / `PH`) an explicit dimension of users, visits and note templates, so one pipeline serves four note formats across two regulatory regimes.

**Architecture:** Five additive Alembic migrations (`0007`–`0011`) plus the model, repository and service changes they enable. Template resolution moves from `format` to `(jurisdiction, format)`. `note_format` converts from a Postgres ENUM to a validated `VARCHAR(32)` because formats are now a growing set. Nothing in the pipeline, the providers, or the prompt contract changes shape — this phase adds a dimension, it does not restructure a layer.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0 (async, `Mapped[]` style), Alembic, Pydantic v2, pytest + pytest-asyncio (auto mode) + httpx `AsyncClient`, real PostgreSQL.

**Spec:** [`visitnote-claude-code-prompt-v9.md`](../../../visitnote-claude-code-prompt-v9.md) — read the **Jurisdiction Model**, **Core Capture Flow**, **Note Formats** and **Data Model** sections before starting.

## Global Constraints

- **No model identifier string appears in pipeline, service, or router code.** Provider and model come from `app/core/config.py` defaults, overridden per template by `note_templates.llm_provider` / `note_templates.model_id`. Seed migrations use the `DEFAULT_PROVIDER` / `DEFAULT_MODEL_ID` constants already defined in `0002_seed_note_templates.py` (`"anthropic"` / `"claude-sonnet-5"`).
- **Jurisdiction is `VARCHAR(2)` with a check constraint, never a Postgres ENUM.** The set grows; that is the same reason `note_format` is leaving its ENUM in Task 2.
- **Map every non-native enum column with `Enum(..., native_enum=False, create_constraint=False, length=N)`, never bare `String(N)`.** A bare `String` column typed `Mapped[SomeEnum]` stores fine but loads back as a plain `str`, so `value is SomeEnum.MEMBER` silently fails while `==` still passes — the worst kind of bug, because the obvious assertion is the one that breaks. `native_enum=False` emits `VARCHAR` and keeps SQLAlchemy's coercion in both directions; `create_constraint=False` keeps the value set open, so a fifth format is an INSERT. Where a database-level check is wanted anyway (both jurisdiction columns), the migration owns the constraint and the model owns the coercion.
- **Routers do HTTP and nothing else.** Business rules live in services, queries in repositories. A router never touches a database session directly.
- **TDD, strictly.** Write the failing test, run it and see it fail for the stated reason, write the minimal implementation, see it pass, commit. A test that passes the first time you run it is not yet testing anything.
- **`ruff` and `mypy --strict` must pass** before every commit: `ruff check . && ruff format --check . && mypy app`.
- **Tests run against real PostgreSQL.** Bring the database up with `docker compose up -d postgres redis` from the repo root before running the suite.
- **Every prompt version is an immutable module.** A change is a new module and a new registry entry, never an edit to an existing one.
- Run migrations with `alembic upgrade head` from `backend/`. Every migration in this plan must have a working `downgrade()`.

---

### Task 1: Jurisdiction on users

**Files:**
- Modify: `backend/app/models/enums.py`
- Create: `backend/app/core/jurisdiction.py`
- Modify: `backend/app/models/user.py`
- Create: `backend/alembic/versions/0007_users_jurisdiction.py`
- Modify: `backend/app/schemas/auth.py` (`OnboardingRequest`, `UserProfile`)
- Modify: `backend/app/services/auth.py` (`AuthService.update_profile`)
- Test: `backend/tests/test_jurisdiction.py` (create), `backend/tests/test_onboarding.py` (extend)

**Interfaces:**
- Consumes: nothing — this is the first task.
- Produces: `Jurisdiction` StrEnum with members `US = "US"` and `PH = "PH"`; `jurisdiction_for_timezone(timezone: str) -> Jurisdiction`; `User.jurisdiction: Mapped[Jurisdiction]` (non-null, defaults to `US`); `OnboardingRequest.jurisdiction: Jurisdiction | None`; `UserProfile.jurisdiction: Jurisdiction`.

- [ ] **Step 1: Write the failing test for timezone-derived jurisdiction**

Create `backend/tests/test_jurisdiction.py`:

```python
"""Jurisdiction derivation.

A user should not have to answer a question the system can already infer. The zone
they capture in is the strongest available signal, and onboarding already asks for it.
"""

import pytest

from app.core.jurisdiction import jurisdiction_for_timezone
from app.models.enums import Jurisdiction


@pytest.mark.parametrize(
    ("timezone", "expected"),
    [
        ("Asia/Manila", Jurisdiction.PH),
        ("America/Los_Angeles", Jurisdiction.US),
        ("America/New_York", Jurisdiction.US),
        ("UTC", Jurisdiction.US),
        ("Europe/London", Jurisdiction.US),
    ],
)
def test_jurisdiction_is_derived_from_the_capture_timezone(
    timezone: str, expected: Jurisdiction
) -> None:
    assert jurisdiction_for_timezone(timezone) is expected


def test_an_unrecognised_zone_falls_back_to_us_rather_than_raising() -> None:
    """Onboarding must never fail closed on a zone we have not mapped.

    US is the safe default: it permits both capture modes, so the fallback never
    silently grants a PH user a capability RA 4200 forbids.
    """
    assert jurisdiction_for_timezone("Mars/Olympus_Mons") is Jurisdiction.US
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_jurisdiction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.jurisdiction'`

- [ ] **Step 3: Add the enum and the derivation**

Append to `backend/app/models/enums.py`:

```python
class Jurisdiction(StrEnum):
    """Which regulatory regime a user, visit, and note template belong to.

    Stored as CHAR(2) with a check constraint rather than a Postgres ENUM, because
    the set grows and ALTER TYPE cannot run inside a transaction block.
    """

    US = "US"
    PH = "PH"
```

Create `backend/app/core/jurisdiction.py`:

```python
"""Deriving a jurisdiction from the zone a user captures in.

Kept as a pure function with no session and no settings, so onboarding, the seed CLI,
and the eval fixtures all reach the same answer for the same input.
"""

from app.models.enums import Jurisdiction

# Explicit rather than a prefix match on "Asia/". The product operates in exactly two
# jurisdictions, and a nurse in Asia/Singapore is not a Philippine nurse.
_PH_ZONES: frozenset[str] = frozenset({"Asia/Manila"})


def jurisdiction_for_timezone(timezone: str) -> Jurisdiction:
    """The jurisdiction implied by an IANA zone, defaulting to US.

    US is the fallback because it is the permissive regime: it allows both capture
    modes. Defaulting an unmapped zone to PH would silently restrict a user; defaulting
    to US never grants a PH user a capability RA 4200 forbids, because PH is only ever
    reached by an explicit match or an explicit choice.
    """
    return Jurisdiction.PH if timezone in _PH_ZONES else Jurisdiction.US
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_jurisdiction.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Write the failing test for the column and the onboarding round-trip**

Append to `backend/tests/test_onboarding.py`:

```python
async def test_onboarding_derives_jurisdiction_from_the_timezone(
    client: AsyncClient,
) -> None:
    headers = await _account(client)
    body = (
        await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"role_title": "rn", "timezone": "Asia/Manila"},
        )
    ).json()
    assert body["jurisdiction"] == "PH"


async def test_an_explicit_jurisdiction_overrides_the_derived_one(
    client: AsyncClient,
) -> None:
    """A Filipino nurse working a US telehealth contract is a real case.

    The derivation is a default, not a determination.
    """
    headers = await _account(client)
    body = (
        await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"timezone": "Asia/Manila", "jurisdiction": "US"},
        )
    ).json()
    assert body["jurisdiction"] == "US"


async def test_a_new_account_defaults_to_us_before_onboarding(client: AsyncClient) -> None:
    headers = await _account(client)
    body = (await client.get("/api/v1/auth/me", headers=headers)).json()
    assert body["jurisdiction"] == "US"
```

If `test_onboarding.py` has no `_account` helper, copy the one from `tests/test_visits.py` (register, then return the `Authorization` header) into this module rather than importing across test modules.

- [ ] **Step 6: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_onboarding.py -v -k jurisdiction`
Expected: FAIL — `KeyError: 'jurisdiction'`, because `UserProfile` has no such field.

- [ ] **Step 7: Add the column, the migration, and the onboarding wiring**

In `backend/app/models/user.py`, import `Jurisdiction` from `app.models.enums` and add, below `timezone`:

```python
    # Selects the note templates available, the capture modes permitted, the privacy
    # regime named in the UI, and the currency shown. Defaulted from the timezone at
    # onboarding and editable, because the derivation is a default, not a determination.
    jurisdiction: Mapped[Jurisdiction] = mapped_column(
        Enum(
            Jurisdiction,
            native_enum=False,
            create_constraint=False,
            length=2,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=Jurisdiction.US,
        server_default="US",
    )
```

Create `backend/alembic/versions/0007_users_jurisdiction.py`:

```python
"""Add jurisdiction to users.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-21

CHAR(2) with a check constraint rather than a Postgres ENUM. The set of jurisdictions
grows, and ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("jurisdiction", sa.String(length=2), nullable=False, server_default="US"),
    )
    op.create_check_constraint(
        "ck_users_jurisdiction", "users", "jurisdiction IN ('US', 'PH')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_jurisdiction", "users", type_="check")
    op.drop_column("users", "jurisdiction")
```

In `backend/app/schemas/auth.py`, import `Jurisdiction`, add `jurisdiction: Jurisdiction` to `UserProfile`, and add to `OnboardingRequest`:

```python
    jurisdiction: Jurisdiction | None = None
```

In `backend/app/services/auth.py`, import `jurisdiction_for_timezone`, and inside `update_profile` replace the timezone branch with:

```python
        if payload.timezone is not None:
            user.timezone = payload.timezone
            # Derive unless the user says otherwise, so onboarding asks one question
            # instead of two. The explicit field below still wins.
            if payload.jurisdiction is None:
                user.jurisdiction = jurisdiction_for_timezone(payload.timezone)
        if payload.jurisdiction is not None:
            user.jurisdiction = payload.jurisdiction
```

Place the `payload.jurisdiction is not None` branch **after** the timezone branch so an explicit value always wins, and assign fields by name — never by iterating the payload.

- [ ] **Step 8: Run the migration and the tests**

Run:
```bash
cd backend && alembic upgrade head && pytest tests/test_onboarding.py tests/test_jurisdiction.py -v
```
Expected: PASS

- [ ] **Step 9: Lint, type-check, and commit**

```bash
cd backend && ruff check . && ruff format --check . && mypy app
git add backend/app/models/enums.py backend/app/core/jurisdiction.py backend/app/models/user.py backend/alembic/versions/0007_users_jurisdiction.py backend/app/schemas/auth.py backend/app/services/auth.py backend/tests/test_jurisdiction.py backend/tests/test_onboarding.py
git commit -m "feat: jurisdiction on users, derived from the capture timezone"
```

---

### Task 2: Move `note_format` off the Postgres ENUM

**Files:**
- Create: `backend/alembic/versions/0008_note_format_varchar.py`
- Modify: `backend/app/models/note_template.py`, `backend/app/models/user.py`, `backend/app/models/visit.py`
- Test: `backend/tests/test_note_templates.py` (extend)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `note_templates.format`, `users.default_note_format` and `visits.note_format` are `VARCHAR(32)`; the `note_format` Postgres type no longer exists. `NoteFormat` remains the Python `StrEnum` and all three columns stay typed `Mapped[NoteFormat]`.

**Why:** an ENUM was the right type for a fixed pair. Formats are now a growing set, `ALTER TYPE ... ADD VALUE` cannot run inside a transaction block, and values can never be removed. There are six migrations and no production data, so this conversion is free now and expensive later.

**Watch out:** three columns reference the type, not two. Dropping it while `visits.note_format` still points at it fails.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_note_templates.py`:

```python
async def test_a_new_format_value_needs_no_type_alteration(session: AsyncSession) -> None:
    """The point of leaving the ENUM: a fourth format is an INSERT, not a DDL change.

    This inserts a format string no Python enum member covers. Under the old
    Postgres ENUM it raised InvalidTextRepresentation.
    """
    await session.execute(
        sa.text(
            """
            INSERT INTO note_templates (
                format, version, name, section_schema, flag_schema,
                prompt_version, llm_provider, model_id, is_active
            ) VALUES (
                'a_format_from_the_future', 1, 'Future', '{"sections": []}'::jsonb,
                '{"flags": []}'::jsonb, 'future_v1', 'anthropic', 'test-model', false
            )
            """
        )
    )
    await session.commit()

    stored = (
        await session.execute(
            sa.text(
                "SELECT format FROM note_templates WHERE prompt_version = 'future_v1'"
            )
        )
    ).scalar_one()
    assert stored == "a_format_from_the_future"

    await session.execute(
        sa.text("DELETE FROM note_templates WHERE prompt_version = 'future_v1'")
    )
    await session.commit()


async def test_the_note_format_enum_type_is_gone(session: AsyncSession) -> None:
    exists = (
        await session.execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'note_format')")
        )
    ).scalar_one()
    assert exists is False
```

Add `import sqlalchemy as sa` and `from sqlalchemy.ext.asyncio import AsyncSession` to the module imports if absent.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_note_templates.py -v -k "future or enum_type"`
Expected: FAIL — `InvalidTextRepresentation: invalid input value for enum note_format`, and the second assertion fails because the type still exists.

- [ ] **Step 3: Write the migration**

Create `backend/alembic/versions/0008_note_format_varchar.py`:

```python
"""Move note_format off the Postgres ENUM.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-21

An ENUM was the right type when formats were a fixed pair. They are now a growing,
data-driven set: ALTER TYPE ... ADD VALUE cannot run inside a transaction block, and a
value can never be removed. Three columns reference the type and all three must be
converted before it can be dropped.

Validity is enforced by note_templates -- a format with no template row cannot be
generated -- rather than by the column type.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, nullable)
_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("note_templates", "format", False),
    ("users", "default_note_format", True),
    ("visits", "note_format", False),
)


def upgrade() -> None:
    for table, column, nullable in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.String(length=32),
            existing_type=postgresql.ENUM("shift_note", "soapie", name="note_format"),
            existing_nullable=nullable,
            postgresql_using=f"{column}::text",
        )
    sa.Enum(name="note_format").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    """Recreate the type and convert back.

    Fails if any row holds a format outside the original pair, which is correct: the
    data would not fit the type being restored.
    """
    note_format = postgresql.ENUM("shift_note", "soapie", name="note_format")
    note_format.create(op.get_bind(), checkfirst=True)
    for table, column, nullable in _COLUMNS:
        op.alter_column(
            table,
            column,
            type_=note_format,
            existing_type=sa.String(length=32),
            existing_nullable=nullable,
            postgresql_using=f"{column}::note_format",
        )
```

- [ ] **Step 4: Update the three models**

In `backend/app/models/note_template.py`, drop the `Enum` import and replace the `format` column with:

```python
    # VARCHAR rather than a Postgres ENUM: formats are a growing set, and a format's
    # validity is established by having a row in this table -- not by the column type.
    format: Mapped[NoteFormat] = mapped_column(
        _format_column(), nullable=False, index=True
    )
```

In `backend/app/models/user.py`, replace `default_note_format` with:

```python
    default_note_format: Mapped[NoteFormat | None] = mapped_column(
        _format_column(), nullable=True
    )
```

In `backend/app/models/visit.py`, replace `note_format` with:

```python
    note_format: Mapped[NoteFormat] = mapped_column(_format_column(), nullable=False)
```

Define `_format_column()` once, in `backend/app/models/enums.py`, and import it into all three models:

```python
def note_format_column() -> Enum:
    """NoteFormat as a VARCHAR that still round-trips to the Python enum.

    `native_enum=False` emits VARCHAR instead of a Postgres ENUM; `create_constraint=False`
    leaves the value set open, because a format's validity is established by having a row
    in `note_templates`, not by the column type. Without this, a bare String column typed
    `Mapped[NoteFormat]` loads back as `str` and every `is` comparison silently fails.
    """
    from sqlalchemy import Enum

    return Enum(
        NoteFormat,
        native_enum=False,
        create_constraint=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )
```

Import it as `from app.models.enums import note_format_column as _format_column` in each model module.

Leave `capture_mode`, `status`, `role_title` and every other ENUM alone — those sets are genuinely closed.

- [ ] **Step 5: Run the migration and the full suite**

Run:
```bash
cd backend && alembic upgrade head && pytest -q
```
Expected: PASS. The whole suite runs because this migration touches three tables that most tests exercise.

- [ ] **Step 6: Verify the downgrade works**

Run:
```bash
cd backend && alembic downgrade 0007 && alembic upgrade head
```
Expected: both succeed with no error. A migration whose downgrade has never been run is a migration you cannot roll back.

- [ ] **Step 7: Lint, type-check, and commit**

```bash
cd backend && ruff check . && ruff format --check . && mypy app
git add backend/alembic/versions/0008_note_format_varchar.py backend/app/models/note_template.py backend/app/models/user.py backend/app/models/visit.py backend/tests/test_note_templates.py
git commit -m "refactor: note_format leaves the Postgres ENUM, formats are a growing set"
```

---

### Task 3: Jurisdiction and diarization on note templates

**Files:**
- Create: `backend/alembic/versions/0009_note_templates_jurisdiction.py`
- Modify: `backend/app/models/note_template.py`
- Test: `backend/tests/test_note_templates.py` (extend)

**Interfaces:**
- Consumes: `Jurisdiction` from Task 1; `VARCHAR` format column from Task 2.
- Produces: `NoteTemplate.jurisdiction: Mapped[Jurisdiction]`, `NoteTemplate.requires_diarization: Mapped[bool]`; unique constraint on `(jurisdiction, format, version)`; index on `(jurisdiction, format)`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_note_templates.py`:

```python
async def test_the_same_format_can_exist_in_two_jurisdictions(
    session: AsyncSession,
) -> None:
    """The constraint that makes PH SOAPIE possible.

    Filipino nurses chart SOAPIE too, but PH SOAPIE must not flag homebound status.
    Same format, different flag schema, two rows -- which the old (format, version)
    unique constraint forbade.
    """
    template = NoteTemplate(
        jurisdiction=Jurisdiction.PH,
        format=NoteFormat.SOAPIE,
        version=1,
        name="PH Skilled Nursing Note",
        section_schema={"sections": []},
        flag_schema={"flags": []},
        requires_diarization=False,
        prompt_version="ph_soapie_v1",
        llm_provider="anthropic",
        model_id="test-model",
        is_active=False,
    )
    session.add(template)
    await session.commit()

    both = (
        await session.execute(
            select(NoteTemplate).where(NoteTemplate.format == NoteFormat.SOAPIE)
        )
    ).scalars().all()
    assert {t.jurisdiction for t in both} == {Jurisdiction.US, Jurisdiction.PH}

    await session.delete(template)
    await session.commit()


async def test_us_templates_require_diarization_and_ph_templates_do_not(
    session: AsyncSession,
) -> None:
    """Diarization is a property of the template, not of the pipeline.

    A US home visit has two to four speakers and a mis-attributed quote is a
    fabrication. A PH spoken recap has one speaker, so paying for diarization on a
    monologue buys nothing.
    """
    us_soapie = (
        await session.execute(
            select(NoteTemplate).where(
                NoteTemplate.jurisdiction == Jurisdiction.US,
                NoteTemplate.format == NoteFormat.SOAPIE,
            )
        )
    ).scalar_one()
    assert us_soapie.requires_diarization is True
```

Import `NoteTemplate`, `Jurisdiction`, `NoteFormat` and `select` at the top of the module if absent.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_note_templates.py -v -k "two_jurisdictions or diarization"`
Expected: FAIL — `TypeError: 'jurisdiction' is an invalid keyword argument for NoteTemplate`

- [ ] **Step 3: Write the migration**

Create `backend/alembic/versions/0009_note_templates_jurisdiction.py`:

```python
"""Add jurisdiction and diarization to note templates.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-21

Jurisdiction is a separate axis from format. Filipino nurses also chart SOAPIE, but PH
SOAPIE must not flag homebound status -- that is one format with two flag schemas,
which (format, version) could not express.

Diarization moves onto the row because it is a property of the note being produced: a
US home visit has several speakers, a PH spoken recap has one.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default backfills the two existing US rows, then is dropped so the
    # application must state a jurisdiction explicitly on every insert.
    op.add_column(
        "note_templates",
        sa.Column("jurisdiction", sa.String(length=2), nullable=False, server_default="US"),
    )
    op.add_column(
        "note_templates",
        sa.Column(
            "requires_diarization", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.create_check_constraint(
        "ck_note_templates_jurisdiction", "note_templates", "jurisdiction IN ('US', 'PH')"
    )
    op.alter_column("note_templates", "jurisdiction", server_default=None)
    op.alter_column("note_templates", "requires_diarization", server_default=None)

    op.drop_constraint(
        "uq_note_templates_format_version", "note_templates", type_="unique"
    )
    op.create_unique_constraint(
        "uq_note_templates_jurisdiction_format_version",
        "note_templates",
        ["jurisdiction", "format", "version"],
    )
    op.drop_index("ix_note_templates_format", table_name="note_templates")
    op.create_index(
        "ix_note_templates_jurisdiction_format",
        "note_templates",
        ["jurisdiction", "format"],
    )


def downgrade() -> None:
    op.drop_index("ix_note_templates_jurisdiction_format", table_name="note_templates")
    op.create_index("ix_note_templates_format", "note_templates", ["format"])
    op.drop_constraint(
        "uq_note_templates_jurisdiction_format_version", "note_templates", type_="unique"
    )
    op.create_unique_constraint(
        "uq_note_templates_format_version", "note_templates", ["format", "version"]
    )
    op.drop_constraint("ck_note_templates_jurisdiction", "note_templates", type_="check")
    op.drop_column("note_templates", "requires_diarization")
    op.drop_column("note_templates", "jurisdiction")
```

Before writing this, confirm the existing constraint and index names:
```bash
cd backend && grep -n "UniqueConstraint\|create_index" alembic/versions/0001_note_templates.py
```
Use whatever names that file actually created.

- [ ] **Step 4: Update the model**

In `backend/app/models/note_template.py`, import `Jurisdiction`, and replace `__table_args__` and add the two columns:

```python
    __table_args__ = (
        UniqueConstraint(
            "jurisdiction", "format", "version", name="jurisdiction_format_version"
        ),
        Index("ix_note_templates_jurisdiction_format", "jurisdiction", "format"),
    )

    # A separate axis from format: the same format carries different flag schemas in
    # different regimes. PH SOAPIE is SOAPIE without the CMS survey requirements.
    jurisdiction: Mapped[Jurisdiction] = mapped_column(
        jurisdiction_column(), nullable=False
    )
```

and, below `flag_schema`:

```python
    # A US home visit has two to four speakers and a mis-attributed quote is a
    # fabrication. A PH spoken recap has one speaker; diarizing a monologue is spend
    # with no buyer.
    requires_diarization: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

Remove the now-unused `index=True` from the `format` column, and add `Index` to the `sqlalchemy` import.

- [ ] **Step 5: Run the migration and the tests**

Run:
```bash
cd backend && alembic upgrade head && pytest tests/test_note_templates.py -v
```
Expected: PASS

- [ ] **Step 6: Verify the downgrade**

Run: `cd backend && alembic downgrade 0008 && alembic upgrade head`
Expected: both succeed.

- [ ] **Step 7: Lint, type-check, and commit**

```bash
cd backend && ruff check . && ruff format --check . && mypy app
git add backend/alembic/versions/0009_note_templates_jurisdiction.py backend/app/models/note_template.py backend/tests/test_note_templates.py
git commit -m "feat: jurisdiction and diarization requirement on note templates"
```

---

### Task 4: Jurisdiction on visits

**Files:**
- Create: `backend/alembic/versions/0010_visits_jurisdiction.py`
- Modify: `backend/app/models/visit.py`, `backend/app/services/visits.py`, `backend/app/schemas/visit.py`
- Test: `backend/tests/test_visits.py` (extend)

**Interfaces:**
- Consumes: `Jurisdiction` from Task 1.
- Produces: `Visit.jurisdiction: Mapped[Jurisdiction]`, set from `user.jurisdiction` at creation; exposed on `VisitRead`.

**Why:** [`app/models/visit.py`](../../../backend/app/models/visit.py) already copies `timezone` onto the visit with the comment "a user who later moves must not retro-date their old notes." Jurisdiction has the identical property. If it lived only on `users`, a nurse who switched jurisdiction would change which template resolves for visits captured before the switch — silently regenerating old work under new rules.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_visits.py`:

```python
async def test_a_visit_carries_the_jurisdiction_it_was_captured_under(
    client: AsyncClient,
) -> None:
    headers = await _account(client, timezone="Asia/Manila")
    visit = await _create(client, headers, _payload(await _client_record(client, headers)))
    assert visit["jurisdiction"] == "PH"


async def test_changing_jurisdiction_does_not_rewrite_existing_visits(
    client: AsyncClient,
) -> None:
    """The same argument the row already makes for timezone.

    A nurse who moves must not have the notes she already captured re-resolved against
    a different jurisdiction's template.
    """
    headers = await _account(client, timezone="Asia/Manila")
    visit = await _create(client, headers, _payload(await _client_record(client, headers)))

    await client.patch("/api/v1/auth/me", headers=headers, json={"jurisdiction": "US"})

    unchanged = (
        await client.get(f"/api/v1/visits/{visit['id']}", headers=headers)
    ).json()
    assert unchanged["jurisdiction"] == "PH"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_visits.py -v -k jurisdiction`
Expected: FAIL — `KeyError: 'jurisdiction'`

- [ ] **Step 3: Write the migration**

Create `backend/alembic/versions/0010_visits_jurisdiction.py`:

```python
"""Add jurisdiction to visits.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-21

Copied from the user at creation for the same reason visits.timezone already is: a
user who changes jurisdiction must not change which template resolves for the visits
they captured before the change.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "visits",
        sa.Column("jurisdiction", sa.String(length=2), nullable=False, server_default="US"),
    )
    op.create_check_constraint(
        "ck_visits_jurisdiction", "visits", "jurisdiction IN ('US', 'PH')"
    )
    # Dropped so the service must state it. A server default here would let a missing
    # assignment pass silently as "US".
    op.alter_column("visits", "jurisdiction", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_visits_jurisdiction", "visits", type_="check")
    op.drop_column("visits", "jurisdiction")
```

- [ ] **Step 4: Update the model, service, and schema**

In `backend/app/models/visit.py`, import `Jurisdiction` and add below `client_id`:

```python
    # Copied from the user at creation, not read from them later -- the same argument
    # as `timezone` below. Changing your jurisdiction must not re-resolve the template
    # for work you already captured.
    jurisdiction: Mapped[Jurisdiction] = mapped_column(
        jurisdiction_column(), nullable=False
    )
```

Add a `jurisdiction_column()` helper to `backend/app/models/enums.py` alongside `note_format_column()` from Task 2, with `length=2`, and use it in `users`, `note_templates` and `visits` alike.

In `backend/app/services/visits.py`, inside the `Visit(...)` constructor in `create`, add:

```python
                jurisdiction=user.jurisdiction,
```

In `backend/app/schemas/visit.py`, import `Jurisdiction` and add `jurisdiction: Jurisdiction` to `VisitRead`, directly after `client_id`.

- [ ] **Step 5: Run the migration and the tests**

Run:
```bash
cd backend && alembic upgrade head && pytest tests/test_visits.py -v
```
Expected: PASS

- [ ] **Step 6: Lint, type-check, and commit**

```bash
cd backend && ruff check . && ruff format --check . && mypy app
git add backend/alembic/versions/0010_visits_jurisdiction.py backend/app/models/visit.py backend/app/services/visits.py backend/app/schemas/visit.py backend/tests/test_visits.py
git commit -m "feat: visits carry the jurisdiction they were captured under"
```

---

### Task 5: Jurisdiction-aware template resolution

**Files:**
- Modify: `backend/app/repositories/note_templates.py`
- Modify: `backend/app/llm/templates.py` (`TemplateSpec`)
- Modify: `backend/app/llm/pipeline.py:171`
- Test: `backend/tests/test_note_templates.py`, `backend/tests/test_llm_templates.py` (extend)

**Interfaces:**
- Consumes: `NoteTemplate.jurisdiction` (Task 3), `Visit.jurisdiction` (Task 4).
- Produces: `NoteTemplateRepository.get_active(jurisdiction: Jurisdiction, note_format: NoteFormat) -> NoteTemplate | None` — **note the changed signature, jurisdiction first**; `TemplateSpec.jurisdiction: Jurisdiction` and `TemplateSpec.requires_diarization: bool`; `TemplateSpec.from_schemas(..., jurisdiction=..., requires_diarization=...)`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_note_templates.py`:

```python
async def test_resolution_is_scoped_to_the_jurisdiction(session: AsyncSession) -> None:
    """The whole point of the dimension: same format, different row.

    Seeded PH templates arrive in Task 8; this asserts the US side resolves correctly
    and that asking for a jurisdiction with no row returns None rather than another
    jurisdiction's template.
    """
    repository = NoteTemplateRepository(session)

    us = await repository.get_active(Jurisdiction.US, NoteFormat.SHIFT_NOTE)
    assert us is not None
    assert us.jurisdiction is Jurisdiction.US

    # shift_note is a US home-care format; PH has no row for it.
    assert await repository.get_active(Jurisdiction.PH, NoteFormat.SHIFT_NOTE) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_note_templates.py -v -k scoped_to_the_jurisdiction`
Expected: FAIL — `TypeError: get_active() takes 2 positional arguments but 3 were given`

- [ ] **Step 3: Update the repository**

In `backend/app/repositories/note_templates.py`, import `Jurisdiction` and replace `get_active`:

```python
    async def get_active(
        self, jurisdiction: Jurisdiction, note_format: NoteFormat
    ) -> NoteTemplate | None:
        """The active template for a jurisdiction and format, newest version first.

        Jurisdiction leads because it is the coarser filter and because it matches the
        index. Ordered by version rather than filtered to one, so promoting a new
        template version is inserting a row and deactivating the old one -- never an
        update that rewrites what already-generated notes were produced from.
        """
        return (
            await self.session.execute(
                select(NoteTemplate)
                .where(
                    NoteTemplate.jurisdiction == jurisdiction,
                    NoteTemplate.format == note_format,
                    NoteTemplate.is_active.is_(True),
                )
                .order_by(NoteTemplate.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
```

Also update `all_active` to order by `NoteTemplate.jurisdiction, NoteTemplate.format, NoteTemplate.version.desc()`.

- [ ] **Step 4: Carry jurisdiction into `TemplateSpec`**

In `backend/app/llm/templates.py`, import `Jurisdiction`, add two fields to the frozen dataclass immediately above `format`:

```python
    jurisdiction: Jurisdiction
```

and after `name`:

```python
    requires_diarization: bool
```

Thread both through `from_template` (reading `template.jurisdiction` and `template.requires_diarization`) and add them as keyword-only parameters on `from_schemas`. Every existing caller of `from_schemas` in the tests must be updated — find them with:

```bash
cd backend && grep -rn "from_schemas" app/ tests/
```

- [ ] **Step 5: Update the pipeline call site**

In `backend/app/llm/pipeline.py`, line 171 currently reads:

```python
        template = await NoteTemplateRepository(self.session).get_active(visit.note_format)
```

Replace with:

```python
        template = await NoteTemplateRepository(self.session).get_active(
            visit.jurisdiction, visit.note_format
        )
```

Read the visit's jurisdiction, never the user's — the visit is the historical fact.

- [ ] **Step 6: Run the tests**

Run: `cd backend && pytest tests/test_note_templates.py tests/test_llm_templates.py tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 7: Run the full suite, lint, type-check, and commit**

```bash
cd backend && pytest -q && ruff check . && ruff format --check . && mypy app
git add backend/app/repositories/note_templates.py backend/app/llm/templates.py backend/app/llm/pipeline.py backend/tests/test_note_templates.py backend/tests/test_llm_templates.py
git commit -m "feat: resolve note templates by (jurisdiction, format)"
```

---

### Task 6: Reject `live_audio` for PH users

**Files:**
- Modify: `backend/app/services/visits.py`
- Modify: `backend/app/api/v1/routers/visits.py`
- Test: `backend/tests/test_visits.py` (extend)

**Interfaces:**
- Consumes: `Visit.jurisdiction` (Task 4).
- Produces: `ProhibitedCaptureModeError` in `app/services/visits.py`, mapped to **HTTP 422** by the visits router.

**Why:** the Philippine Anti-Wiretapping Act (RA 4200) requires the consent of *all* parties to record a private communication, with criminal liability. A ward holds twenty to forty patients, their families, and other staff — consent from all parties is not obtainable, and a checkbox does not obtain it on a bystander's behalf.

**This must be a server-side rejection, not a hidden UI control.** Hiding the button is not a control; the existing `_live_audio_requires_consent` validator in `app/schemas/visit.py` makes the same argument.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_visits.py`:

```python
async def test_a_ph_user_cannot_open_a_live_recording(client: AsyncClient) -> None:
    """RA 4200 requires all-party consent, with criminal liability.

    A ward holds twenty to forty patients, their families, and other staff. Consent
    from all parties is not obtainable, and a checkbox does not obtain it on a
    bystander's behalf. Rejected by the API, not hidden in the UI.
    """
    headers = await _account(client, timezone="Asia/Manila")
    response = await client.post(
        "/api/v1/visits",
        headers=headers,
        json=_payload(
            await _client_record(client, headers),
            capture_mode="live_audio",
            consent_acknowledged=True,
        ),
    )
    assert response.status_code == 422
    assert "RA 4200" in response.json()["detail"]


async def test_a_ph_user_can_still_dictate_a_spoken_recap(client: AsyncClient) -> None:
    """The PH product is a spoken-recap product, and that path stays open."""
    headers = await _account(client, timezone="Asia/Manila")
    visit = await _create(client, headers, _payload(await _client_record(client, headers)))
    assert visit["capture_mode"] == "spoken_recap"


async def test_a_us_user_may_still_open_a_live_recording(client: AsyncClient) -> None:
    headers = await _account(client, timezone="America/Los_Angeles")
    visit = await _create(
        client,
        headers,
        _payload(
            await _client_record(client, headers),
            capture_mode="live_audio",
            consent_acknowledged=True,
        ),
    )
    assert visit["capture_mode"] == "live_audio"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_visits.py -v -k "live_recording or spoken_recap"`
Expected: FAIL — the PH case returns 201 instead of 422.

- [ ] **Step 3: Add the rule to the service**

In `backend/app/services/visits.py`, import `CaptureMode` and `Jurisdiction`, and add above `VisitService`:

```python
# Jurisdictions in which recording a third party is not lawfully obtainable, and the
# statute that says so. Data rather than a branch, so adding a jurisdiction is a row.
PROHIBITED_CAPTURE_MODES: dict[Jurisdiction, tuple[CaptureMode, str]] = {
    Jurisdiction.PH: (
        CaptureMode.LIVE_AUDIO,
        "RA 4200 (Anti-Wiretapping Act) requires the consent of all parties to a "
        "private communication. Record a spoken recap instead.",
    ),
}


class ProhibitedCaptureModeError(Exception):
    """The capture mode is unlawful in this user's jurisdiction.

    Enforced here rather than in the schema, because the rule depends on the
    authenticated user and a Pydantic model validator cannot see them.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
```

Then, inside `create`, immediately after the idempotency-key lookup returns nothing and **before** the client lookup:

```python
        prohibited = PROHIBITED_CAPTURE_MODES.get(user.jurisdiction)
        if prohibited is not None and payload.capture_mode is prohibited[0]:
            raise ProhibitedCaptureModeError(prohibited[1])
```

Placing it after the idempotency check means a replayed key for an already-created visit still returns that visit rather than erroring — the check guards creation, not retrieval.

- [ ] **Step 4: Map the error in the router**

In `backend/app/api/v1/routers/visits.py`, import `ProhibitedCaptureModeError` and extend the `try` in `create_visit`:

```python
    try:
        visit, created = await VisitService(session).create(user, payload)
    except UnknownClientError as exc:
        raise _NOT_FOUND from exc
    except ProhibitedCaptureModeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.reason
        ) from exc
```

422 rather than 403: the request is well-formed and the user is authorised, but this field carries a value that is not processable for them — the same status the existing consent validator produces.

- [ ] **Step 5: Run the tests**

Run: `cd backend && pytest tests/test_visits.py -v`
Expected: PASS

- [ ] **Step 6: Lint, type-check, and commit**

```bash
cd backend && ruff check . && ruff format --check . && mypy app
git add backend/app/services/visits.py backend/app/api/v1/routers/visits.py backend/tests/test_visits.py
git commit -m "feat: reject live_audio for PH users under RA 4200"
```

---

### Task 7: Repeating section groups for FDAR

**Files:**
- Modify: `backend/app/llm/templates.py`
- Test: `backend/tests/test_llm_templates.py` (extend)

**Interfaces:**
- Consumes: `TemplateSpec` from Task 5.
- Produces: `SectionSpec.repeating: bool` and `SectionSpec.fields: tuple[SectionSpec, ...]` (empty for flat sections); `json_schema_for` emits a JSON Schema `array` of objects for a repeating section.

**Why:** FDAR is structurally unlike every other format here. A shift produces *several* F-D-A-R entries — one per focus. A patient with pain, a fever, and a scheduled dressing change generates three. Every other format is one flat ordered list of sections.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_llm_templates.py`:

```python
_FDAR_SECTIONS = {
    "sections": [
        {"key": "shift_details", "label": "Shift details", "order": 1, "description": "Unit, bed, shift."},
        {
            "key": "focus_entries",
            "label": "Focus entries",
            "order": 2,
            "description": "One entry per focus.",
            "repeating": True,
            "fields": [
                {"key": "focus", "label": "Focus", "order": 1, "description": "The problem."},
                {"key": "data", "label": "Data", "order": 2, "description": "Findings."},
                {"key": "action", "label": "Action", "order": 3, "description": "Interventions."},
                {"key": "response", "label": "Response", "order": 4, "description": "Patient response."},
            ],
        },
    ]
}


def test_a_repeating_section_parses_its_fields() -> None:
    spec = _spec(section_schema=_FDAR_SECTIONS)
    focus_entries = next(s for s in spec.sections if s.key == "focus_entries")
    assert focus_entries.repeating is True
    assert tuple(f.key for f in focus_entries.fields) == ("focus", "data", "action", "response")


def test_a_flat_section_has_no_fields_and_is_not_repeating() -> None:
    spec = _spec(section_schema=_FDAR_SECTIONS)
    shift_details = next(s for s in spec.sections if s.key == "shift_details")
    assert shift_details.repeating is False
    assert shift_details.fields == ()


def test_a_repeating_section_becomes_an_array_in_the_output_contract() -> None:
    """A shift produces several FDAR entries, so the contract must allow several.

    A string here would force the model to flatten three foci into one blob, which is
    exactly the deficiency MISSING_RESPONSE exists to catch.
    """
    schema = json_schema_for(_spec(section_schema=_FDAR_SECTIONS))
    focus_entries = schema["properties"]["sections"]["properties"]["focus_entries"]
    assert focus_entries["type"] == "array"
    assert set(focus_entries["items"]["required"]) == {"focus", "data", "action", "response"}
    assert focus_entries["items"]["additionalProperties"] is False
```

Add a `_spec(...)` helper to the module if one does not exist, wrapping `TemplateSpec.from_schemas` with sensible defaults for every argument except the one under test.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_llm_templates.py -v -k "repeating or flat_section"`
Expected: FAIL — `AttributeError: 'SectionSpec' object has no attribute 'repeating'`

- [ ] **Step 3: Extend `SectionSpec` and the parser**

In `backend/app/llm/templates.py`, replace `SectionSpec`:

```python
@dataclass(frozen=True, slots=True)
class SectionSpec:
    key: str
    label: str
    order: int
    description: str
    # FDAR charts one F-D-A-R block per focus, and a shift has several. Every other
    # format is a flat list, so this is False everywhere but there.
    repeating: bool = False
    fields: tuple["SectionSpec", ...] = ()
```

Add a module-level parser above `TemplateSpec` and use it for both the top level and the nested fields:

```python
def _parse_sections(items: list[dict[str, Any]]) -> tuple[SectionSpec, ...]:
    return tuple(
        SectionSpec(
            key=str(item["key"]),
            label=str(item["label"]),
            order=int(item["order"]),
            description=str(item.get("description", "")),
            repeating=bool(item.get("repeating", False)),
            fields=_parse_sections(item.get("fields", [])),
        )
        for item in sorted(items, key=lambda s: int(s["order"]))
    )
```

In `from_schemas`, replace the inline `sections = tuple(...)` comprehension with `sections = _parse_sections(section_schema["sections"])`.

- [ ] **Step 4: Extend `json_schema_for`**

In `json_schema_for`, replace the `sections` properties comprehension with a call to a new helper:

```python
def _section_property(section: SectionSpec) -> dict[str, Any]:
    """The output contract for one section.

    A repeating section is an array of objects, so three foci arrive as three entries
    rather than as one flattened string the flag engine cannot inspect per-entry.
    """
    if not section.repeating:
        return {"type": ["string", "null"], "description": section.description}
    return {
        "type": "array",
        "description": section.description,
        "items": {
            "type": "object",
            "properties": {
                field.key: {"type": ["string", "null"], "description": field.description}
                for field in section.fields
            },
            "required": [field.key for field in section.fields],
            "additionalProperties": False,
        },
    }
```

and use `section.key: _section_property(section) for section in spec.sections`.

- [ ] **Step 5: Run the tests**

Run: `cd backend && pytest tests/test_llm_templates.py tests/test_llm_contract.py -v`
Expected: PASS. If `test_llm_contract.py` fails, the Pydantic validation of generated payloads also needs the array case — fix it there before moving on.

- [ ] **Step 6: Lint, type-check, and commit**

```bash
cd backend && ruff check . && ruff format --check . && mypy app
git add backend/app/llm/templates.py backend/tests/test_llm_templates.py
git commit -m "feat: repeating section groups in the template contract, for FDAR"
```

---

### Task 8: PH prompt modules

**Files:**
- Create: `backend/app/llm/prompts/ph_soapie_v1.py`, `backend/app/llm/prompts/ph_fdar_v1.py`
- Modify: `backend/app/llm/prompts/__init__.py`
- Test: `backend/tests/test_llm_prompts.py` (extend)

**Interfaces:**
- Consumes: `SHARED_RULES` from `app.llm.prompts.shared`.
- Produces: registry entries `"ph_soapie_v1"` and `"ph_fdar_v1"`, each a module exposing `VERSION: str` and `SYSTEM_PROMPT: str`.

Read `backend/app/llm/prompts/soapie_v1.py` first and follow its structure exactly — same constant names, same use of `SHARED_RULES`, same tone.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_llm_prompts.py`:

```python
def test_the_ph_prompt_versions_are_registered() -> None:
    assert {"ph_soapie_v1", "ph_fdar_v1"} <= set(known_versions())


def test_ph_soapie_does_not_ask_for_homebound_status() -> None:
    """Homebound status is a CMS survey requirement with no PhilHealth analogue.

    Asking for it would invite the model to invent one, which is the exact failure
    class the fabrication checker exists to catch.
    """
    prompt = get_prompt("ph_soapie_v1").system_prompt.lower()
    assert "homebound" not in prompt


def test_ph_fdar_names_the_four_fdar_elements() -> None:
    prompt = get_prompt("ph_fdar_v1").system_prompt.lower()
    for element in ("focus", "data", "action", "response"):
        assert element in prompt


def test_every_ph_prompt_carries_the_shared_rules() -> None:
    """The no-fabrication rules are not per-format and must not be re-stated per format."""
    for version in ("ph_soapie_v1", "ph_fdar_v1"):
        assert SHARED_RULES in get_prompt(version).system_prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_llm_prompts.py -v -k ph_`
Expected: FAIL — `AssertionError` on the registry set.

- [ ] **Step 3: Write the two prompt modules**

Create `backend/app/llm/prompts/ph_soapie_v1.py`, modelled on `soapie_v1.py`, with `VERSION = "ph_soapie_v1"`. Its `SYSTEM_PROMPT` must:
- embed `SHARED_RULES`
- describe the nine PH SOAPIE sections (the US ten, **minus Homebound status**)
- never mention homebound status, skilled-necessity rationale, or plan-of-care linkage
- state that the transcript is a single-speaker dictated recap, so no statement may be attributed to the patient as a direct quote unless the nurse explicitly says the patient said it
- instruct that any spoken patient name is omitted from the output

Create `backend/app/llm/prompts/ph_fdar_v1.py` with `VERSION = "ph_fdar_v1"`. Its `SYSTEM_PROMPT` must:
- embed `SHARED_RULES`
- define Focus, Data, Action, Response explicitly
- state that a shift has **one entry per focus** and the model must emit one array entry per distinct focus, never merge two foci into one entry
- require a time alongside every vital sign and every medication administration, and dose, route and site for medications
- state that an Action with no documented Response is the deficiency the note must surface, not paper over
- instruct that any spoken patient name is omitted from the output

- [ ] **Step 4: Register both modules**

In `backend/app/llm/prompts/__init__.py`, extend the import and the registry comprehension:

```python
from app.llm.prompts import ph_fdar_v1, ph_soapie_v1, shift_note_v1, soapie_v1
```

```python
_REGISTRY: dict[str, Prompt] = {
    module.VERSION: Prompt(version=module.VERSION, system_prompt=module.SYSTEM_PROMPT)
    for module in (shift_note_v1, soapie_v1, ph_soapie_v1, ph_fdar_v1)
}
```

The registry stays explicit — never scan the package. A prompt version appearing in production because someone dropped a file in a directory is precisely what this design prevents.

- [ ] **Step 5: Run the tests**

Run: `cd backend && pytest tests/test_llm_prompts.py -v`
Expected: PASS

- [ ] **Step 6: Lint, type-check, and commit**

```bash
cd backend && ruff check . && ruff format --check . && mypy app
git add backend/app/llm/prompts/ph_soapie_v1.py backend/app/llm/prompts/ph_fdar_v1.py backend/app/llm/prompts/__init__.py backend/tests/test_llm_prompts.py
git commit -m "feat: PH SOAPIE and PH FDAR prompt modules"
```

---

### Task 9: Seed the PH templates and make role defaults jurisdiction-aware

**Files:**
- Create: `backend/alembic/versions/0011_seed_ph_templates.py`
- Modify: `backend/app/schemas/auth.py` (`DEFAULT_FORMAT_BY_ROLE`), `backend/app/services/auth.py`
- Modify: `backend/app/models/enums.py` (`NoteFormat`)
- Test: `backend/tests/test_note_templates.py`, `backend/tests/test_onboarding.py` (extend)

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: `NoteFormat.FDAR = "fdar"`; two seeded rows, `(PH, soapie, 1)` and `(PH, fdar, 1)`; `default_format_for(jurisdiction: Jurisdiction, role: RoleTitle) -> NoteFormat` replacing the `DEFAULT_FORMAT_BY_ROLE` dict; `AuthService.update_profile` reconciles a note format stranded by a jurisdiction change.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_note_templates.py`:

```python
async def test_the_ph_templates_are_seeded_and_resolve(session: AsyncSession) -> None:
    repository = NoteTemplateRepository(session)
    for note_format in (NoteFormat.SOAPIE, NoteFormat.FDAR):
        template = await repository.get_active(Jurisdiction.PH, note_format)
        assert template is not None, note_format
        assert template.jurisdiction is Jurisdiction.PH
        assert template.requires_diarization is False


async def test_ph_soapie_drops_the_three_cms_only_flags(session: AsyncSession) -> None:
    """The single test that proves jurisdiction carries semantic weight.

    Same format, same sections bar one, different flag schema -- because homebound
    status, skilled-necessity rationale and plan-of-care linkage are CMS survey
    requirements with no Philippine analogue.
    """
    repository = NoteTemplateRepository(session)
    us = await repository.get_active(Jurisdiction.US, NoteFormat.SOAPIE)
    ph = await repository.get_active(Jurisdiction.PH, NoteFormat.SOAPIE)
    assert us is not None and ph is not None

    cms_only = {"MISSING_HOMEBOUND", "MISSING_NECESSITY_RATIONALE", "MISSING_POC_LINK"}
    us_codes = {f["code"] for f in us.flag_schema["flags"]}
    ph_codes = {f["code"] for f in ph.flag_schema["flags"]}

    assert cms_only <= us_codes
    assert cms_only.isdisjoint(ph_codes)


async def test_every_template_flags_a_spoken_patient_identifier(
    session: AsyncSession,
) -> None:
    """A pseudonymous label never de-identified the audio; this is what enforces it."""
    for template in await NoteTemplateRepository(session).all_active():
        codes = {f["code"] for f in template.flag_schema["flags"]}
        assert "PATIENT_IDENTIFIER_DETECTED" in codes, template.prompt_version


async def test_ph_fdar_has_a_repeating_focus_section(session: AsyncSession) -> None:
    fdar = await NoteTemplateRepository(session).get_active(
        Jurisdiction.PH, NoteFormat.FDAR
    )
    assert fdar is not None
    sections = fdar.section_schema["sections"]
    focus = next(s for s in sections if s["key"] == "focus_entries")
    assert focus["repeating"] is True
    assert [f["key"] for f in focus["fields"]] == ["focus", "data", "action", "response"]
```

Append to `backend/tests/test_onboarding.py`:

```python
async def test_switching_jurisdiction_reconciles_a_stranded_note_format(
    client: AsyncClient,
) -> None:
    """Switching PH -> US must not leave the user pointing at a format that has no
    template in their new jurisdiction.

    A PH RN defaults to fdar. There is no (US, fdar) template, so without
    reconciliation their next visit would resolve to None and fail in the pipeline --
    a failure at generation time, minutes later, for a mistake made at the switch.
    """
    headers = await _account(client)
    ph = (
        await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"role_title": "rn", "timezone": "Asia/Manila"},
        )
    ).json()
    assert ph["default_note_format"] == "fdar"

    us = (
        await client.patch("/api/v1/auth/me", headers=headers, json={"jurisdiction": "US"})
    ).json()
    assert us["jurisdiction"] == "US"
    assert us["default_note_format"] == "soapie"


async def test_switching_jurisdiction_keeps_a_format_that_is_still_valid(
    client: AsyncClient,
) -> None:
    """Reconciliation only fires when the format is actually stranded.

    soapie exists in both jurisdictions, so a US RN who moves to PH keeps it rather
    than being silently switched to fdar.
    """
    headers = await _account(client)
    await client.patch(
        "/api/v1/auth/me",
        headers=headers,
        json={"role_title": "rn", "timezone": "America/Los_Angeles"},
    )
    moved = (
        await client.patch("/api/v1/auth/me", headers=headers, json={"jurisdiction": "PH"})
    ).json()
    assert moved["default_note_format"] == "soapie"


async def test_a_ph_rn_defaults_to_fdar_and_a_us_rn_to_soapie(client: AsyncClient) -> None:
    """Role alone cannot pick a format once there are two jurisdictions.

    An RN on a Manila ward charts FDAR; an RN doing US home health charts SOAPIE.
    """
    ph = await _account(client)
    ph_profile = (
        await client.patch(
            "/api/v1/auth/me",
            headers=ph,
            json={"role_title": "rn", "timezone": "Asia/Manila"},
        )
    ).json()
    assert ph_profile["default_note_format"] == "fdar"

    us = await _account(client)
    us_profile = (
        await client.patch(
            "/api/v1/auth/me",
            headers=us,
            json={"role_title": "rn", "timezone": "America/Los_Angeles"},
        )
    ).json()
    assert us_profile["default_note_format"] == "soapie"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_note_templates.py tests/test_onboarding.py -v -k "ph_ or seeded or identifier"`
Expected: FAIL — `AttributeError: FDAR` on `NoteFormat`.

- [ ] **Step 3: Add the format and make role defaults jurisdiction-aware**

In `backend/app/models/enums.py`, add to `NoteFormat`:

```python
    FDAR = "fdar"
```

In `backend/app/schemas/auth.py`, replace the `DEFAULT_FORMAT_BY_ROLE` dict with:

```python
# Role alone cannot pick a format once there are two jurisdictions: an RN on a Manila
# ward charts FDAR, an RN doing US home health charts SOAPIE. Keyed on both, so a
# missing pair is a KeyError at import-time review rather than a silent wrong default.
_DEFAULT_FORMAT: dict[tuple[Jurisdiction, RoleTitle], NoteFormat] = {
    (Jurisdiction.US, RoleTitle.CAREGIVER): NoteFormat.SHIFT_NOTE,
    (Jurisdiction.US, RoleTitle.HHA): NoteFormat.SHIFT_NOTE,
    (Jurisdiction.US, RoleTitle.CNA): NoteFormat.SHIFT_NOTE,
    (Jurisdiction.US, RoleTitle.LPN): NoteFormat.SOAPIE,
    (Jurisdiction.US, RoleTitle.RN): NoteFormat.SOAPIE,
    (Jurisdiction.US, RoleTitle.OTHER): NoteFormat.SHIFT_NOTE,
    # PH ships no shift_note template -- the PH market is hospital bedside nursing,
    # not home care -- so every PH role lands on a clinical format.
    (Jurisdiction.PH, RoleTitle.CAREGIVER): NoteFormat.FDAR,
    (Jurisdiction.PH, RoleTitle.HHA): NoteFormat.FDAR,
    (Jurisdiction.PH, RoleTitle.CNA): NoteFormat.FDAR,
    (Jurisdiction.PH, RoleTitle.LPN): NoteFormat.FDAR,
    (Jurisdiction.PH, RoleTitle.RN): NoteFormat.FDAR,
    (Jurisdiction.PH, RoleTitle.OTHER): NoteFormat.FDAR,
}


def default_format_for(jurisdiction: Jurisdiction, role: RoleTitle) -> NoteFormat:
    return _DEFAULT_FORMAT[(jurisdiction, role)]
```

In `backend/app/services/auth.py`, import `default_format_for` instead of `DEFAULT_FORMAT_BY_ROLE` and change the role branch in `update_profile` to:

```python
        if payload.role_title is not None:
            user.role_title = payload.role_title
            # Derive from role AND jurisdiction unless the user overrides it. Read
            # user.jurisdiction, not the payload's -- the timezone branch above has
            # already applied any change, so this sees the final value.
            if payload.default_note_format is None:
                user.default_note_format = default_format_for(
                    user.jurisdiction, payload.role_title
                )
```

**Ordering matters:** the timezone/jurisdiction branch from Task 1 must run *before* this one, so a single PATCH carrying both `timezone` and `role_title` derives the format from the new jurisdiction.

Then, as the **last** thing `update_profile` does before committing, reconcile a stranded format:

```python
        # A jurisdiction change can strand the user's format: a PH RN defaults to
        # fdar, and there is no (US, fdar) template. Left alone, their next visit
        # would resolve to None and fail in the pipeline minutes later, for a mistake
        # made here. Checked against note_templates rather than a hardcoded map, so
        # seeding a PH shift_note later makes it valid with no code change.
        if user.role_title is not None and user.default_note_format is not None:
            templates = NoteTemplateRepository(self.session)
            if await templates.get_active(user.jurisdiction, user.default_note_format) is None:
                user.default_note_format = default_format_for(
                    user.jurisdiction, user.role_title
                )
```

Import `NoteTemplateRepository` from `app.repositories.note_templates`. A service calling a repository is the established direction in this codebase; a router doing so would not be.

This runs after every branch, so it catches a stranded format however it arose — a jurisdiction-only PATCH, a combined one, or an explicit `default_note_format` the user is no longer entitled to.

- [ ] **Step 4: Write the seed migration**

Create `backend/alembic/versions/0011_seed_ph_templates.py`, following `0002_seed_note_templates.py` exactly — same `_sections()` / `_flags()` helpers, same `DEFAULT_PROVIDER` / `DEFAULT_MODEL_ID` constants, same parameterised INSERT. Four differences:

1. The INSERT includes `jurisdiction` and `requires_diarization`, and no longer casts `format` to the dropped ENUM:

```python
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
```

2. `_sections()` gains a repeating variant for the FDAR focus group, emitting `"repeating": True` and a nested `"fields"` list of the same shape.
3. Section and flag content comes from the **Note Formats** section of the spec — PH SOAPIE (nine sections, US flags minus the three CMS-only codes) and PH FDAR (six sections with `focus_entries` repeating; the flag set listed in the spec).
4. `downgrade()` deletes `WHERE jurisdiction = 'PH' AND version = 1`.

This migration must also **add `PATIENT_IDENTIFIER_DETECTED` (critical) to the two existing US rows**, via an `UPDATE` that appends the flag object to `flag_schema -> 'flags'`, because `test_every_template_flags_a_spoken_patient_identifier` covers all four templates. Write that as a separate statement in the same `upgrade()`, and reverse it in `downgrade()`.

- [ ] **Step 5: Run the migration and the tests**

Run:
```bash
cd backend && alembic upgrade head && pytest tests/test_note_templates.py tests/test_onboarding.py -v
```
Expected: PASS

- [ ] **Step 6: Verify the downgrade**

Run: `cd backend && alembic downgrade 0010 && alembic upgrade head`
Expected: both succeed.

- [ ] **Step 7: Run the full suite, lint, type-check, and commit**

```bash
cd backend && pytest -q && ruff check . && ruff format --check . && mypy app
git add backend/alembic/versions/0011_seed_ph_templates.py backend/app/models/enums.py backend/app/schemas/auth.py backend/app/services/auth.py backend/tests/test_note_templates.py backend/tests/test_onboarding.py
git commit -m "feat: seed PH SOAPIE and PH FDAR templates, jurisdiction-aware role defaults"
```

- [ ] **Step 8: Record how long Task 9 took**

Add a line to `CHANGELOG.md` under `[Unreleased]` stating the wall-clock time from starting Task 8 to finishing Task 9 — the time it took to add the third and fourth note formats.

The spec asks for this measurement by name. It is the evidence behind the README's central architectural claim ("one pipeline, four note formats, two regulatory regimes — because templates and their flag schemas are rows, not code"), and an unmeasured claim is an assertion.

---

## Out of scope for this phase

Named here so they are not discovered as gaps mid-task:

- **The web client.** Onboarding's jurisdiction field, the PH consent copy, and the repeating-group section editor are Phase 5. This phase is backend and migrations only.
- **`notes.note_template_id`.** The spec's claim that every note records its template id does not hold against `app/models/note.py`, which stores `prompt_version`, `provider` and `model_id`. That is adequate provenance. Whether to add the foreign key is a Phase 5 decision, where the editor needs the section schema anyway. (The spec has been corrected to say so.)
- **Golden dataset cases for the PH templates.** Phase 5b, authored by the PH RN.
- **The PH Endorsement format.** Deferred — it is multi-patient, and therefore a data model change rather than a template change.
