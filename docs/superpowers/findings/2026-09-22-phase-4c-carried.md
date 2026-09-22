# Phase 4c — findings carried forward

Raised by the whole-branch review of `feat/phase-4c-findings` on 2026-09-22, alongside
the fix wave the review's other findings went into. This one is deliberately left
unguarded.

## A `prompt_version` rollback to `shift_note_v1` / `soapie_v1` would re-declare a flag
## with no instruction behind it

Migration `0012` appends `PATIENT_IDENTIFIER_DETECTED` to the two US templates'
`flag_schema` at `(jurisdiction='US', version=1)` -- the same rows `shift_note_v1` and
`soapie_v1` are the `prompt_version` for. `0011`'s docstring names exactly this failure
mode: a flag declared in `flag_schema` with no prompt text ever asking the model to
raise it produces a clean note that reads as a pass rather than a missing-control
finding, which is worse than not declaring the code at all.

Nothing in this repository performs that rollback today -- `prompt_version` is set once
at seed time and repointed forward by `0012`, never back. If a future migration or a
manual `UPDATE` ever repointed either row's `prompt_version` back to the `v1` module
without also either reverting the `flag_schema` append or moving the row onto a prompt
that carries the instruction, the row would return to exactly the state `0011` and
`0012` exist to avoid.

A guard against this is not written here because it would be speculative: there is no
code path in this branch that performs the rollback, so a check today would be testing
a hypothetical rather than a real one, and would have to guess at the shape of a
migration that does not exist. If a `prompt_version` downgrade is ever proposed, its
review should re-read this note and confirm `flag_schema` and `prompt_version` are
changed together.
