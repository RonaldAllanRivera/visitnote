# The test suite has no isolation, and `alembic downgrade` pays for it

Pre-existing, predates Phase 4b. Two attempts to patch around it have now failed, so it is
recorded here as its own piece of work rather than chased a third time.

## What happens

`backend/tests/conftest.py` runs tests against real PostgreSQL and **commits** — by design,
and the fixture's docstring gives good reasons (cross-tenant isolation, aggregation
correctness, unique constraints, and TIMESTAMPTZ behaviour across a DST boundary either do
not exist or behave differently in SQLite). What it does not have is any per-test rollback
or truncation, so every run leaves its rows behind. A long-lived development database
currently holds thousands of accounts.

Since the Philippine templates were seeded, some of that residue is visits and notes
recorded as `format='fdar'`. Migration `0011`'s downgrade deliberately refuses while such
rows exist, because `fdar` has no representation below `0008` where the two-value
`note_format` ENUM is restored, and remapping a charted format or deleting a clinical
record is not a migration's decision to make. After a full suite run:

```
visits with note_format='fdar'   151
notes  with format='fdar'         15
```

so `alembic downgrade base` refuses — correctly, and with an actionable message.

## Why patching it per-file does not work

Two rounds have been tried: an autouse cleanup fixture in `tests/test_pipeline.py`, then
another in `tests/test_visits.py`. Rows still accumulate, because any test that creates a
PH account and a visit produces them, and new test files will keep doing so. It is
whack-a-mole, and each patch makes the suite look isolated without being isolated.

## What is actually true today

- **CI is genuinely green.** Its migration steps run on a fresh database before `pytest`,
  so there is no residue when the round-trip is verified.
- **A developer's remedy is a clean database**, not a code change. Either drop and recreate
  the development database, or verify migrations against a throwaway one:
  ```
  docker compose exec -T postgres psql -U visitnote -d postgres -c "CREATE DATABASE scratch;"
  docker compose run --rm -e DATABASE_URL="postgresql+asyncpg://visitnote:visitnote@postgres:5432/scratch" \
    api sh -c 'alembic upgrade head && alembic check && alembic downgrade base'
  ```
- **The guard refusing is the guard working.** A database holding data you care about
  *should* refuse to roll back past the point where that data stops being representable.

## The durable fix, when it is worth doing

Give the suite real isolation. The obvious candidate is a transaction per test with a
rollback, which is the standard approach — but note that it is not free here: the pipeline
task deliberately takes its own session from its arq context, so anything relying on
committed cross-session state would need handling. That is why this is its own task and
not a line in someone else's fix wave.

A cheaper interim step, if the full fix is deferred: a session-scoped teardown that
truncates the tables the suite writes, leaving the seeded `note_templates` rows intact.
