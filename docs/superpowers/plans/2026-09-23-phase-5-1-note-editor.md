# Phase 5.1 — Note Review and the Schema-Driven Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A nurse opens a note the pipeline wrote, reads it in the structure their format prescribes, corrects what the model got wrong — including adding an FDAR focus entry it missed — and saves, without two people silently overwriting each other.

**Architecture:** One additive migration (`0013`) gives `notes` a foreign key to the template row that produced it, so the editor renders against that template rather than whatever is active now. Three endpoints follow — read one note, list recent notes, patch one note under a version check — and a React editor that renders sections from `section_schema` with no format-specific component anywhere. Nothing in the pipeline or the prompt contract changes shape; this phase reads what Phase 4 already writes.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0 (async, `Mapped[]` style), Alembic, Pydantic v2, pytest + pytest-asyncio (auto mode) + httpx `AsyncClient`, real PostgreSQL. React 19 + Vite, TanStack Query v5, react-router 7, Vitest + Testing Library, Tailwind 4.

**Spec:** [`2026-09-23-phase-5-1-note-editor-design.md`](../specs/2026-09-23-phase-5-1-note-editor-design.md) — read it before starting. The build specification it derives from is [`visitnote-claude-code-prompt-v9.md`](../../../visitnote-claude-code-prompt-v9.md).

## Global Constraints

- **Routers do HTTP and nothing else.** Business rules live in services, queries in repositories. A router never touches a database session directly beyond passing it to a service.
- **Tenant scoping lives in the repository, not the handler.** Another user's note is **404**, never 403, so a caller cannot probe for ids they do not own. A new route must not be able to forget it.
- **TDD, strictly.** Write the failing test, run it and watch it fail for the stated reason, write the minimal implementation, watch it pass, commit. A test that passes the first time you run it is not yet testing anything.
- **`ruff check . && mypy app` must pass** before every backend commit. `npm run typecheck && npm run lint` before every web commit.
- **Tests run against real PostgreSQL.** `docker compose up -d postgres redis` from the repo root first. Run the backend suite inside the API container: `docker compose exec -T api pytest -q`.
- **Every migration must have a working `downgrade()`.** CI runs `alembic downgrade base && alembic upgrade head`. Verify `0013`'s down path against a scratch database, because the development database holds `fdar` rows that make `downgrade base` refuse — see [the test-isolation finding](../findings/2026-09-22-test-isolation.md).
- **Map every non-native enum column with `Enum(..., native_enum=False, create_constraint=False, length=N)`, never bare `String(N)`.** A bare `String` typed `Mapped[SomeEnum]` loads back as `str`, so `value is SomeEnum.MEMBER` silently fails while `==` still passes.
- **Regenerate the client types after any schema change**: `npm run generate:api` in `web/` against a running API, and commit the result. The `contract` CI job fails on drift.
- **No format-specific component in the client.** If a component name contains `fdar`, `soapie` or `shift_note`, the design has been lost.
- **The section PATCH validates structure, never `BANNED_PHRASES`.** That rule governs the model's voice; a nurse is the author of a clinical record.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/alembic/versions/0013_notes_note_template_id.py` | the FK, its backfill, and the refusal when a note cannot be resolved |
| `backend/app/models/note.py` | `Note.note_template_id` |
| `backend/app/llm/pipeline.py` | resolve the template row, pass its id to the write |
| `backend/app/repositories/notes.py` | note reads scoped to a user, flag-count aggregation, the versioned update |
| `backend/app/llm/contract.py` | `validate_sections_structure`, shared by generation and editing |
| `backend/app/schemas/note.py` | `NoteRead`, `NoteListItem`, `NoteUpdate`, `TemplateRead`, `SectionSpecRead`, `NoteFlagRead` |
| `backend/app/services/notes.py` | read, list and update rules; the version check |
| `backend/app/api/v1/routers/notes.py` | three routes, HTTP only |
| `web/src/lib/note.ts` | note queries and the save mutation |
| `web/src/routes/NoteEditor.tsx` | fetch, form state, save, conflict handling |
| `web/src/routes/Notes.tsx` | the recent list |
| `web/src/components/note/SectionField.tsx` | one flat section |
| `web/src/components/note/RepeatingSection.tsx` | one repeating section and its entries |
| `web/src/components/note/VisitDetailsFields.tsx` | the four header fields |
| `web/src/components/note/FlagsPanel.tsx` | flags grouped by severity |

---

### Task 1: `note_template_id` on notes

**Files:**
- Modify: `backend/app/models/note.py`
- Create: `backend/alembic/versions/0013_notes_note_template_id.py`
- Modify: `backend/app/repositories/notes.py` (`NoteRepository.create_for_visit`)
- Modify: `backend/app/llm/pipeline.py` (`_template`, and its call site)
- Test: `backend/tests/test_note_persistence.py` (extend)

**Interfaces:**
- Consumes: nothing — this is the first task.
- Produces: `Note.note_template_id: Mapped[uuid.UUID]` (non-null, FK to `note_templates.id`); `NoteRepository.create_for_visit(*, visit: Visit, spec: TemplateSpec, generated: GeneratedNote, template_id: uuid.UUID) -> Note`; `NotePipeline._template(visit: Visit) -> NoteTemplate` (returns the row, not the spec).

**Why the id is not on `TemplateSpec`:** it is a frozen value object describing a contract, built in `tests/test_llm_contract.py` and `tests/test_llm_templates.py` directly from schemas with no row behind it. An optional `id` there would put a `None` path into a `NOT NULL` column. The write site takes the id explicitly instead.

- [ ] **Step 1: Write the failing test that a generated note records its template**

Append to `backend/tests/test_note_persistence.py`:

```python
async def test_the_note_records_the_template_that_produced_it(
    session: AsyncSession,
) -> None:
    # Resolving the template at read time would render an old note against a newer
    # template's section_schema the day a second version is seeded.
    visit = await _visit(session)
    template = await NoteTemplateRepository(session).get_active(
        visit.jurisdiction, visit.note_format
    )
    assert template is not None

    note = await NoteRepository(session).create_for_visit(
        visit=visit,
        spec=TemplateSpec.from_template(template),
        generated=_generated(),
        template_id=template.id,
    )

    assert note.note_template_id == template.id
```

Use the file's existing `_visit` and `_generated` helpers; if they are named differently in the file as it stands, match what is there rather than renaming them.

- [ ] **Step 2: Run it and watch it fail**

Run: `docker compose exec -T api pytest tests/test_note_persistence.py -k records_the_template -q`
Expected: FAIL — `TypeError: create_for_visit() got an unexpected keyword argument 'template_id'`

- [ ] **Step 3: Add the column to the model**

In `backend/app/models/note.py`, inside `class Note`, directly after the `format` column:

```python
    # The exact template row this note was generated from, not whichever row is
    # active when someone opens it. Templates are versioned and promotion inserts a
    # new row rather than rewriting the old one, so this pointer keeps meaning what
    # it meant on the day the note was written -- which is what lets the editor
    # render an old note against the schema that actually shaped its sections.
    note_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("note_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
```

- [ ] **Step 4: Write the migration**

Create `backend/alembic/versions/0013_notes_note_template_id.py`:

```python
"""Record which template produced each note.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-23

Templates are resolved by (jurisdiction, format) to the active row with the highest
version. Without this column the editor would render a note against whichever
template is active when it is opened, which stops being the one that produced it the
moment a second version is seeded: stored sections with no schema entry, schema
entries with no stored section.

The backfill takes the highest version regardless of is_active, so a template that
has since been deactivated still resolves the notes it produced. A note that cannot
be resolved stops the migration with the pairs named, rather than letting SET NOT
NULL fail on a constraint violation -- remapping or discarding a clinical record is
not a migration's decision to make.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notes", sa.Column("note_template_id", sa.UUID(), nullable=True))

    op.execute(
        """
        UPDATE notes AS n
        SET note_template_id = (
            SELECT t.id
            FROM note_templates AS t
            WHERE t.jurisdiction = v.jurisdiction
              AND t.format = n.format
            ORDER BY t.version DESC
            LIMIT 1
        )
        FROM visits AS v
        WHERE v.id = n.visit_id
        """
    )

    unresolved = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT DISTINCT v.jurisdiction, n.format
                FROM notes AS n
                JOIN visits AS v ON v.id = n.visit_id
                WHERE n.note_template_id IS NULL
                """
            )
        )
        .fetchall()
    )
    if unresolved:
        pairs = ", ".join(f"({row[0]}, {row[1]})" for row in unresolved)
        raise RuntimeError(
            "Cannot backfill notes.note_template_id: no note_templates row exists for "
            f"{pairs}. Seed the missing template before upgrading; remapping a charted "
            "format is not a migration's decision to make."
        )

    op.alter_column("notes", "note_template_id", nullable=False)
    op.create_index(
        op.f("ix_notes_note_template_id"), "notes", ["note_template_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_notes_note_template_id_note_templates"),
        "notes",
        "note_templates",
        ["note_template_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_notes_note_template_id_note_templates"), "notes", type_="foreignkey"
    )
    op.drop_index(op.f("ix_notes_note_template_id"), table_name="notes")
    op.drop_column("notes", "note_template_id")
```

