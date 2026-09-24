import { useEffect, useState } from 'react'
import { useBlocker, useParams } from 'react-router'

import { FlagsPanel } from '@/components/note/FlagsPanel'
import { RepeatingSection } from '@/components/note/RepeatingSection'
import { SectionField } from '@/components/note/SectionField'
import { VisitDetailsFields } from '@/components/note/VisitDetailsFields'
import { NoteConflictError, useNote, useSaveNote, type Note, type SectionValue } from '@/lib/note'

type Entry = Record<string, string | null>

interface Draft {
  version: number
  visitDetails: Record<string, string | null>
  sections: Record<string, SectionValue>
}

function draftOf(note: Note): Draft {
  return {
    // Captured with the draft, not read at save time: this is the version the nurse
    // actually saw, which is the thing the server needs to compare against.
    version: note.version,
    // `NoteRead.visit_details` is typed `Record<string, unknown>` in the generated
    // client -- the read schema still leaves it as `Any` -- but what the backend
    // actually writes there, on both the generation and edit paths, is always
    // `str | null` per key (`VISIT_DETAIL_KEYS`). This cast states that contract; it
    // is what `NoteUpdate.visit_details` requires the draft to be shaped as anyway.
    visitDetails: { ...note.visit_details } as Record<string, string | null>,
    sections: { ...note.sections },
  }
}

const RELOAD_WARNING =
  'Reloading discards the edits you have made since your last save. This cannot be undone. Continue?'

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
  const [reloadError, setReloadError] = useState<string | null>(null)

  // The draft only exists between an edit and the point it is reconciled back into
  // the query cache (a successful save, or a successful reload). Its presence is
  // exactly "there is something here the server has not seen" -- which is also
  // exactly when leaving the page would lose work.
  const hasUnsavedChanges = draft !== null

  const blocker = useBlocker(hasUnsavedChanges)

  useEffect(() => {
    if (!hasUnsavedChanges) return
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault()
    }
    window.addEventListener('beforeunload', handler)
    return () => { window.removeEventListener('beforeunload', handler) }
  }, [hasUnsavedChanges])

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
            This note was changed somewhere else — it is now at{' '}
            {conflict.currentVersion === null
              ? 'another version'
              : `version ${String(conflict.currentVersion)}`}
            . Saving now would discard that change.
          </p>
          <p className="text-sm text-muted">
            Reloading discards the edits you have made since your last save.
          </p>
          {reloadError !== null && <p className="text-sm text-critical">{reloadError}</p>}
          <button
            type="button"
            onClick={() => {
              if (!window.confirm(RELOAD_WARNING)) return
              void refetch().then((result) => {
                if (result.isError) {
                  // The mutation's error is left in place deliberately: a reload that
                  // failed has not reconciled anything, so the conflict the nurse was
                  // shown is still the true state, and a save now would still 409.
                  setReloadError('Could not reload the note. Try again.')
                  return
                }
                setReloadError(null)
                setDraft(null)
                save.reset()
              })
            }}
            className="rounded-md border border-line px-3 py-2 text-sm"
          >
            Reload the note
          </button>
        </div>
      ) : (
        save.isError && <p className="text-sm text-critical">{save.error.message}</p>
      )}

      {blocker.state === 'blocked' && (
        <div role="alertdialog" className="space-y-2 rounded-md border border-critical/50 p-4">
          <p className="text-sm">
            You have unsaved changes. Leaving this page now will discard them.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => { blocker.proceed() }}
              className="rounded-md border border-line px-3 py-2 text-sm"
            >
              Leave without saving
            </button>
            <button
              type="button"
              onClick={() => { blocker.reset() }}
              className="rounded-md bg-accent px-3 py-2 text-sm text-surface"
            >
              Stay
            </button>
          </div>
        </div>
      )}

      <button
        type="button"
        disabled={save.isPending}
        onClick={() => {
          save.mutate(
            {
              version: current.version,
              visit_details: current.visitDetails,
              sections: current.sections,
            },
            {
              onSuccess: () => {
                // The saved note is now the query cache's version; dropping the draft
                // re-derives the next one from it, so the version a later edit carries
                // is the version the server just accepted, not the one it superseded.
                setDraft(null)
              },
            },
          )
        }}
        className="rounded-md bg-accent px-4 py-2 text-surface disabled:opacity-50"
      >
        {save.isPending ? 'Saving…' : 'Save'}
      </button>
    </section>
  )
}
