import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { UserProfile } from '@/lib/profile'
import { profileFixture } from '@/test/fixtures'
import { useAuthStore } from '@/stores/auth'

import { RequireOnboarding } from './RequireOnboarding'

vi.mock('@/api/client', () => ({ api: { GET: vi.fn() } }))

function profileResponse(overrides: Partial<UserProfile> = {}) {
  return {
    data: profileFixture(overrides),
    error: undefined,
    response: new Response(null, { status: 200 }),
  }
}

/** Reports where the guard said the user was trying to go. */
function OnboardingProbe() {
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from
  return <span>onboarding screen, from {from ?? 'nowhere'}</span>
}

function renderGuard(initialPath = '/new') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route element={<RequireOnboarding />}>
            <Route path="/new" element={<span>capture screen</span>} />
          </Route>
          <Route path="/onboarding" element={<OnboardingProbe />} />
        </Routes>
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

describe('RequireOnboarding', () => {
  it('sends an account that has never been asked to onboarding', async () => {
    // Without this, a Manila nurse captures a visit under the US default they were
    // never shown, and the RA 4200 refusal never fires for the person it protects.
    vi.mocked(api.GET).mockResolvedValue(profileResponse({ role_title: null }))

    renderGuard()

    expect(await screen.findByText(/onboarding screen/)).toBeInTheDocument()
  })

  it('carries the intended destination so onboarding can return the user to it', async () => {
    vi.mocked(api.GET).mockResolvedValue(profileResponse({ role_title: null }))

    renderGuard('/new')

    expect(await screen.findByText('onboarding screen, from /new')).toBeInTheDocument()
  })

  it('lets an onboarded account straight through', async () => {
    vi.mocked(api.GET).mockResolvedValue(profileResponse({ role_title: 'rn' }))

    renderGuard()

    expect(await screen.findByText('capture screen')).toBeInTheDocument()
  })

  it('renders neither branch while the profile is still in flight', () => {
    // Deciding on an unresolved profile would throw an onboarded user at the form on
    // every reload -- the same failure `isSessionRestorable` exists to prevent for
    // the access token, which is absent after every refresh.
    vi.mocked(api.GET).mockReturnValue(new Promise(() => {}))

    renderGuard()

    expect(screen.queryByText('capture screen')).not.toBeInTheDocument()
    expect(screen.queryByText(/onboarding screen/)).not.toBeInTheDocument()
  })
})
