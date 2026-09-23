import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { UserProfile } from '@/lib/profile'
import { profileFixture } from '@/test/fixtures'
import { useAuthStore } from '@/stores/auth'

import { AppLayout } from './AppLayout'

vi.mock('@/api/client', () => ({ api: { GET: vi.fn() } }))

function signedInAs(jurisdiction: UserProfile['jurisdiction']) {
  useAuthStore.getState().setSession({ accessToken: 'a', refreshToken: 'r' })
  vi.mocked(api.GET).mockResolvedValue({
    data: profileFixture({ jurisdiction }),
    response: new Response(null, { status: 200 }),
  })
}

function renderLayout() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AppLayout />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  useAuthStore.getState().clear()
  vi.mocked(api.GET).mockReset()
})

describe('AppLayout disclaimer', () => {
  it('tells a US user the note is theirs to stand behind', async () => {
    signedInAs('US')

    renderLayout()

    expect(await screen.findByText(/not medical advice or a medical device/i)).toBeInTheDocument()
  })

  it("tells a PH user the patient's chart is still the legal record", async () => {
    // Not a softer version of the same sentence. In US home health the note IS the
    // record the agency keeps; on a PH ward it is a draft the nurse transcribes into
    // the hospital chart. Showing the US wording to a PH nurse misstates which
    // document carries legal weight.
    signedInAs('PH')

    renderLayout()

    expect(await screen.findByText(/drafting aid/i)).toBeInTheDocument()
    expect(screen.getByText(/chart remains the legal record/i)).toBeInTheDocument()
  })

  it('does not ask the API who the visitor is when nobody is signed in', () => {
    // The landing page renders this shell. A profile fetch here would 401 for every
    // anonymous visitor and trip the session-expired handler on a public page.
    renderLayout()

    expect(api.GET).not.toHaveBeenCalled()
    expect(screen.getByText(/not medical advice or a medical device/i)).toBeInTheDocument()
  })
})
