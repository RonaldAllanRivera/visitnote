import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, Link, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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

function okPatch(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) } as never
}

function conflictPatch(currentVersion: number) {
  return {
    error: { detail: { message: 'changed', current_version: currentVersion } } as unknown as never,
    response: new Response(null, { status: 409 }),
  }
}

/**
 * NoteEditor blocks in-app navigation with `useBlocker`, which requires a data
 * router -- a plain `<MemoryRouter>` throws the moment the hook runs. The harness
 * also gives the editor a sibling link, standing in for header navigation, so the
 * blocker has something to intercept.
 */
function renderEditor() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [
      {
        path: '/notes/:noteId',
        element: (
          <>
            <NoteEditor />
            <Link to="/elsewhere">Elsewhere</Link>
          </>
        ),
      },
      { path: '/elsewhere', element: <p>Somewhere else</p> },
    ],
    { initialEntries: [`/notes/${NOTE_ID}`] },
  )
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
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
  })
})

afterEach(() => {
  vi.restoreAllMocks()
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
    vi.mocked(api.PATCH).mockResolvedValue(okPatch(note({ version: 2, edited: true })))

    renderEditor()
    fireEvent.click(await screen.findByRole('button', { name: /save/i }))

    await waitFor(() => { expect(api.PATCH).toHaveBeenCalled() })
    const calls = vi.mocked(api.PATCH).mock.calls as unknown as [string, { body: { version: number } }][]
    const firstCall = calls[0]
    if (firstCall === undefined) throw new Error('expected api.PATCH to have been called')
    expect(firstCall[1].body.version).toBe(1)
  })

  it('sends the version the *previous save* returned, not the version it loaded at', async () => {
    // The bug this guards against: a draft that never resyncs after a save always
    // carries the version it started at. Editing before the first save is the part
    // that matters -- it is what makes `draft` non-null, so if the save's success
    // doesn't clear it, everything typed afterwards keeps building on the stale
    // version instead of the one the server just accepted.
    vi.mocked(api.PATCH)
      .mockResolvedValueOnce(okPatch(note({
        version: 2, edited: true,
        sections: { shift_details: 'First edit.', focus_entries: [{ focus: 'Pain', response: '' }] },
      })))
      .mockResolvedValueOnce(okPatch(note({ version: 3, edited: true })))

    renderEditor()
    const textarea = await screen.findByLabelText(/shift details/i)
    fireEvent.change(textarea, { target: { value: 'First edit.' } })

    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    await waitFor(() => { expect(api.PATCH).toHaveBeenCalledTimes(1) })
    await screen.findByText(/version 2/i)

    fireEvent.change(screen.getByLabelText(/shift details/i), { target: { value: 'Second edit.' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => { expect(api.PATCH).toHaveBeenCalledTimes(2) })
    const calls = vi.mocked(api.PATCH).mock.calls as unknown as [string, { body: { version: number } }][]
    const secondCall = calls[1]
    if (secondCall === undefined) throw new Error('expected a second api.PATCH call')
    expect(secondCall[1].body.version).toBe(2)
  })

  it('leaves the header and the fields agreeing once a save lands', async () => {
    vi.mocked(api.PATCH).mockResolvedValue(
      okPatch(note({
        version: 2,
        edited: true,
        sections: { shift_details: 'Night shift.', focus_entries: [{ focus: 'Pain', response: '' }] },
      })),
    )

    renderEditor()
    fireEvent.click(await screen.findByRole('button', { name: /save/i }))

    await screen.findByText(/version 2/i)
    expect(screen.getByText(/· edited/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/shift details/i)).toHaveValue('Night shift.')
  })

  it('says "another version" rather than inventing version 0 for a malformed 409', async () => {
    vi.mocked(api.PATCH).mockResolvedValue({
      error: { detail: { message: 'changed' } },
      response: new Response(null, { status: 409 }),
    } as never)

    renderEditor()
    fireEvent.click(await screen.findByRole('button', { name: /save/i }))

    await screen.findByText(/another version/i)
    expect(screen.queryByText(/version 0/i)).not.toBeInTheDocument()
  })

  it('normalises an all-whitespace edit to null before saving, for a section and a visit detail', async () => {
    vi.mocked(api.PATCH).mockResolvedValue(okPatch(note({ version: 2, edited: true })))

    renderEditor()
    fireEvent.change(await screen.findByLabelText(/shift details/i), { target: { value: '   ' } })
    fireEvent.change(screen.getByLabelText(/start time/i), { target: { value: '  ' } })

    fireEvent.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => { expect(api.PATCH).toHaveBeenCalled() })
    const calls = vi.mocked(api.PATCH).mock.calls as unknown as [
      string,
      { body: { sections: Record<string, unknown>; visit_details: Record<string, unknown> } },
    ][]
    const call = calls[0]
    if (call === undefined) throw new Error('expected api.PATCH to have been called')
    expect(call[1].body.sections.shift_details).toBeNull()
    expect(call[1].body.visit_details.start_time).toBeNull()
  })

  it('offers a reload rather than choosing which version survives', async () => {
    vi.mocked(api.PATCH).mockResolvedValue(conflictPatch(4))

    renderEditor()
    fireEvent.click(await screen.findByRole('button', { name: /save/i }))

    expect(await screen.findByRole('button', { name: /reload/i })).toBeInTheDocument()
  })

  it('reloads the server copy on confirmation, and the next save is accepted', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api.PATCH).mockResolvedValueOnce(conflictPatch(4))

    renderEditor()
    fireEvent.click(await screen.findByRole('button', { name: /save/i }))
    await screen.findByRole('button', { name: /reload/i })

    vi.mocked(api.GET).mockResolvedValueOnce({
      data: note({ version: 4, edited: true }),
      response: new Response(null, { status: 200 }),
    })
    vi.mocked(api.PATCH).mockResolvedValueOnce(okPatch(note({ version: 5, edited: true })))

    fireEvent.click(screen.getByRole('button', { name: /reload/i }))

    await screen.findByText(/version 4/i)
    expect(screen.queryByRole('button', { name: /reload/i })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => { expect(api.PATCH).toHaveBeenCalledTimes(2) })
    const calls = vi.mocked(api.PATCH).mock.calls as unknown as [string, { body: { version: number } }][]
    const secondCall = calls[1]
    if (secondCall === undefined) throw new Error('expected a second api.PATCH call')
    expect(secondCall[1].body.version).toBe(4)
  })

  it('asks for confirmation before reloading, and does nothing if declined', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    vi.mocked(api.PATCH).mockResolvedValue(conflictPatch(4))

    renderEditor()
    fireEvent.click(await screen.findByRole('button', { name: /save/i }))
    fireEvent.click(await screen.findByRole('button', { name: /reload/i }))

    expect(confirmSpy).toHaveBeenCalled()
    // Declined: the conflict panel, offering reload, is still there.
    expect(await screen.findByRole('button', { name: /reload/i })).toBeInTheDocument()
  })

  it('surfaces a failed reload instead of silently sitting on the stale note', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api.PATCH).mockResolvedValue(conflictPatch(4))

    renderEditor()
    fireEvent.click(await screen.findByRole('button', { name: /save/i }))
    await screen.findByRole('button', { name: /reload/i })

    // Set up *after* the initial load has already consumed the persistent mock, so
    // this failure lands on the refetch the reload button triggers, not on the
    // note's first load.
    vi.mocked(api.GET).mockResolvedValueOnce({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 500 }),
    })

    fireEvent.click(screen.getByRole('button', { name: /reload/i }))

    await screen.findByText(/could not reload/i)
    // The conflict is still the true state of the world, so the offer to reload
    // stays rather than the screen quietly looking fine again.
    expect(screen.getByRole('button', { name: /reload/i })).toBeInTheDocument()
  })

  it('shows an ordinary save failure without treating it as a conflict', async () => {
    vi.mocked(api.PATCH).mockResolvedValue({
      error: { detail: 'The server had a problem saving this note.' },
      response: new Response(null, { status: 500 }),
    } as never)

    renderEditor()
    fireEvent.click(await screen.findByRole('button', { name: /save/i }))

    await screen.findByText('The server had a problem saving this note.')
    expect(screen.queryByRole('button', { name: /reload/i })).not.toBeInTheDocument()
  })

  it('shows what the model flagged', async () => {
    renderEditor()

    await screen.findByText('No response charted.')
  })

  it('warns before in-app navigation discards unsaved edits, and honours "stay"', async () => {
    renderEditor()
    const textarea = await screen.findByLabelText(/shift details/i)
    fireEvent.change(textarea, { target: { value: 'Typing and not yet saved.' } })

    fireEvent.click(screen.getByRole('link', { name: /elsewhere/i }))

    await screen.findByText(/unsaved changes/i)

    fireEvent.click(screen.getByRole('button', { name: /^stay$/i }))

    expect(screen.queryByText(/unsaved changes/i)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/shift details/i)).toHaveValue('Typing and not yet saved.')
  })

  it('lets the nurse leave once warned, discarding the draft', async () => {
    renderEditor()
    const textarea = await screen.findByLabelText(/shift details/i)
    fireEvent.change(textarea, { target: { value: 'Typing and not yet saved.' } })

    fireEvent.click(screen.getByRole('link', { name: /elsewhere/i }))
    fireEvent.click(await screen.findByRole('button', { name: /leave/i }))

    await screen.findByText('Somewhere else')
  })

  it('does not block navigation when there is nothing unsaved', async () => {
    renderEditor()
    await screen.findByRole('button', { name: /save/i })

    fireEvent.click(screen.getByRole('link', { name: /elsewhere/i }))

    await screen.findByText('Somewhere else')
  })

  it('warns before closing the tab while there are unsaved edits, and only then', async () => {
    renderEditor()
    const textarea = await screen.findByLabelText(/shift details/i)

    const before = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(before)
    expect(before.defaultPrevented).toBe(false)

    fireEvent.change(textarea, { target: { value: 'Typing and not yet saved.' } })

    const after = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(after)
    expect(after.defaultPrevented).toBe(true)
  })
})