- [ ] **Step 5: Take the write site's template id explicitly**

In `backend/app/repositories/notes.py`, change the signature and the `Note(...)` construction:

```python
    async def create_for_visit(
        self,
        *,
        visit: Visit,
        spec: TemplateSpec,
        generated: GeneratedNote,
        template_id: uuid.UUID,
    ) -> Note:
```

and inside the `Note(...)` call, after `format=spec.format,`:

```python
            note_template_id=template_id,
```

- [ ] **Step 6: Return the row from the pipeline's template resolution**

In `backend/app/llm/pipeline.py`, change `_template` to return the row:

```python
    async def _template(self, visit: Visit) -> NoteTemplate:
```

with its final line becoming `return template` instead of `return TemplateSpec.from_template(template)`. Import `NoteTemplate` from `app.models`. At the call site (around line 119):

```python
        template = await self._template(visit)
        spec = TemplateSpec.from_template(template)
```

and at the persist site (around line 146):

```python
            await NoteRepository(self.session).create_for_visit(
                visit=visit, spec=spec, generated=generated, template_id=template.id
            )
```

- [ ] **Step 7: Migrate and run the tests**

Run:
```bash
docker compose exec -T api alembic upgrade head
docker compose exec -T api pytest tests/test_note_persistence.py tests/test_pipeline.py -q
```
Expected: PASS. If the migration raises the unresolved-pairs error, a template row is genuinely missing for a format your database holds notes in — seed it rather than weakening the check.

- [ ] **Step 8: Verify the down path on a scratch database**

The development database holds `fdar` rows that make `alembic downgrade base` refuse by design, so verify against a throwaway one:

```bash
docker compose exec -T postgres psql -U visitnote -d postgres -c "DROP DATABASE IF EXISTS scratch;"
docker compose exec -T postgres psql -U visitnote -d postgres -c "CREATE DATABASE scratch;"
docker compose run --rm -e DATABASE_URL="postgresql+asyncpg://visitnote:visitnote@postgres:5432/scratch" \
  api sh -c 'alembic upgrade head && alembic check && alembic downgrade base'
```
Expected: all three succeed.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/note.py backend/alembic/versions/0013_notes_note_template_id.py \
        backend/app/repositories/notes.py backend/app/llm/pipeline.py backend/tests/test_note_persistence.py
git commit -m "feat: record which template produced each note"
```

---

### Task 2: Structural validation, shared by generation and editing

**Files:**
- Modify: `backend/app/llm/contract.py`
- Test: `backend/tests/test_llm_contract.py` (extend)

**Interfaces:**
- Consumes: `TemplateSpec`, `SectionValue` from Task 0 state (both already exist).
- Produces: `validate_sections_structure(sections: dict[str, SectionValue], spec: TemplateSpec) -> None`, raising `NoteValidationError`. Checks section keys and repeating-entry shapes. Does **not** check banned phrases.

**Why:** `validate_output` currently does keys, repeating entries and banned phrases in one pass. The section PATCH needs the first two and must not apply the third. Extracting the shared half means the editor and the pipeline cannot disagree about what a valid `focus_entries` looks like.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_llm_contract.py`:

```python
def test_structure_validation_rejects_an_unknown_section() -> None:
    with pytest.raises(NoteValidationError) as exc:
        validate_sections_structure({"invented": "text"}, SPEC)

    assert "invented" in str(exc.value)


def test_structure_validation_rejects_an_entry_missing_a_declared_field() -> None:
    # MISSING_RESPONSE exists to catch an Action with no documented Response. A key
    # the author never wrote and a response they determined absent must not be
    # indistinguishable.
    sections = {key: "text" for key in _REPEATING_FLAT_KEYS}
    sections["focus_entries"] = [{"focus": "Pain", "data": "7/10", "action": "Gave PRN"}]

    with pytest.raises(NoteValidationError) as exc:
        validate_sections_structure(sections, REPEATING_SPEC)

    assert "response" in str(exc.value)


def test_structure_validation_permits_a_banned_phrase() -> None:
    # The banned-phrase rule governs how the *model* writes. A nurse typing these
    # words is the author of a clinical record, and the editor is not a gate on a
    # clinician's language.
    sections = {key: "routine visit" for key in _FLAT_KEYS}

    validate_sections_structure(sections, SPEC)
```

Define these next to the existing `SPEC` and `REPEATING_SPEC` in that file. Listed explicitly rather than derived from the spec, so a change to either schema breaks the test loudly instead of quietly testing a different shape:

```python
# Every section `SPEC` declares, and every *flat* section `REPEATING_SPEC` declares.
_FLAT_KEYS: tuple[str, ...] = ("observations", "handover")
_REPEATING_FLAT_KEYS: tuple[str, ...] = ("shift_details",)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `docker compose exec -T api pytest tests/test_llm_contract.py -k structure_validation -q`
Expected: FAIL — `NameError: name 'validate_sections_structure' is not defined`

- [ ] **Step 3: Extract the shared check**

In `backend/app/llm/contract.py`, add above `validate_output`:

```python
def validate_sections_structure(
    sections: dict[str, SectionValue], spec: TemplateSpec
) -> None:
    """Check a section map against the template's shape.

    Shared by generation and by the review editor, so the two cannot disagree about
    what a valid repeating section looks like. Structure only: the banned-phrase rule
    belongs to `validate_output`, because it governs how the model writes rather than
    what a human author is allowed to say about their own patient.
    """
    _check_keys(
        actual=set(sections),
        expected={section.key for section in spec.sections},
        label="sections",
    )
    _check_repeating_sections(sections, spec)
```

and in `validate_output`, replace the existing `_check_keys(...)` call for sections and the `_check_repeating_sections(note.sections, spec)` call with a single:

```python
    validate_sections_structure(note.sections, spec)
```

leaving the `visit_details` key check and `_check_banned_phrases(note.sections)` exactly as they are.

- [ ] **Step 4: Run the whole contract suite**

Run: `docker compose exec -T api pytest tests/test_llm_contract.py -q`
Expected: PASS, including every test that existed before — the extraction must not change generation behaviour.

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm/contract.py backend/tests/test_llm_contract.py
git commit -m "refactor: share structural section validation with the editor"
```

---

### Task 3: Read one note

**Files:**
- Create: `backend/app/schemas/note.py`
- Modify: `backend/app/repositories/notes.py`
- Create: `backend/app/services/notes.py`
- Create: `backend/app/api/v1/routers/notes.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/test_notes_api.py` (create)

**Interfaces:**
- Consumes: `Note.note_template_id` (Task 1).
- Produces: `NoteRead`, `TemplateRead`, `SectionSpecRead`, `NoteFlagRead` in `app/schemas/note.py`; `NoteRepository.get_for_user(note_id: uuid.UUID, user_id: uuid.UUID) -> Note | None`; `NoteService.get(note_id: uuid.UUID, user: User) -> NoteRead` raising `NoteNotFoundError`; `GET /api/v1/notes/{note_id}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_notes_api.py`:

```python
"""Reading a note.

The editor renders from the template's section schema, so the read has to carry that
schema -- and it has to be the schema of the template that produced the note, not
whichever one is active when someone opens it.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NoteTemplate

PASSWORD = "a-sufficiently-long-password"


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


async def test_reading_a_note_returns_its_sections_and_flags(
    client: AsyncClient, note_fixture
) -> None:
    note, headers = note_fixture

    response = await client.get(f"/api/v1/notes/{note.id}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(note.id)
    assert body["version"] == 1
    assert body["edited"] is False
    assert set(body["sections"]) == {s["key"] for s in body["template"]["sections"]}


async def test_the_read_carries_the_schema_of_the_producing_template(
    client: AsyncClient, session: AsyncSession, note_fixture
) -> None:
    # The whole point of the foreign key. With a v2 seeded and active, resolving by
    # (jurisdiction, format) would hand the editor v2's schema for a note whose
    # sections were shaped by v1.
    note, headers = note_fixture
    produced_by = (
        await session.execute(select(NoteTemplate).where(NoteTemplate.id == note.note_template_id))
    ).scalar_one()
    session.add(
        NoteTemplate(
            jurisdiction=produced_by.jurisdiction,
            format=produced_by.format,
            version=produced_by.version + 1,
            name=f"{produced_by.name} v{produced_by.version + 1}",
            section_schema={
                "sections": [
                    {"key": "completely_different", "label": "Different", "order": 1,
                     "description": "Only in v2."}
                ]
            },
            flag_schema=produced_by.flag_schema,
            requires_diarization=produced_by.requires_diarization,
            prompt_version=produced_by.prompt_version,
            llm_provider=produced_by.llm_provider,
            model_id=produced_by.model_id,
            is_active=True,
        )
    )
    await session.commit()

    body = (await client.get(f"/api/v1/notes/{note.id}", headers=headers)).json()

    assert body["template"]["version"] == produced_by.version
    assert "completely_different" not in {s["key"] for s in body["template"]["sections"]}


async def test_another_users_note_is_not_found(
    client: AsyncClient, note_fixture
) -> None:
    # 404 rather than 403: a caller must not be able to probe for note ids they do
    # not own.
    note, _ = note_fixture
    other = (
        await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
        )
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    response = await client.get(f"/api/v1/notes/{note.id}", headers=headers)

    assert response.status_code == 404
```

