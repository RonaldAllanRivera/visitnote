# Phase 5.1 — Note review and the schema-driven editor

**Status:** approved design, not yet implemented.
**Spec:** [`visitnote-claude-code-prompt-v9.md`](../../../visitnote-claude-code-prompt-v9.md) — the Phase 5 row of Build Order, the PH · FDAR section, and Concurrency on note edits.

Phase 5 as the build document defines it covers review, section editing, sign-off and
PDF in one phase. It is split here: 5.1 is everything needed to *read and correct* a
note, 5.2 is everything needed to *finalise* one. The split is at the point where a
note stops being editable, which is also where the legal claims begin.

## Why this phase exists

The pipeline has been writing notes since Phase 4. Nothing in the product displays
one. A nurse records a shift, watches the processing screen reach a terminal state,
and arrives at a note id that no screen renders. Both jurisdictions reach the same
dead end, which is why this is the next slice rather than a later one.

## Goal

A nurse opens a note the pipeline wrote, reads it in the structure their format
prescribes, corrects what the model got wrong — including adding an FDAR focus entry
it missed — and saves, without two people silently overwriting each other.

---

## 1. Provenance: `notes.note_template_id`

The editor renders from `note_templates.section_schema`. The question the build
document deferred to this phase is how a note finds its schema.

> *"whether `notes` should also hold a `note_template_id` foreign key is a Phase 5
> question, where the editor needs the section schema anyway."*

**Decision: add the foreign key.**

`notes` currently records `format`, `prompt_version`, `llm_provider` and `model_id`,
but nothing identifying the template row. Template resolution picks
`is_active = true` with the highest `version`, so resolving at read time means that
the day a `(PH, fdar, 2)` row is seeded, every v1 note renders against v2's schema:
stored sections with no schema entry, schema entries with no stored section. The
`sections` JSONB is shaped by the template that wrote it, and nothing records which
one that was.

Two alternatives were considered and rejected:

- **Snapshot `section_schema` onto each note.** Self-contained, and immune to any
  change in the templates table. Rejected because it duplicates roughly two kilobytes
  per note, creates a second source of truth for a schema, and makes "which template
  produced this" something a reader infers rather than reads. Its extra safety only
  pays off if template rows mutate, and this codebase has deliberately built the
  opposite: `NoteTemplateRepository.get_active` documents promotion as inserting a row
  and deactivating the old one, "never an update that rewrites what already-generated
  notes were produced from". A row that cannot be rewritten is a row a pointer can
  safely name.
- **Resolve at read time from `(visits.jurisdiction, notes.format)`.** No migration,
  and wrong for the reason above.

### Migration `0013`

1. Add `note_template_id UUID NULL`, foreign key to `note_templates.id`,
   `ON DELETE RESTRICT` — a template row that notes were generated from must not be
   deletable.
2. Backfill from `(visits.jurisdiction, notes.format)`, taking the **highest version
   regardless of `is_active`**, so a template that has since been deactivated still
   resolves the notes it produced.
3. If any row remains unresolved, stop with a message naming the unresolved
   `(jurisdiction, format)` pairs rather than letting `SET NOT NULL` fail on a
   constraint violation. This follows the posture `0011`'s downgrade already takes:
   refuse with something actionable rather than guess about clinical records.
4. `SET NOT NULL`.

Downgrade drops the column.

`TemplateSpec` gains `id`, populated in `from_template`, so
`NoteRepository.create_for_visit` writes the foreign key for every note generated
after this migration.

---

## 2. Read API

### `GET /api/v1/notes/{note_id}`

Returns the note, its flags, and the section schema of the template that produced it,
resolved through the new foreign key rather than through whatever is active now.

```jsonc
{
  "id": "…", "visit_id": "…", "format": "fdar",
  "version": 1, "edited": false, "review_status": "unreviewed",
  "signed_at": null,
  "visit_details": { "client_label": "Bed 12", "visit_date": "2026-09-23",
                     "start_time": "22:00", "end_time": "06:00" },
  "sections": { "shift_details": "…", "focus_entries": [ { "focus": "…", "data": "…",
                "action": "…", "response": "…" } ], "…": "…" },
  "flags": [ { "code": "MISSING_RESPONSE", "message": "…", "severity": "critical" } ],
  "template": {
    "jurisdiction": "PH", "format": "fdar", "version": 1, "name": "…",
    "sections": [ { "key": "focus_entries", "label": "Focus entries", "order": 2,
                    "description": "…", "repeating": true,
                    "fields": [ { "key": "focus", "label": "Focus", "order": 1,
                                  "description": "…" } ] } ]
  }
}
```

Keyed on the note's own id rather than the visit's: the note is the resource being
edited, `VisitProcessingStatus` already returns `note_id`, and `PATCH` needs a
resource to address.

### `GET /api/v1/notes`

The recent list — enough to get back to a note after closing the tab, and no more.
Per note: id, client label and date from `visit_details`, format, whether it has been
edited, whether it has been signed, and flag counts per severity. The counts are a
SQL aggregation over `note_flags` grouped by severity, which is the access pattern
that table exists to serve.

Newest first by `created_at`, capped at 50, with no pagination in this phase — a
tester needs to find the note they just wrote, and fifty is past the point where a
list is the wrong tool.

Explicitly not the Phase 7 roster: no agency scope, no review queue, no charts.

### Tenant scoping

Applied in the repository, not checked in handlers, matching the convention Phase 3
set. Another user's note is **404**, never 403, so a caller cannot probe for note ids
they do not own.

