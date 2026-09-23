import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { UserProfile } from '@/lib/profile'
import { profileFixture } from '@/test/fixtures'
import { useAuthStore } from '@/stores/auth'

import { Settings } from './Settings'

vi.mock('@/api/client', () => ({ api: { GET: vi.fn(), PATCH: vi.fn() } }))

function ok(profile: UserProfile) {
  return { data: profile, response: new Response(null, { status: 200 }) }
}

function signedInAs(jurisdiction: UserProfile['jurisdiction']) {
  vi.mocked(api.GET).mockResolvedValue(ok(profileFixture({ jurisdiction })))
}

function renderSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The request bodies sent, in order. `api.PATCH` is overloaded per path, so its
 * generated call tuple collapses to `never` and cannot be indexed directly. */
function patchBodies(): unknown[] {
  const calls = vi.mocked(api.PATCH).mock.calls as unknown as [string, { body?: unknown }][]
  return calls.map((call) => call[1].body)
}

beforeEach(() => {
  // The profile query only runs for a session that exists -- the public landing
  // page renders the shell too, and must not fetch a profile for a visitor.
  localStorage.clear()
  useAuthStore.getState().setSession({ accessToken: 'a', refreshToken: 'r' })
  vi.mocked(api.GET).mockReset()
  vi.mocked(api.PATCH).mockReset()
})

describe('Settings', () => {
  it('names the regime the account is currently under', async () => {
    signedInAs('US')

    renderSettings()

    expect(await screen.findByText(/United States/i)).toBeInTheDocument()
  })

  it('switches jurisdiction with a request that carries nothing else', async () => {
    // Nothing else, deliberately: the server derives the note format from the new
    // jurisdiction and reconciles a format the switch would strand. A client that
    // also sent a format would be overriding a decision it is not equipped to make.
    signedInAs('US')
    vi.mocked(api.PATCH).mockResolvedValue(ok(profileFixture({ jurisdiction: 'PH' })))

    renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: /philippines/i }))

    await waitFor(() => { expect(api.PATCH).toHaveBeenCalled() })
    expect(patchBodies()[0]).toEqual({ jurisdiction: 'PH' })
  })

  it('reflects the new regime without waiting for a refetch', async () => {
    signedInAs('US')
    vi.mocked(api.PATCH).mockResolvedValue(ok(profileFixture({ jurisdiction: 'PH' })))

    renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: /philippines/i }))

    expect(await screen.findByText(/RA 4200/)).toBeInTheDocument()
  })

  it('offers the way back, so a switch made by mistake is not a dead end', async () => {
    signedInAs('PH')

    renderSettings()

    expect(await screen.findByRole('button', { name: /united states/i })).toBeInTheDocument()
  })

  it('says that notes already written keep the regime they were written under', async () => {
    signedInAs('US')

    renderSettings()

    expect(await screen.findByText(/already/i)).toBeInTheDocument()
  })

  it('surfaces a refused switch instead of showing a regime that did not take', async () => {
    signedInAs('US')
    vi.mocked(api.PATCH).mockResolvedValue({
      error: { detail: 'Unsupported jurisdiction' } as unknown as never,
      response: new Response(null, { status: 422 }),
    })

    renderSettings()
    fireEvent.click(await screen.findByRole('button', { name: /philippines/i }))

    expect(await screen.findByText(/Unsupported jurisdiction/)).toBeInTheDocument()
    expect(screen.getByText(/United States/i)).toBeInTheDocument()
  })
})
