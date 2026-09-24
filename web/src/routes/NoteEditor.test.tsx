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
  })
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
    const calls = vi.mocked(api.PATCH).mock.calls as unknown as [string, { body: { version: number } }][]
    const firstCall = calls[0]
    if (firstCall === undefined) throw new Error('expected api.PATCH to have been called')
    expect(firstCall[1].body.version).toBe(1)
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