---

## 3. `PATCH /api/v1/notes/{note_id}`

```jsonc
{ "version": 3, "visit_details": { … }, "sections": { … } }
```

`visit_details` and `sections` are both optional; whichever is present replaces its
stored counterpart wholesale. A successful write increments `version`, sets
`edited = true`, and returns the same shape the `GET` returns.

**A stale `version` returns 409.** This is the guarantee `notes.version` was added
for: a supervisor opening a note in the review queue while its author edits it on
their phone must not silently discard one of them.

The version travels in the body rather than an `If-Match` header, so it appears in
the OpenAPI schema and omitting it is a TypeScript compile error in the generated
client rather than a request that succeeds by accident.

The 409 carries the note's current version and nothing else. It deliberately does not
return the newer note body: the client asks for it with a fresh `GET`, so there is one
code path that renders a note rather than two, and no chance of an error response and
a success response disagreeing about the shape of one.

### What the PATCH validates

Structure only, against the template's own `section_schema`:

- every section key belongs to the template, and none is missing;
- a repeating section carries a list of entries, each entry carrying exactly the
  fields the schema declares;
- a flat section carries a string or null.

It deliberately does **not** apply `BANNED_PHRASES`. That rule governs how the *model*
writes: a note in the product's own voice saying "routine visit" documents nothing.
A nurse typing the same words is the author of a clinical record, and a product that
refuses her sentence has overstepped. The flag system is advisory; the editor is not
a gate on a clinician's language.

### What the PATCH does not accept

`version`, `edited`, `review_status`, `signed_at`, `format` and the provenance fields
are not writable. The request model accepts `version`, `visit_details` and `sections`
and nothing else, so a field added to `Note` later cannot become client-writable by
default — the same reason `OnboardingRequest` sets `extra="forbid"`.

No check is written for editing a signed note. Nothing in this phase can set
`signed_at`: sign-off arrives in 5.2, and that is where the lock belongs, beside the
code that creates the state it guards. A check written here would be testing a state
this branch cannot produce, which is the same call — and the same reasoning — recorded
in [the Phase 4c carried finding](../findings/2026-09-22-phase-4c-carried.md).
**5.2 must add the lock in the same change that adds sign-off.**

### What editing does not do

Flags do not re-evaluate. They are a record of what the model found when it generated
the note, the panel is a checklist a human works through, and `edited` marks that the
note no longer matches what the model produced. Deterministic flag checkers belong to
Phase 5b's eval work; writing them here would mean writing the same rules twice, and a
checker that gets a rule wrong silently clears a real finding on a legal record.

---

## 4. The editor

Route `/notes/:noteId`.

Sections render in `order`. A flat section is a labelled textarea with the schema's
`description` as help text. A repeating section — `focus_entries` today, and nothing
else in any current template — renders as an ordered list of entry cards, each card
holding that section's `fields` as textareas, with **add entry** and **remove entry**.
FDAR charts one F-D-A-R block per nursing focus and a shift has several; a nurse who
charted three focuses when the model captured two has to be able to add the third.

`visit_details` gets its own small form above the sections: client label, date, start
and end time. These are editable because the missing-times flags are decided from
them, and a flag pointing at a read-only field is a flag that cannot be cleared.

Saving is explicit. On **409** the editor says the note changed somewhere else and
offers to reload it, rather than choosing on the user's behalf which version survives.

Component split, each independently testable:

| File | Responsibility |
|---|---|
| `routes/NoteEditor.tsx` | fetch, form state, save, conflict handling |
| `components/note/SectionField.tsx` | one flat section |
| `components/note/RepeatingSection.tsx` | one repeating section and its entries |
| `components/note/VisitDetailsFields.tsx` | the four header fields |
| `components/note/FlagsPanel.tsx` | flags grouped by severity |
| `lib/note.ts` | the note queries and the save mutation |

---

## 5. Flags panel

Grouped by severity — critical, then warning, then info — each showing its code and
the model's message. `note_flags.section_key` stays null: the output contract does not
ask the model which section a flag is about, and deriving it from the code would be
guesswork. The column's own comment reserves it for "when the review UI lets a human
attach one", which is not this phase.

---

## 6. Testing

Backend, against real PostgreSQL as the suite already does:

- the pipeline writes `note_template_id` on a generated note;
- the read returns the schema of the template that produced the note, not the active
  one — proved by seeding a higher version and asserting the note still renders
  against its own;
- `PATCH` increments `version` and sets `edited`;
- a stale `version` returns 409 and leaves the stored note untouched;
- another user's note returns 404 on both read and write;
- an unknown section key is rejected;
- a repeating entry missing a declared field is rejected;
- a banned phrase written by a human is accepted.

Web, with Vitest and Testing Library:

- sections render in schema order, with a repeating section rendering one card per
  stored entry;
- adding an entry appends an empty card, removing one drops it;
- the save body carries the version the note was loaded at;
- a 409 response surfaces a reload offer rather than a generic error;
- the flags panel groups by severity;
- the recent list renders label, date and flag counts.

---

## 7. Out of scope

Sign-off lock, WeasyPrint PDF export, and moving the disclaimer onto `note_templates`
— all Phase 5.2. No flag re-evaluation, no review queue, no agency roster, no
share links. Audio and transcript display are not part of this phase either: the
transcript exists on the visit, but showing a nurse what the microphone heard is a
separate design question about a document that contains identifiers the note does not.
