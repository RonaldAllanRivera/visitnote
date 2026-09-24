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
    })

    renderNotes()

    expect(await screen.findByText('Bed 12')).toBeInTheDocument()
    expect(screen.getByText(/2 critical/i)).toBeInTheDocument()
  })

  it('says what to do when there is nothing yet', async () => {
    // An empty list that says nothing reads like a failure to load.
    vi.mocked(api.GET).mockResolvedValue({
      data: [], response: new Response(null, { status: 200 }),
    })

    renderNotes()

    expect(await screen.findByText(/record your first/i)).toBeInTheDocument()
  })
})
