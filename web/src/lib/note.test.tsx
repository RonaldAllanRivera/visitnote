import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { Note } from '@/lib/note'

import { normalizeFieldValue, NoteConflictError, useNote, useSaveNote } from './note'

vi.mock('@/api/client', () => ({ api: { GET: vi.fn(), PATCH: vi.fn() } }))

const NOTE_ID = '22222222-2222-2222-2222-222222222222'

function noteFixture(overrides: Partial<Note> = {}): Note {
  return {
    id: NOTE_ID,
    visit_id: '33333333-3333-3333-3333-333333333333',
    format: 'shift_note',
    version: 1,
    edited: false,
    review_status: 'unreviewed',
    signed_at: null,
    visit_details: {},
    sections: { narrative: 'Patient stable.' },
    flags: [],
    template: {
      jurisdiction: 'US',
      format: 'shift_note',
      version: 1,
      name: 'Shift note',
      sections: [],
    },
    ...overrides,
  }
}

function ok<T>(data: T) {
  return { data, response: new Response(null, { status: 200 }) }
}

function renderNoteAndSave() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return renderHook(() => ({ note: useNote(NOTE_ID), save: useSaveNote(NOTE_ID) }), { wrapper })
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
  vi.mocked(api.PATCH).mockReset()
})

describe('useSaveNote', () => {
  it('does not refetch the open note after a save', async () => {
    // useNote sets staleTime: Infinity precisely so an editor's in-progress draft is
    // never quietly replaced by a background refetch. queryKeys.notes() used to
    // share a root with queryKeys.note(id), so invalidating the list after a save
    // (invalidateQueries defaults to prefix matching) also invalidated -- and
    // refetched -- every open note underneath the editor.
    vi.mocked(api.GET).mockResolvedValue(ok(noteFixture({ version: 1 })))
    vi.mocked(api.PATCH).mockResolvedValue(ok(noteFixture({ version: 2, edited: true })))

    const { result } = renderNoteAndSave()

    await waitFor(() => { expect(result.current.note.data).toBeDefined() })
    expect(api.GET).toHaveBeenCalledTimes(1)

    result.current.save.mutate({ version: 1, sections: { narrative: 'Patient improving.' } })

    await waitFor(() => { expect(result.current.save.isSuccess).toBe(true) })

    // The save landed and the mutation's onSuccess ran (which invalidates the list),
    // but the note's own query must not have gone back to the network for it.
    expect(api.GET).toHaveBeenCalledTimes(1)
  })

  it('reports a conflict with no current_version as null, not as version 0', async () => {
    // A malformed 409 body used to degrade to `currentVersion: 0`, which the dialog
    // then printed as if it were the note's real version.
    vi.mocked(api.GET).mockResolvedValue(ok(noteFixture({ version: 1 })))
    vi.mocked(api.PATCH).mockResolvedValue({
      error: { detail: { message: 'changed' } },
      response: new Response(null, { status: 409 }),
    } as never)

    const { result } = renderNoteAndSave()
    await waitFor(() => { expect(result.current.note.data).toBeDefined() })

    result.current.save.mutate({ version: 1, sections: { narrative: 'Edited.' } })

    await waitFor(() => { expect(result.current.save.isError).toBe(true) })
    const error = result.current.save.error
    expect(error).toBeInstanceOf(NoteConflictError)
    expect((error as NoteConflictError).currentVersion).toBeNull()
  })
})

describe('normalizeFieldValue', () => {
  it('turns an all-whitespace edit into null', () => {
    expect(normalizeFieldValue('')).toBeNull()
    expect(normalizeFieldValue('   ')).toBeNull()
    expect(normalizeFieldValue('\n\t ')).toBeNull()
  })

  it('leaves real content untouched', () => {
    expect(normalizeFieldValue('Ate half of lunch.')).toBe('Ate half of lunch.')
    // Leading/trailing whitespace around real content is not itself the "nothing
    // here" signal -- only a value that is whitespace through and through is.
    expect(normalizeFieldValue('  Ate half of lunch.  ')).toBe('  Ate half of lunch.  ')
  })
})
