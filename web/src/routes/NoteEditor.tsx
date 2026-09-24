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
