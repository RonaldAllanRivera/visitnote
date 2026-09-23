import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { UserProfile } from '@/lib/profile'
import { profileFixture } from '@/test/fixtures'
import { useAuthStore } from '@/stores/auth'

import { NewVisit } from './NewVisit'

vi.mock('@/api/client', () => ({ api: { GET: vi.fn(), POST: vi.fn() } }))

function ok(data: unknown) {
  return { data, response: new Response(null, { status: 200 }) }
}

/** Route by path: this screen reads the care recipients and the profile. */
function serveAs(jurisdiction: UserProfile['jurisdiction']) {
  vi.mocked(api.GET).mockImplementation(((path: string) =>
    Promise.resolve(
      path === '/api/v1/auth/me'
        ? ok(profileFixture({ jurisdiction }))
        : ok([{ id: 'c1', label: 'Mrs R', is_active: true }]),
    )) as never)
}

function renderNewVisit() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NewVisit />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  // The profile query only runs for a session that exists -- the public landing
  // page renders the shell too, and must not fetch a profile for a visitor.
  localStorage.clear()
  useAuthStore.getState().setSession({ accessToken: 'a', refreshToken: 'r' })
  vi.mocked(api.GET).mockReset()
})

describe('NewVisit capture modes', () => {
  it('offers to record the visit itself to a US account', async () => {
    serveAs('US')

    renderNewVisit()

    expect(await screen.findByLabelText(/record the visit itself/i)).toBeInTheDocument()
  })

  it('withholds live recording from a PH account and says why', async () => {
    // The server refuses this capture mode for PH accounts regardless of what this
    // screen shows. Offering a choice that is always refused is the broken part:
    // the nurse picks it, records, and only then learns it was never available.
    serveAs('PH')

    renderNewVisit()

    expect(await screen.findByText(/RA 4200/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/record the visit itself/i)).not.toBeInTheDocument()
  })

  it("quotes the server's reason rather than writing its own", async () => {
    // The statute text belongs to whoever enforces it. Asserting on the API's exact
    // wording is what stops the screen drifting into a paraphrase that sounds right
    // and cites the wrong thing.
    serveAs('PH')

    renderNewVisit()

    expect(await screen.findByText(/Anti-Wiretapping Act/)).toBeInTheDocument()
  })

  it('offers what the account may do, not what its jurisdiction implies', async () => {
    // Driven by the published capability, not by the client re-deriving the rule
    // from the jurisdiction. If PH ever permits live capture -- an exemption, a
    // different setting -- the screen follows the server without a release.
    vi.mocked(api.GET).mockImplementation(((path: string) =>
      Promise.resolve(
        path === '/api/v1/auth/me'
          ? ok(
              profileFixture({
                jurisdiction: 'PH',
                capabilities: {
                  allowed_capture_modes: ['live_audio', 'spoken_recap'],
                  capture_restriction: null,
                  available_formats: ['fdar'],
                },
              }),
            )
          : ok([{ id: 'c1', label: 'Mrs R', is_active: true }]),
      )) as never)

    renderNewVisit()

    expect(await screen.findByLabelText(/record the visit itself/i)).toBeInTheDocument()
  })
})