Add these fixtures to `backend/tests/conftest.py`. They write a note directly rather than running the pipeline, which needs audio and a provider:

```python
@pytest.fixture
async def note_fixture(
    client: AsyncClient, session: AsyncSession
) -> tuple[Note, dict[str, str]]:
    """A US shift note owned by a registered user, with the headers to read it.

    Written through the repository rather than the pipeline: this fixture exists to
    exercise the review API, and routing it through transcription and generation
    would make every one of those tests depend on a provider.
    """
    return await _note_for_new_user(client, session)


@pytest.fixture
async def two_notes_fixture(
    client: AsyncClient, session: AsyncSession
) -> tuple[tuple[Note, Note], dict[str, str]]:
    """Two notes for one user, older first."""
    older, headers = await _note_for_new_user(client, session)
    newer, _ = await _note_for_new_user(client, session, headers=headers)
    return (older, newer), headers


async def _note_for_new_user(
    client: AsyncClient,
    session: AsyncSession,
    headers: dict[str, str] | None = None,
) -> tuple[Note, dict[str, str]]:
    if headers is None:
        registered = (
            await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"{uuid.uuid4().hex}@visitnote-testing.com",
                    "password": "a-sufficiently-long-password",
                },
            )
        ).json()
        headers = {"Authorization": f"Bearer {registered['access_token']}"}

    profile = (await client.get("/api/v1/auth/me", headers=headers)).json()
    user_id = uuid.UUID(profile["id"])

    care_recipient = Client(owner_id=user_id, label="Mrs R")
    session.add(care_recipient)
    await session.flush()

    visit = Visit(
        user_id=user_id,
        client_id=care_recipient.id,
        jurisdiction=Jurisdiction.US,
        note_format=NoteFormat.SHIFT_NOTE,
        capture_mode=CaptureMode.SPOKEN_RECAP,
        status=VisitStatus.PROCESSING,
        timezone="America/Los_Angeles",
        idempotency_key=uuid.uuid4().hex,
    )
    session.add(visit)
    await session.commit()
    await session.refresh(visit)

    # Filtered on jurisdiction as well as format: once the PH rows exist, filtering
    # on format alone raises MultipleResultsFound instead of picking a row.
    template = (
        await session.execute(
            select(NoteTemplate).where(
                NoteTemplate.jurisdiction == Jurisdiction.US,
                NoteTemplate.format == NoteFormat.SHIFT_NOTE,
                NoteTemplate.is_active.is_(True),
            )
        )
    ).scalars().first()
    assert template is not None

    note = await NoteRepository(session).create_for_visit(
        visit=visit,
        spec=TemplateSpec.from_template(template),
        generated=GeneratedNote(
            visit_details={
                "client_label": "Mrs R",
                "visit_date": "2026-09-21",
                "start_time": "08:00",
                "end_time": None,
            },
            sections={"observations": "Ate half of lunch.", "handover": None},
            flags=[
                GeneratedFlag(
                    code="MISSING_SHIFT_TIMES",
                    message="No end time was stated.",
                    severity=FlagSeverity.CRITICAL,
                )
            ],
        ),
        template_id=template.id,
    )
    return note, headers
```

`conftest.py` needs these imports added: `uuid`, `select` from `sqlalchemy`, `AsyncClient` from `httpx`, `GeneratedFlag` and `GeneratedNote` from `app.llm.contract`, `TemplateSpec` from `app.llm.templates`, `Client`, `Note`, `NoteTemplate` and `Visit` from `app.models`, `CaptureMode`, `FlagSeverity`, `Jurisdiction`, `NoteFormat` and `VisitStatus` from `app.models.enums`, and `NoteRepository` from `app.repositories.notes`.

The sections `observations` and `handover` are the two the seeded US shift-note template declares; if that template's schema has changed, read it and use its keys instead.

- [ ] **Step 2: Run them and watch them fail**

Run: `docker compose exec -T api pytest tests/test_notes_api.py -q`
Expected: FAIL — 404 from FastAPI for every request, because no `/api/v1/notes` route exists yet.

- [ ] **Step 3: Write the read schemas**

Create `backend/app/schemas/note.py`:

```python
"""Note read and update models.

The read carries the producing template's section schema because the client renders
from it and contains no format-specific component: a third note format is a seeded
row and a prompt module, never a new screen.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import FlagSeverity, Jurisdiction, NoteFormat, ReviewStatus

# A section is prose, or -- for a repeating group like FDAR's focus entries -- a list
# of entries. Mirrors `app.llm.contract.SectionValue`, which is the shape the pipeline
# validates and stores.
SectionValue = str | list[dict[str, str | None]] | None


class SectionSpecRead(BaseModel):
    key: str
    label: str
    order: int
    description: str
    repeating: bool
    fields: list["SectionSpecRead"]


class TemplateRead(BaseModel):
    jurisdiction: Jurisdiction
    format: NoteFormat
    version: int
    name: str
    sections: list[SectionSpecRead]


class NoteFlagRead(BaseModel):
    code: str
    message: str
    severity: FlagSeverity


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    visit_id: uuid.UUID
    format: NoteFormat
    version: int
    edited: bool
    review_status: ReviewStatus
    signed_at: datetime | None
    visit_details: dict[str, Any]
    sections: dict[str, SectionValue]
    flags: list[NoteFlagRead]
    template: TemplateRead
```

- [ ] **Step 4: Add the scoped read to the repository**

In `backend/app/repositories/notes.py`, add to `NoteRepository`:

```python
    async def get_for_user(self, note_id: uuid.UUID, user_id: uuid.UUID) -> Note | None:
        """One note, scoped to its owner.

        Scoping here rather than in the handler is what keeps a new route from
        forgetting it. A note belonging to someone else is indistinguishable from one
        that does not exist.
        """
        return (
            await self.session.execute(
                select(Note)
                .where(Note.id == note_id, Note.user_id == user_id)
                .options(selectinload(Note.template))
            )
        ).scalar_one_or_none()
```

Add `from sqlalchemy.orm import selectinload` to the imports, and give `Note` a relationship in `backend/app/models/note.py`, beside the existing `note_flags` relationship:

```python
    template: Mapped["NoteTemplate"] = relationship(lazy="raise")
```

with `from app.models.note_template import NoteTemplate` imported under `TYPE_CHECKING`. `lazy="raise"` makes a forgotten eager load a loud error rather than a silent extra query inside a request.

- [ ] **Step 5: Write the service**

Create `backend/app/services/notes.py`:

```python
"""Reading and correcting a generated note."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.templates import SectionSpec, TemplateSpec
from app.models import Note, User
from app.repositories.notes import NoteRepository
from app.schemas.note import NoteFlagRead, NoteRead, SectionSpecRead, TemplateRead


class NoteNotFoundError(Exception):
    """No such note, or it belongs to someone else.

    One error for both, so a caller cannot probe for note ids they do not own.
    """


def _section_spec_read(section: SectionSpec) -> SectionSpecRead:
    return SectionSpecRead(
        key=section.key,
        label=section.label,
        order=section.order,
        description=section.description,
        repeating=section.repeating,
        fields=[_section_spec_read(field) for field in section.fields],
    )


@dataclass(slots=True)
class NoteService:
    session: AsyncSession

    async def get(self, note_id: uuid.UUID, user: User) -> NoteRead:
        note = await NoteRepository(self.session).get_for_user(note_id, user.id)
        if note is None:
            raise NoteNotFoundError
        return self._read(note)

    def _read(self, note: Note) -> NoteRead:
        spec = TemplateSpec.from_template(note.template)
        return NoteRead(
            id=note.id,
            visit_id=note.visit_id,
            format=note.format,
            version=note.version,
            edited=note.edited,
            review_status=note.review_status,
            signed_at=note.signed_at,
            visit_details=dict(note.visit_details),
            sections=dict(note.sections),
            flags=[NoteFlagRead(**flag) for flag in note.flags],
            template=TemplateRead(
                jurisdiction=spec.jurisdiction,
                format=spec.format,
                version=spec.version,
                name=spec.name,
                sections=[_section_spec_read(section) for section in spec.sections],
            ),
        )
```

- [ ] **Step 6: Write the router and register it**

Create `backend/app/api/v1/routers/notes.py`:

