# Model/migration drift — `alembic check` cannot gate CI yet

Found while adding an `alembic check` step to CI in Phase 4c (Finding 6's companion).
Reproduced on a **completely fresh database**, so this is not dev-database residue.

The step was added as specified and **it fails**. `alembic check` reports 12 drifts, none
of them the naming defect Finding 6 described. All predate Phase 4b.

## Why it matters

Autogenerate is the normal way to write a migration. Against this drift it proposes
spurious changes — including dropping a live unique constraint on `users.email`. Finding 6
was one instance of exactly this class and it survived a full phase precisely because
nothing checked. The guard is worth having; it just cannot pass today.

## 1. Eleven `modify_default` drifts

The models declare Python-side `default=`; the migrations created `server_default=`.
Alembic sees a server default in the database that the model does not declare, and
proposes removing it. The fix is mechanical: give each model column a `server_default`
matching what its migration created.

| Table | Column | Type |
|---|---|---|
| `clients` | `is_active` | boolean |
| `notes` | `version` | integer |
| `notes` | `edited` | boolean |
| `notes` | `review_status` | enum `review_status` |
| `processing_jobs` | `stage` | enum `job_stage` |
| `processing_jobs` | `status` | enum `job_status` |
| `processing_jobs` | `attempts` | integer |
| `users` | `timezone` | varchar(64) |
| `users` | `is_staff` | boolean |
| `users` | `is_demo` | boolean |
| `users` | `is_active` | boolean |

Note that Phase 4b's own new columns do **not** appear here, but not for one shared
reason. `users.jurisdiction` declares both `default=` and `server_default=`, matching
migration `0007`, which keeps `server_default='US'` permanently — that is the pattern
the eleven-column fix above copies. `visits.jurisdiction` and `note_templates.jurisdiction`
are clean on the opposite pattern: migrations `0009` and `0010` each add a
`server_default` only to backfill existing rows, then drop it in the same migration, so
neither column carries one at rest — the model declaring no default matches a database
that, deliberately, has none either. Copying the `users.jurisdiction` pattern onto these
two would reintroduce a server default the migrations remove on purpose, so an insert
with no jurisdiction could pass silently as `'US'` instead of failing loudly.

## 2. One `remove_constraint` on `users.email`

`app/models/user.py` declares `unique=True` on the column, which yields a constraint whose
name does not match what migration `0003` created. Same root cause as Finding 6 and as the
`note_templates` fix: `app/models/base.py`'s `uq` convention is
`"uq_%(table_name)s_%(column_0_N_name)s"`, which interpolates the **columns**, not
`%(constraint_name)s`. Migration `0006`'s docstring already notes this as a
convention-versus-pre-convention mismatch.

## Decision required

The `alembic check` step is currently **in** `.github/workflows/ci.yml` and will fail on
merge. One of these has to happen before this branch lands:

1. **Fix the 12 drifts**, so the step passes and genuinely guards. Mechanical, bounded —
   eleven `server_default=` additions plus one constraint name. Touches five model files,
   no migration.
2. **Remove the step**, and do the drift work as its own piece later. Keeps CI green;
   loses the guard that would have caught Finding 6.

A third option — leaving the step non-blocking — is not recommended. A permanently-red
check trains everyone to ignore CI, which is worse than no check at all.

Option 1 is preferred: the work is small, well understood, and the guard has already
demonstrated its value by surfacing this.