```python
"""Note review routes."""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.note import NoteRead
from app.services.notes import NoteNotFoundError, NoteService

router = APIRouter(prefix="/notes", tags=["notes"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")


@router.get("/{note_id}", response_model=NoteRead)
async def read_note(note_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> NoteRead:
    try:
        return await NoteService(session).get(note_id, user)
    except NoteNotFoundError as exc:
        raise _NOT_FOUND from exc
```

In `backend/app/api/v1/router.py`, add `notes` to the import and `api_router.include_router(notes.router)` after `visits`.

- [ ] **Step 7: Run the tests**

Run: `docker compose exec -T api pytest tests/test_notes_api.py -q && docker compose exec -T api ruff check . && docker compose exec -T api mypy app`
Expected: PASS, exit 0, no issues.

- [ ] **Step 8: Commit**

```bash
git add backend/app/schemas/note.py backend/app/services/notes.py \
        backend/app/api/v1/routers/notes.py backend/app/api/v1/router.py \
        backend/app/repositories/notes.py backend/app/models/note.py \
        backend/tests/test_notes_api.py backend/tests/conftest.py
git commit -m "feat: read a note with the schema of the template that produced it"
```

---

### Task 4: List recent notes

**Files:**
- Modify: `backend/app/repositories/notes.py`
- Modify: `backend/app/schemas/note.py`
- Modify: `backend/app/services/notes.py`
- Modify: `backend/app/api/v1/routers/notes.py`
- Test: `backend/tests/test_notes_api.py` (extend)

**Interfaces:**
- Consumes: `NoteService` (Task 3).
- Produces: `NoteListItem` in `app/schemas/note.py`; `NoteRepository.recent_for_user(user_id: uuid.UUID, limit: int = 50) -> list[Note]`; `NoteRepository.flag_counts(note_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[FlagSeverity, int]]`; `NoteService.list(user: User) -> list[NoteListItem]`; `GET /api/v1/notes`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_notes_api.py`:

```python
async def test_the_list_returns_your_own_notes_newest_first(
    client: AsyncClient, two_notes_fixture
) -> None:
    (older, newer), headers = two_notes_fixture

    body = (await client.get("/api/v1/notes", headers=headers)).json()

    assert [item["id"] for item in body] == [str(newer.id), str(older.id)]


async def test_the_list_counts_flags_by_severity(
    client: AsyncClient, note_fixture
) -> None:
    # Aggregated in SQL over note_flags rather than by counting the JSONB payload in
    # Python: that normalized table exists for exactly this access pattern.
    note, headers = note_fixture

    body = (await client.get("/api/v1/notes", headers=headers)).json()

    assert body[0]["flag_counts"]["critical"] >= 1


async def test_the_list_excludes_other_users_notes(
    client: AsyncClient, note_fixture
) -> None:
    _, _ = note_fixture
    other = (
        await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
        )
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    body = (await client.get("/api/v1/notes", headers=headers)).json()

    assert body == []
```

`two_notes_fixture` was added alongside `note_fixture` in Task 3; no new fixture is needed here.

- [ ] **Step 2: Run them and watch them fail**

Run: `docker compose exec -T api pytest tests/test_notes_api.py -k list -q`
Expected: FAIL — 405 or 404, because only `/notes/{note_id}` is registered.

- [ ] **Step 3: Add the queries**

In `backend/app/repositories/notes.py`, add to `NoteRepository`:

```python
    async def recent_for_user(self, user_id: uuid.UUID, limit: int = 50) -> list[Note]:
        """The user's most recent notes.

        Bounded rather than paginated: this list exists so someone can get back to a
        note they just wrote, and past fifty rows a list is the wrong tool. The
        roster with its filters is phase 7.
        """
        return list(
            (
                await self.session.execute(
                    select(Note)
                    .where(Note.user_id == user_id)
                    .order_by(Note.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def flag_counts(
        self, note_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[FlagSeverity, int]]:
        """Flag counts per note, per severity, computed in SQL.

        The API contract promises these aggregations are SQL rather than Python
        loops, and that promise is not keepable against a JSONB array at volume --
        which is the whole reason note_flags exists alongside notes.flags.
        """
        if not note_ids:
            return {}

        rows = (
            await self.session.execute(
                select(NoteFlag.note_id, NoteFlag.severity, func.count())
                .where(NoteFlag.note_id.in_(note_ids))
                .group_by(NoteFlag.note_id, NoteFlag.severity)
            )
        ).all()

        counts: dict[uuid.UUID, dict[FlagSeverity, int]] = {}
        for note_id, severity, count in rows:
            counts.setdefault(note_id, {})[severity] = count
        return counts
```

Add `func` to the `sqlalchemy` import and `FlagSeverity` to the enums import.

- [ ] **Step 4: Add the list schema**

In `backend/app/schemas/note.py`:

```python
class NoteListItem(BaseModel):
    id: uuid.UUID
    visit_id: uuid.UUID
    format: NoteFormat
    client_label: str | None
    visit_date: str | None
    edited: bool
    signed_at: datetime | None
    # Keyed by severity. Absent severities are omitted rather than sent as zero, so
    # the client renders what exists instead of three counters that are mostly noise.
    flag_counts: dict[FlagSeverity, int]
```

- [ ] **Step 5: Add the service method**

In `backend/app/services/notes.py`, add to `NoteService`:

```python
    async def list(self, user: User) -> list[NoteListItem]:
        notes = await NoteRepository(self.session).recent_for_user(user.id)
        counts = await NoteRepository(self.session).flag_counts([note.id for note in notes])
        return [
            NoteListItem(
                id=note.id,
                visit_id=note.visit_id,
                format=note.format,
                # Read from the note's own header rather than joined from the visit:
                # this is the label as it was written into the note, which is what a
                # reader is looking for when scanning the list.
                client_label=note.visit_details.get("client_label"),
                visit_date=note.visit_details.get("visit_date"),
                edited=note.edited,
                signed_at=note.signed_at,
                flag_counts=counts.get(note.id, {}),
            )
            for note in notes
        ]
```

Import `NoteListItem` at the top of the file.

- [ ] **Step 6: Add the route**

In `backend/app/api/v1/routers/notes.py`, **above** the `/{note_id}` route so the literal path is matched first:

```python
@router.get("", response_model=list[NoteListItem])
async def list_notes(user: CurrentUser, session: SessionDep) -> list[NoteListItem]:
    return await NoteService(session).list(user)
```

Import `NoteListItem`.

- [ ] **Step 7: Run the tests**

Run: `docker compose exec -T api pytest tests/test_notes_api.py -q && docker compose exec -T api ruff check . && docker compose exec -T api mypy app`
Expected: PASS, exit 0.

- [ ] **Step 8: Commit**

```bash
git add backend/app/repositories/notes.py backend/app/schemas/note.py \
        backend/app/services/notes.py backend/app/api/v1/routers/notes.py \
        backend/tests/test_notes_api.py backend/tests/conftest.py
git commit -m "feat: list recent notes with flag counts"
```

---

### Task 5: Version-checked PATCH

**Files:**
- Modify: `backend/app/schemas/note.py`
- Modify: `backend/app/repositories/notes.py`
- Modify: `backend/app/services/notes.py`
- Modify: `backend/app/api/v1/routers/notes.py`
- Test: `backend/tests/test_note_editing.py` (create)

**Interfaces:**
- Consumes: `validate_sections_structure` (Task 2), `NoteService` (Task 3).
- Produces: `NoteUpdate` in `app/schemas/note.py`; `NoteService.update(note_id: uuid.UUID, user: User, payload: NoteUpdate) -> NoteRead` raising `NoteNotFoundError`, `StaleNoteVersionError(current_version: int)`, `NoteStructureError(message: str)`; `PATCH /api/v1/notes/{note_id}` returning 200, 404, 409 or 422.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_note_editing.py`:

```python
"""Correcting a generated note.

The version check is the whole point: a supervisor opening a note in the review queue
while its author edits it on their phone must not silently discard one of them.
"""

import uuid

from httpx import AsyncClient

PASSWORD = "a-sufficiently-long-password"


def _email() -> str:
    return f"{uuid.uuid4().hex}@visitnote-testing.com"


async def _sections(client: AsyncClient, note_id: uuid.UUID, headers: dict) -> dict:
    return (await client.get(f"/api/v1/notes/{note_id}", headers=headers)).json()


async def test_editing_a_section_bumps_the_version_and_marks_it_edited(
    client: AsyncClient, note_fixture
) -> None:
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)
    sections = body["sections"]
    first_key = body["template"]["sections"][0]["key"]
    sections[first_key] = "Corrected by the nurse."

    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": body["version"], "sections": sections},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["version"] == body["version"] + 1
    assert updated["edited"] is True
    assert updated["sections"][first_key] == "Corrected by the nurse."


async def test_a_stale_version_is_refused(client: AsyncClient, note_fixture) -> None:
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)
    stale = body["version"]
    await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": stale, "sections": body["sections"]},
    )

    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": stale, "sections": body["sections"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["current_version"] == stale + 1


async def test_a_refused_edit_leaves_the_note_alone(
    client: AsyncClient, note_fixture
) -> None:
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)
    first_key = body["template"]["sections"][0]["key"]
    original = body["sections"][first_key]
    sections = dict(body["sections"])
    sections[first_key] = "Should not be stored."

    await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": body["version"] - 1, "sections": sections},
    )

    after = await _sections(client, note.id, headers)
    assert after["sections"][first_key] == original


async def test_an_unknown_section_key_is_rejected(
    client: AsyncClient, note_fixture
) -> None:
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)
    sections = dict(body["sections"])
    sections["invented_section"] = "text"

    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": body["version"], "sections": sections},
    )

    assert response.status_code == 422
    assert "invented_section" in str(response.json()["detail"])


async def test_a_nurses_own_words_are_never_refused(
    client: AsyncClient, note_fixture
) -> None:
    # BANNED_PHRASES governs how the model writes. The author of a clinical record is
    # not subject to it.
    note, headers = note_fixture
    body = await _sections(client, note.id, headers)
    sections = dict(body["sections"])
    sections[body["template"]["sections"][0]["key"]] = "routine visit"

    response = await client.patch(
        f"/api/v1/notes/{note.id}",
        headers=headers,
        json={"version": body["version"], "sections": sections},
    )

    assert response.status_code == 200


async def test_editing_another_users_note_is_not_found(
    client: AsyncClient, note_fixture
) -> None:
    note, _ = note_fixture
    other = (
        await client.post(
            "/api/v1/auth/register", json={"email": _email(), "password": PASSWORD}
        )
    ).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}

    response = await client.patch(
        f"/api/v1/notes/{note.id}", headers=headers, json={"version": 1, "sections": {}}
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run them and watch them fail**

Run: `docker compose exec -T api pytest tests/test_note_editing.py -q`
Expected: FAIL — 405 Method Not Allowed, because no PATCH route exists.

- [ ] **Step 3: Add the update schema**

In `backend/app/schemas/note.py`:

```python
class NoteUpdate(BaseModel):
    """A correction to a generated note.

    `extra="forbid"` is a security control rather than tidiness: version, edited,
    review_status, signed_at, format and the provenance fields are not the client's
    to set, and rejecting unknown fields makes a future column client-writable by
    accident impossible to write.
    """

    model_config = ConfigDict(extra="forbid")

    # The version the client loaded. A mismatch means someone else has written since,
    # and the edit is refused rather than applied on top of work it never saw.
    version: int
    visit_details: dict[str, Any] | None = None
    sections: dict[str, SectionValue] | None = None
```

- [ ] **Step 4: Add the conditional update to the repository**

In `backend/app/repositories/notes.py`, add to `NoteRepository`:

```python
    async def update_if_current(
        self,
        *,
        note: Note,
        expected_version: int,
        visit_details: dict[str, Any] | None,
        sections: dict[str, Any] | None,
    ) -> bool:
        """Apply an edit only if nobody has written since the client read.

        The check is a WHERE clause on the UPDATE rather than a read-then-write, so
        two concurrent saves cannot both pass the comparison before either commits.
        """
        values: dict[str, Any] = {
            "version": Note.version + 1,
            "edited": True,
        }
        if visit_details is not None:
            values["visit_details"] = visit_details
        if sections is not None:
            values["sections"] = sections

        result = await self.session.execute(
            update(Note)
            .where(Note.id == note.id, Note.version == expected_version)
            .values(**values)
        )
        await self.session.commit()
        return result.rowcount == 1
```

Add `update` to the `sqlalchemy` import and `Any` to the typing import.

- [ ] **Step 5: Add the service rules**

In `backend/app/services/notes.py`, add the errors and the method:

```python
class StaleNoteVersionError(Exception):
    """Someone else has written to this note since the client read it."""

    def __init__(self, current_version: int) -> None:
        super().__init__(f"Note has moved on to version {current_version}")
        self.current_version = current_version


class NoteStructureError(Exception):
    """The edit does not fit the template's shape."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
```

and to `NoteService`:

```python
    async def update(self, note_id: uuid.UUID, user: User, payload: NoteUpdate) -> NoteRead:
        notes = NoteRepository(self.session)
        note = await notes.get_for_user(note_id, user.id)
        if note is None:
            raise NoteNotFoundError

        if payload.sections is not None:
            spec = TemplateSpec.from_template(note.template)
            try:
                # Structure only. BANNED_PHRASES is not applied: it governs how the
                # model writes, and a nurse is the author of a clinical record.
                validate_sections_structure(payload.sections, spec)
            except NoteValidationError as exc:
                raise NoteStructureError(str(exc)) from exc

        applied = await notes.update_if_current(
            note=note,
            expected_version=payload.version,
            visit_details=payload.visit_details,
            sections=payload.sections,
        )
        if not applied:
            fresh = await notes.get_for_user(note_id, user.id)
            assert fresh is not None  # it existed a moment ago and nothing deletes notes here
            raise StaleNoteVersionError(fresh.version)

        updated = await notes.get_for_user(note_id, user.id)
        assert updated is not None
        return self._read(updated)
```

Import `validate_sections_structure` and `NoteValidationError` from `app.llm.contract`, and `NoteUpdate` from `app.schemas.note`.

- [ ] **Step 6: Add the route**

In `backend/app/api/v1/routers/notes.py`:

```python
@router.patch("/{note_id}", response_model=NoteRead)
async def update_note(
    note_id: uuid.UUID, payload: NoteUpdate, user: CurrentUser, session: SessionDep
) -> NoteRead:
    try:
        return await NoteService(session).update(note_id, user, payload)
    except NoteNotFoundError as exc:
        raise _NOT_FOUND from exc
    except StaleNoteVersionError as exc:
        # The current version and nothing else: the client refetches, so there is one
        # code path that renders a note rather than two that could disagree.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "This note was changed somewhere else.",
                    "current_version": exc.current_version},
        ) from exc
    except NoteStructureError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message
        ) from exc
```

Import `NoteUpdate`, `StaleNoteVersionError` and `NoteStructureError`.

- [ ] **Step 7: Run the tests**

Run: `docker compose exec -T api pytest tests/test_note_editing.py tests/test_notes_api.py -q && docker compose exec -T api ruff check . && docker compose exec -T api mypy app`
Expected: PASS, exit 0.

- [ ] **Step 8: Regenerate the client types and commit**

```bash
cd web && npm run generate:api && cd ..
git add backend/app/schemas/note.py backend/app/repositories/notes.py \
        backend/app/services/notes.py backend/app/api/v1/routers/notes.py \
        backend/tests/test_note_editing.py web/src/api/schema.d.ts
git commit -m "feat: version-checked note editing"
```

---

### Task 6: Web — note queries and the flags panel

**Files:**
- Create: `web/src/lib/note.ts`
- Modify: `web/src/lib/queryClient.ts`
- Create: `web/src/components/note/FlagsPanel.tsx`
- Test: `web/src/components/note/FlagsPanel.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /api/v1/notes/{id}` (Task 3), `PATCH /api/v1/notes/{id}` (Task 5).
- Produces: `queryKeys.note(noteId)`, `queryKeys.notes()`; `useNote(noteId)`, `useNotes()`, `useSaveNote(noteId)` in `lib/note.ts`; `type Note = components['schemas']['NoteRead']`, `type SectionSpec = components['schemas']['SectionSpecRead']`, `type NoteFlag = components['schemas']['NoteFlagRead']`; `<FlagsPanel flags={…} />`.

- [ ] **Step 1: Write the failing test**

Create `web/src/components/note/FlagsPanel.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { FlagsPanel } from './FlagsPanel'

const FLAGS = [
  { code: 'MISSING_VITALS_TIME', message: 'Vitals with no time.', severity: 'warning' },
  { code: 'MISSING_RESPONSE', message: 'An action with no response.', severity: 'critical' },
] as const

describe('FlagsPanel', () => {
  it('puts critical findings above warnings', () => {
    // A nurse working down the list should meet the thing that matters first.
    render(<FlagsPanel flags={[...FLAGS]} />)

    const codes = screen.getAllByTestId('flag-code').map((node) => node.textContent)
    expect(codes).toEqual(['MISSING_RESPONSE', 'MISSING_VITALS_TIME'])
  })

  it('says so plainly when the model found nothing', () => {
    render(<FlagsPanel flags={[]} />)

    expect(screen.getByText(/no findings/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd web && npx vitest run src/components/note/FlagsPanel.test.tsx`
Expected: FAIL — cannot resolve `./FlagsPanel`.

- [ ] **Step 3: Add the query keys**

In `web/src/lib/queryClient.ts`, inside `queryKeys`, after `profile`:

```ts
  notes: () => ['notes'] as const,
  // Nested under the collection key so invalidating ['notes'] after a save also
  // refreshes the list's flag counts and edited markers.
  note: (noteId: string) => ['notes', noteId] as const,
```

- [ ] **Step 4: Write the queries**

Create `web/src/lib/note.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { detailMessage } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryClient'

export type Note = components['schemas']['NoteRead']
export type NoteListItem = components['schemas']['NoteListItem']
export type SectionSpec = components['schemas']['SectionSpecRead']
export type NoteFlag = components['schemas']['NoteFlagRead']
export type SectionValue = Note['sections'][string]

/** Thrown when the note moved on while it was open. Carries where it moved to. */
export class NoteConflictError extends Error {
  constructor(readonly currentVersion: number) {
    super('This note was changed somewhere else.')
    this.name = 'NoteConflictError'
  }
}

export function useNote(noteId: string) {
  return useQuery({
    queryKey: queryKeys.note(noteId),
    queryFn: async (): Promise<Note> => {
      const { data, response } = await api.GET('/api/v1/notes/{note_id}', {
        params: { path: { note_id: noteId } },
      })
      if (!response.ok || !data) throw new Error('Could not load this note')
      return data
    },
    // The editor holds a draft derived from this. Refetching underneath an open form
    // would replace what the nurse is typing with what the server last sent.
    staleTime: Infinity,
  })
}

export function useNotes() {
  return useQuery({
    queryKey: queryKeys.notes(),
    queryFn: async (): Promise<NoteListItem[]> => {
      const { data, response } = await api.GET('/api/v1/notes')
      if (!response.ok || !data) throw new Error('Could not load your notes')
      return data
    },
  })
}

export function useSaveNote(noteId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: components['schemas']['NoteUpdate']): Promise<Note> => {
      const { data, error, response } = await api.PATCH('/api/v1/notes/{note_id}', {
        params: { path: { note_id: noteId } },
        body,
      })
      if (response.status === 409) {
        const detail = (error as { detail?: { current_version?: number } } | undefined)?.detail
        throw new NoteConflictError(detail?.current_version ?? 0)
      }
      if (error ?? !data) throw new Error(detailMessage(error, 'Could not save this note'))
      return data
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.note(noteId), saved)
      // The list shows edited state and flag counts, so it is stale the moment a
      // save lands.
      void queryClient.invalidateQueries({ queryKey: queryKeys.notes() })
    },
  })
}
```

- [ ] **Step 5: Write the panel**

Create `web/src/components/note/FlagsPanel.tsx`:

```tsx
import type { NoteFlag } from '@/lib/note'

/**
 * Ordered by what a reviewer should deal with first, not by the order the model
 * emitted them. Severity comes from the template rather than the model, so this
 * ordering is a property of the note format and not of a generation.
 */
const SEVERITY_ORDER: Record<NoteFlag['severity'], number> = {
  critical: 0,
  warning: 1,
  info: 2,
}

const SEVERITY_STYLE: Record<NoteFlag['severity'], string> = {
  critical: 'border-critical/50',
  warning: 'border-line',
  info: 'border-line',
}

/**
 * What the model found, as a checklist.
 *
 * Flags do not change when a section is edited. They record what was true of the
 * generated note; re-evaluating them would mean writing deterministic checkers that
 * phase 5b's eval suite also needs, and a checker that gets a rule wrong silently
 * clears a real finding on a legal record.
 */
export function FlagsPanel({ flags }: { flags: NoteFlag[] }) {
  if (flags.length === 0) {
    return <p className="text-sm text-muted">No findings. Read it through anyway.</p>
  }

  const ordered = [...flags].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
  )

  return (
    <ul className="space-y-2">
      {ordered.map((flag) => (
        <li
          key={`${flag.severity}-${flag.code}-${flag.message}`}
          className={`rounded-md border p-3 ${SEVERITY_STYLE[flag.severity]}`}
        >
          <span data-testid="flag-code" className="block font-mono text-xs text-muted">
            {flag.code}
          </span>
          <span className="block text-sm">{flag.message}</span>
        </li>
      ))}
    </ul>
  )
}
```

- [ ] **Step 6: Run the test and the checks**

Run: `cd web && npx vitest run src/components/note/FlagsPanel.test.tsx && npm run typecheck && npm run lint`
Expected: PASS, exit 0, exit 0.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/note.ts web/src/lib/queryClient.ts web/src/components/note/
git commit -m "feat: note queries and the flags panel"
```

---

### Task 7: Web — schema-driven section fields

**Files:**
- Create: `web/src/components/note/SectionField.tsx`
- Create: `web/src/components/note/RepeatingSection.tsx`
- Create: `web/src/components/note/VisitDetailsFields.tsx`
- Test: `web/src/components/note/RepeatingSection.test.tsx` (create)

**Interfaces:**
- Consumes: `SectionSpec`, `SectionValue` (Task 6).
- Produces: `<SectionField section={SectionSpec} value={string | null} onChange={(next: string) => void} />`; `<RepeatingSection section={SectionSpec} entries={Array<Record<string, string | null>>} onChange={(next: Array<Record<string, string | null>>) => void} />`; `<VisitDetailsFields details={Record<string, unknown>} onChange={(key: string, value: string) => void} />`.

- [ ] **Step 1: Write the failing test**

Create `web/src/components/note/RepeatingSection.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { SectionSpec } from '@/lib/note'

import { RepeatingSection } from './RepeatingSection'

const SECTION: SectionSpec = {
  key: 'focus_entries',
  label: 'Focus entries',
  order: 2,
  description: 'One F-D-A-R entry per nursing focus charted this shift.',
  repeating: true,
  fields: [
    { key: 'focus', label: 'Focus', order: 1, description: '', repeating: false, fields: [] },
    { key: 'response', label: 'Response', order: 2, description: '', repeating: false, fields: [] },
  ],
}

const ENTRIES = [{ focus: 'Pain', response: 'Relieved to 3/10' }]

describe('RepeatingSection', () => {
  it('renders one card per stored entry, with a field per declared field', () => {
    render(<RepeatingSection section={SECTION} entries={ENTRIES} onChange={vi.fn()} />)

    expect(screen.getByDisplayValue('Pain')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Relieved to 3/10')).toBeInTheDocument()
  })

  it('adds an empty entry carrying every declared field', () => {
    // A nurse who charted three focuses when the model caught two has to be able to
    // add the third, or the repeating group is only half editable.
    const onChange = vi.fn()
    render(<RepeatingSection section={SECTION} entries={ENTRIES} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: /add focus entry/i }))

    expect(onChange).toHaveBeenCalledWith([...ENTRIES, { focus: '', response: '' }])
  })

  it('removes the entry the nurse asked to remove', () => {
    const onChange = vi.fn()
    const two = [...ENTRIES, { focus: 'Fever', response: 'Down to 37.2' }]
    render(<RepeatingSection section={SECTION} entries={two} onChange={onChange} />)

    fireEvent.click(screen.getAllByRole('button', { name: /remove/i })[1]!)

    expect(onChange).toHaveBeenCalledWith([ENTRIES[0]])
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd web && npx vitest run src/components/note/RepeatingSection.test.tsx`
Expected: FAIL — cannot resolve `./RepeatingSection`.

- [ ] **Step 3: Write the flat section field**

Create `web/src/components/note/SectionField.tsx`:

```tsx
import type { SectionSpec } from '@/lib/note'

/**
 * One prose section, labelled and described by the template.
 *
 * The description is the same sentence the prompt gave the model, shown to the nurse
 * as help text: the instruction the note was written against is also the best
 * statement of what belongs in the box.
 */
export function SectionField({
  section,
  value,
  onChange,
}: {
  section: SectionSpec
  value: string | null
  onChange: (next: string) => void
}) {
  const id = `section-${section.key}`
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="block text-sm font-medium">
        {section.label}
      </label>
      {section.description !== '' && (
        <p className="text-xs text-muted">{section.description}</p>
      )}
      <textarea
        id={id}
        rows={4}
        value={value ?? ''}
        onChange={(event) => { onChange(event.target.value) }}
        className="w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm"
      />
    </div>
  )
}
```

- [ ] **Step 4: Write the repeating section**

Create `web/src/components/note/RepeatingSection.tsx`:

```tsx
import type { SectionSpec } from '@/lib/note'

type Entry = Record<string, string | null>

/**
 * A section the format repeats -- FDAR's focus entries, and nothing else in any
 * current template.
 *
 * Generic over the schema rather than written for FDAR: a section is repeating
 * because its template row says `repeating: true`, and a future format that repeats
 * something else needs no code here. An added entry carries every declared field as
 * an empty string rather than omitting them, because the server rejects an entry
 * whose keys do not match the schema exactly -- a missing key and a field the author
 * left blank are different facts.
 */
export function RepeatingSection({
  section,
  entries,
  onChange,
}: {
  section: SectionSpec
  entries: Entry[]
  onChange: (next: Entry[]) => void
}) {
  const blank = (): Entry =>
    Object.fromEntries(section.fields.map((field) => [field.key, '']))

  const updateEntry = (index: number, key: string, value: string) => {
    onChange(entries.map((entry, i) => (i === index ? { ...entry, [key]: value } : entry)))
  }

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-medium">{section.label}</h3>
        {section.description !== '' && (
          <p className="text-xs text-muted">{section.description}</p>
        )}
      </div>

      {entries.map((entry, index) => (
        <div key={index} className="space-y-3 rounded-md border border-line p-3">
          <div className="flex items-baseline justify-between">
            <span className="text-xs text-muted">
              {section.label} {index + 1}
            </span>
            <button
              type="button"
              onClick={() => { onChange(entries.filter((_, i) => i !== index)) }}
              className="text-xs text-muted underline underline-offset-4"
            >
              Remove
            </button>
          </div>

          {section.fields.map((field) => {
            const id = `${section.key}-${index}-${field.key}`
            return (
              <div key={field.key} className="space-y-1">
                <label htmlFor={id} className="block text-xs font-medium">
                  {field.label}
                </label>
                <textarea
                  id={id}
                  rows={2}
                  value={entry[field.key] ?? ''}
                  onChange={(event) => { updateEntry(index, field.key, event.target.value) }}
                  className="w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm"
                />
              </div>
            )
          })}
        </div>
      ))}

      <button
        type="button"
        onClick={() => { onChange([...entries, blank()]) }}
        className="rounded-md border border-line px-3 py-2 text-sm"
      >
        Add {section.label.toLowerCase().replace(/ entries$/, ' entry')}
      </button>
    </div>
  )
}
```

The add button's accessible name must read "Add focus entry" for the test above: `"Focus entries".toLowerCase()` is `"focus entries"`, and the replace turns it into `"focus entry"`.

- [ ] **Step 5: Write the visit-details fields**

Create `web/src/components/note/VisitDetailsFields.tsx`:

```tsx
/**
 * The note's header: who, when, and the exact times.
 *
 * Editable, because the missing-times flags are decided from these fields rather
 * than by parsing prose -- a flag pointing at a read-only field is a flag that
 * cannot be cleared.
 */
const LABELS: Record<string, string> = {
  client_label: 'Care recipient',
  visit_date: 'Date',
  start_time: 'Start time',
  end_time: 'End time',
}

export function VisitDetailsFields({
  details,
  onChange,
}: {
  details: Record<string, unknown>
  onChange: (key: string, value: string) => void
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {Object.keys(LABELS).map((key) => {
        const id = `visit-detail-${key}`
        const value = details[key]
        return (
          <div key={key} className="space-y-1">
            <label htmlFor={id} className="block text-xs font-medium">
              {LABELS[key]}
            </label>
            <input
              id={id}
              value={typeof value === 'string' ? value : ''}
              onChange={(event) => { onChange(key, event.target.value) }}
              className="w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm"
            />
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 6: Run the tests and the checks**

Run: `cd web && npx vitest run src/components/note && npm run typecheck && npm run lint`
Expected: PASS, exit 0, exit 0.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/note/
git commit -m "feat: schema-driven section fields with repeating groups"
```

---

### Task 8: Web — the editor, saving, and conflict handling

**Files:**
- Create: `web/src/routes/NoteEditor.tsx`
- Modify: `web/src/routes/router.tsx`
- Modify: `web/src/routes/Processing.tsx`
- Test: `web/src/routes/NoteEditor.test.tsx` (create)

**Interfaces:**
- Consumes: `useNote`, `useSaveNote`, `NoteConflictError` (Task 6); `SectionField`, `RepeatingSection`, `VisitDetailsFields`, `FlagsPanel` (Tasks 6–7).
- Produces: route `/notes/:noteId` rendering `<NoteEditor />`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/routes/NoteEditor.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

import { NoteEditor } from './NoteEditor'

vi.mock('@/api/client', () => ({ api: { GET: vi.fn(), PATCH: vi.fn() } }))

const NOTE_ID = '22222222-2222-2222-2222-222222222222'

function note(overrides: Record<string, unknown> = {}) {
  return {
    id: NOTE_ID,
    visit_id: '33333333-3333-3333-3333-333333333333',
    format: 'fdar',
    version: 1,
    edited: false,
    review_status: 'unreviewed',
    signed_at: null,
    visit_details: { client_label: 'Bed 12', visit_date: '2026-09-23',
                     start_time: '22:00', end_time: '06:00' },
    sections: { shift_details: 'Night shift.', focus_entries: [{ focus: 'Pain', response: '' }] },
    flags: [{ code: 'MISSING_RESPONSE', message: 'No response charted.', severity: 'critical' }],
    template: {
      jurisdiction: 'PH', format: 'fdar', version: 1, name: 'PH FDAR',
      sections: [
        { key: 'shift_details', label: 'Shift details', order: 1, description: '',
          repeating: false, fields: [] },
        { key: 'focus_entries', label: 'Focus entries', order: 2, description: '',
          repeating: true, fields: [
            { key: 'focus', label: 'Focus', order: 1, description: '', repeating: false, fields: [] },
            { key: 'response', label: 'Response', order: 2, description: '', repeating: false, fields: [] },
          ] },
      ],
    },
    ...overrides,
  }
}

function renderEditor() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/notes/${NOTE_ID}`]}>
        <Routes>
          <Route path="/notes/:noteId" element={<NoteEditor />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  useAuthStore.getState().setSession({ accessToken: 'a', refreshToken: 'r' })
  vi.mocked(api.GET).mockReset()
  vi.mocked(api.PATCH).mockReset()
  vi.mocked(api.GET).mockResolvedValue({
    data: note(), response: new Response(null, { status: 200 }),
  } as never)
})

describe('NoteEditor', () => {
  it('renders sections in the order the template declares', async () => {
    renderEditor()

    const headings = await screen.findAllByText(/shift details|focus entries/i)
    expect(headings[0]?.textContent).toMatch(/shift details/i)
  })

  it('sends the version the note was loaded at', async () => {
    // Without it the server cannot tell an edit made against current state from one
    // made against a copy that is three saves old.
    vi.mocked(api.PATCH).mockResolvedValue({
      data: note({ version: 2, edited: true }),
      response: new Response(null, { status: 200 }),
    } as never)

    renderEditor()
    fireEvent.click(await screen.findByRole('button', { name: /save/i }))

    await waitFor(() => { expect(api.PATCH).toHaveBeenCalled() })
    const body = (vi.mocked(api.PATCH).mock.calls as unknown as [string, { body: { version: number } }][])[0]![1].body
    expect(body.version).toBe(1)
  })

  it('offers a reload rather than choosing which version survives', async () => {
    vi.mocked(api.PATCH).mockResolvedValue({
      error: { detail: { message: 'changed', current_version: 4 } } as unknown as never,
      response: new Response(null, { status: 409 }),
    })

    renderEditor()
    fireEvent.click(await screen.findByRole('button', { name: /save/i }))

    expect(await screen.findByRole('button', { name: /reload/i })).toBeInTheDocument()
  })

  it('shows what the model flagged', async () => {
    renderEditor()

    expect(await screen.findByText('No response charted.')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd web && npx vitest run src/routes/NoteEditor.test.tsx`
Expected: FAIL — cannot resolve `./NoteEditor`.

- [ ] **Step 3: Write the editor**

Create `web/src/routes/NoteEditor.tsx`:

```tsx
import { useState } from 'react'
import { useParams } from 'react-router'

import { FlagsPanel } from '@/components/note/FlagsPanel'
import { RepeatingSection } from '@/components/note/RepeatingSection'
import { SectionField } from '@/components/note/SectionField'
import { VisitDetailsFields } from '@/components/note/VisitDetailsFields'
import { NoteConflictError, useNote, useSaveNote, type Note, type SectionValue } from '@/lib/note'

type Entry = Record<string, string | null>

interface Draft {
  version: number
  visitDetails: Record<string, unknown>
  sections: Record<string, SectionValue>
}

function draftOf(note: Note): Draft {
  return {
    // Captured with the draft, not read at save time: this is the version the nurse
    // actually saw, which is the thing the server needs to compare against.
    version: note.version,
    visitDetails: { ...note.visit_details },
    sections: { ...note.sections },
  }
}

/**
 * Read a generated note and correct it.
 *
 * Every section on this screen comes from the template's section schema. There is no
 * FDAR component and no SOAPIE component, because a third format is a seeded row and
 * a prompt module -- if a component here ever needs to know which format it is
 * rendering, that property has been lost.
 */
export function NoteEditor() {
  const { noteId = '' } = useParams()
  const { data: note, isPending, refetch } = useNote(noteId)
  const save = useSaveNote(noteId)
  const [draft, setDraft] = useState<Draft | null>(null)

  if (isPending) return <p className="text-sm text-muted">Loading the note…</p>
  if (note === undefined) return <p className="text-sm text-critical">Could not load this note.</p>

  const current = draft ?? draftOf(note)
  const conflict = save.error instanceof NoteConflictError ? save.error : null

  const setSection = (key: string, value: SectionValue) => {
    setDraft({ ...current, sections: { ...current.sections, [key]: value } })
  }

  return (
    <section className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{note.template.name}</h1>
        <p className="text-xs text-muted">
          Version {note.version}
          {note.edited ? ' · edited' : ' · as generated'}
        </p>
      </header>

      <FlagsPanel flags={note.flags} />

      <VisitDetailsFields
        details={current.visitDetails}
        onChange={(key, value) => {
          setDraft({ ...current, visitDetails: { ...current.visitDetails, [key]: value } })
        }}
      />

      {note.template.sections.map((section) =>
        section.repeating ? (
          <RepeatingSection
            key={section.key}
            section={section}
            entries={(current.sections[section.key] as Entry[] | null) ?? []}
            onChange={(next) => { setSection(section.key, next) }}
          />
        ) : (
          <SectionField
            key={section.key}
            section={section}
            value={(current.sections[section.key] as string | null) ?? ''}
            onChange={(next) => { setSection(section.key, next) }}
          />
        ),
      )}

      {conflict !== null ? (
        <div className="space-y-2 rounded-md border border-critical/50 p-4">
          <p className="text-sm">
            This note was changed somewhere else — it is now at version{' '}
            {conflict.currentVersion}. Saving now would discard that change.
          </p>
          <button
            type="button"
            onClick={() => {
              setDraft(null)
              save.reset()
              void refetch()
            }}
            className="rounded-md border border-line px-3 py-2 text-sm"
          >
            Reload the note
          </button>
        </div>
      ) : (
        save.isError && <p className="text-sm text-critical">{save.error.message}</p>
      )}

      <button
        type="button"
        disabled={save.isPending}
        onClick={() => {
          save.mutate({
            version: current.version,
            visit_details: current.visitDetails,
            sections: current.sections,
          })
        }}
        className="rounded-md bg-accent px-4 py-2 text-surface disabled:opacity-50"
      >
        {save.isPending ? 'Saving…' : 'Save'}
      </button>
    </section>
  )
}
```

- [ ] **Step 4: Register the route**

In `web/src/routes/router.tsx`, inside the `RequireOnboarding` children, after the processing route:

```tsx
              { path: 'notes/:noteId', element: <NoteEditor /> },
```

with `import { NoteEditor } from '@/routes/NoteEditor'` added alongside the other route imports.

- [ ] **Step 5: Send the processing screen to the note**

In `web/src/routes/Processing.tsx`, replace the finished-and-not-failed block (it currently offers only "Record another visit"):

```tsx
      {finished && !failed && (
        <div className="space-y-2 text-sm">
          {data.note_id !== null && (
            <p>
              {/* The note is why the nurse recorded anything. It goes first, and
                  "record another" stops being the only thing a finished visit
                  offers. */}
              <Link to={`/notes/${data.note_id}`} className="underline">
                Read and correct your note
              </Link>
            </p>
          )}
          <p>
            <Link to="/new" className="underline">
              Record another visit
            </Link>
          </p>
        </div>
      )}
```

- [ ] **Step 6: Run the tests and the checks**

Run: `cd web && npx vitest run && npm run typecheck && npm run lint`
Expected: PASS for every suite, exit 0, exit 0.

- [ ] **Step 7: Commit**

```bash
git add web/src/routes/NoteEditor.tsx web/src/routes/NoteEditor.test.tsx \
        web/src/routes/router.tsx web/src/routes/Processing.tsx
git commit -m "feat: the schema-driven note editor"
```

---

### Task 9: Web — the recent notes list

**Files:**
- Create: `web/src/routes/Notes.tsx`
- Modify: `web/src/routes/router.tsx`
- Modify: `web/src/components/AppLayout.tsx`
- Test: `web/src/routes/Notes.test.tsx` (create)

**Interfaces:**
- Consumes: `useNotes` (Task 6).
- Produces: route `/notes` rendering `<Notes />`; a "Notes" entry in the header navigation.

- [ ] **Step 1: Write the failing test**

Create `web/src/routes/Notes.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

import { Notes } from './Notes'

vi.mock('@/api/client', () => ({ api: { GET: vi.fn() } }))

const ITEM = {
  id: '22222222-2222-2222-2222-222222222222',
  visit_id: '33333333-3333-3333-3333-333333333333',
  format: 'fdar',
  client_label: 'Bed 12',
  visit_date: '2026-09-23',
  edited: false,
  signed_at: null,
  flag_counts: { critical: 2 },
}

function renderNotes() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Notes />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  useAuthStore.getState().setSession({ accessToken: 'a', refreshToken: 'r' })
  vi.mocked(api.GET).mockReset()
})

describe('Notes', () => {
  it('lists a note with its label, date and critical count', async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: [ITEM], response: new Response(null, { status: 200 }),
    } as never)

    renderNotes()

    expect(await screen.findByText('Bed 12')).toBeInTheDocument()
    expect(screen.getByText(/2 critical/i)).toBeInTheDocument()
  })

  it('says what to do when there is nothing yet', async () => {
    // An empty list that says nothing reads like a failure to load.
    vi.mocked(api.GET).mockResolvedValue({
      data: [], response: new Response(null, { status: 200 }),
    } as never)

    renderNotes()

    expect(await screen.findByText(/record your first/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd web && npx vitest run src/routes/Notes.test.tsx`
Expected: FAIL — cannot resolve `./Notes`.

- [ ] **Step 3: Write the list**

Create `web/src/routes/Notes.tsx`:

```tsx
import { Link } from 'react-router'

import { useNotes, type NoteListItem } from '@/lib/note'

/** Severities worth a badge, most serious first. */
const SEVERITIES = ['critical', 'warning'] as const

function summary(item: NoteListItem): string {
  const parts = SEVERITIES.flatMap((severity) => {
    const count = item.flag_counts[severity] ?? 0
    return count > 0 ? [`${count} ${severity}`] : []
  })
  return parts.length === 0 ? 'No findings' : parts.join(' · ')
}

/**
 * A way back to your own work.
 *
 * Deliberately not the phase 7 roster: no agency scope, no review queue, no charts.
 * It exists because a nurse closes the tab and the note they just recorded should
 * not be reachable only by a URL they did not keep.
 */
export function Notes() {
  const { data: notes, isPending } = useNotes()

  if (isPending) return <p className="text-sm text-muted">Loading your notes…</p>

  if (notes === undefined) {
    return <p className="text-sm text-critical">Could not load your notes.</p>
  }

  if (notes.length === 0) {
    return (
      <section className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">Notes</h1>
        <p className="text-sm text-muted">
          Nothing here yet. <Link to="/new" className="underline underline-offset-4">
            Record your first note
          </Link>.
        </p>
      </section>
    )
  }

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Notes</h1>
      <ul className="divide-y divide-line">
        {notes.map((item) => (
          <li key={item.id}>
            <Link to={`/notes/${item.id}`} className="flex items-baseline justify-between gap-4 py-3">
              <span>
                <span className="block text-sm">{item.client_label ?? 'Unlabelled'}</span>
                <span className="block text-xs text-muted">
                  {item.visit_date ?? '—'} · {item.format}
                  {item.edited ? ' · edited' : ''}
                  {item.signed_at !== null ? ' · signed' : ''}
                </span>
              </span>
              <span className="text-xs text-muted">{summary(item)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
```

- [ ] **Step 4: Register the route and the nav entry**

In `web/src/routes/router.tsx`, inside the `RequireOnboarding` children:

```tsx
              { path: 'notes', element: <Notes /> },
```

placed **before** `notes/:noteId`, with `import { Notes } from '@/routes/Notes'` added.

In `web/src/components/AppLayout.tsx`, add between the "New note" and "Settings" links:

```tsx
          <NavLink to="/notes" className={linkClass}>Notes</NavLink>
```

- [ ] **Step 5: Run everything**

Run: `cd web && npx vitest run && npm run typecheck && npm run lint`
Expected: PASS for every suite, exit 0, exit 0.

- [ ] **Step 6: Run the full backend suite and the contract check**

Run:
```bash
docker compose exec -T api ruff check . && docker compose exec -T api mypy app && docker compose exec -T api pytest -q
```
Expected: exit 0, no issues, all tests pass.

- [ ] **Step 7: Commit**

```bash
git add web/src/routes/Notes.tsx web/src/routes/Notes.test.tsx \
        web/src/routes/router.tsx web/src/components/AppLayout.tsx
git commit -m "feat: recent notes list"
```

---

## Out of scope for this phase

Sign-off lock, WeasyPrint PDF export, and moving the disclaimer onto `note_templates` — all Phase 5.2. **5.2 must add the signed-note edit lock in the same change that adds sign-off**: no guard is written here because nothing in this phase can set `signed_at`, and a check against a state this branch cannot produce would be testing a hypothetical.

No flag re-evaluation, no review queue, no agency roster, no share links, no transcript display.
