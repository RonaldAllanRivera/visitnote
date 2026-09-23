import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { UserProfile } from '@/lib/profile'
import { profileFixture } from '@/test/fixtures'

import { Onboarding } from './Onboarding'

vi.mock('@/api/client', () => ({ api: { GET: vi.fn(), PATCH: vi.fn() } }))

/**
 * `error` is omitted rather than set to undefined: openapi-fetch's success branch
 * declares `error?: never`, which under `exactOptionalPropertyTypes` means absent --
 * not present-and-undefined. Omitting it is also what the client really returns.
 */
function patchResponse(overrides: Partial<UserProfile> = {}) {
  return { data: profileFixture(overrides), response: new Response(null, { status: 200 }) }
}

/** Pin what the browser reports, the way a device in that region would. */
function withTimezone(timeZone: string) {
  const real = Intl.DateTimeFormat().resolvedOptions()
  vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({ ...real, timeZone })
}

function renderOnboarding(from?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const entry =
    from === undefined ? { pathname: '/onboarding' } : { pathname: '/onboarding', state: { from } }
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/new" element={<span>capture screen</span>} />
          <Route path="/visits/abc/processing" element={<span>processing screen</span>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function chooseRole(value: string) {
  fireEvent.change(screen.getByLabelText(/what you do/i), { target: { value } })
}

function click(name: RegExp) {
  fireEvent.click(screen.getByRole('button', { name }))
}

/**
 * The request bodies this screen sent, in order.
 *
 * Read structurally: `api.PATCH` is overloaded per path, so the generated call tuple
 * collapses to `never` and cannot be indexed for an assertion.
 */
function patchBodies(): unknown[] {
  const calls = vi.mocked(api.PATCH).mock.calls as unknown as [string, { body?: unknown }][]
  return calls.map((call) => call[1].body)
}

beforeEach(() => {
  vi.mocked(api.PATCH).mockReset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Onboarding', () => {
  it('prefills the timezone the device reports', () => {
    withTimezone('Asia/Manila')

    renderOnboarding()

    expect(screen.getByLabelText(/time zone/i)).toHaveValue('Asia/Manila')
  })

  it('sends the role and timezone, and omits a name that was left blank', async () => {
    // Every field on the server is apply-if-present, so an omitted name is a no-op
    // while an empty string would overwrite a real name with nothing.
    withTimezone('Asia/Manila')
    vi.mocked(api.PATCH).mockResolvedValue(patchResponse({ role_title: 'rn', jurisdiction: 'PH' }))

    renderOnboarding()
    chooseRole('rn')
    click(/continue/i)

    await waitFor(() => { expect(api.PATCH).toHaveBeenCalled() })
    const body = patchBodies()[0]
    expect(body).toMatchObject({ role_title: 'rn', timezone: 'Asia/Manila' })
    expect(body).not.toHaveProperty('full_name')
  })

  it('reports the Philippine regime the server derived, and what it costs', async () => {
    // The zone-to-jurisdiction mapping lives on the server. This screen states the
    // consequence of the answer it got back; it does not decide the answer.
    withTimezone('Asia/Manila')
    vi.mocked(api.PATCH).mockResolvedValue(patchResponse({ role_title: 'rn', jurisdiction: 'PH' }))

    renderOnboarding()
    chooseRole('rn')
    click(/continue/i)

    expect(await screen.findByText(/Philippines/i)).toBeInTheDocument()
    expect(screen.getByText(/RA 4200/)).toBeInTheDocument()
  })

  it('reports the United States regime for a US device', async () => {
    withTimezone('America/New_York')
    vi.mocked(api.PATCH).mockResolvedValue(patchResponse({ role_title: 'rn', jurisdiction: 'US' }))

    renderOnboarding()
    chooseRole('rn')
    click(/continue/i)

    expect(await screen.findByText(/United States/i)).toBeInTheDocument()
  })

  it('lets a nurse whose device zone is wrong correct the regime', async () => {
    // Only Asia/Manila maps to PH, so a Manila nurse whose phone reports
    // Asia/Singapore lands under the permissive regime. This is their way out.
    withTimezone('Asia/Singapore')
    vi.mocked(api.PATCH)
      .mockResolvedValueOnce(patchResponse({ role_title: 'rn', jurisdiction: 'US' }))
      .mockResolvedValueOnce(patchResponse({ role_title: 'rn', jurisdiction: 'PH' }))

    renderOnboarding()
    chooseRole('rn')
    click(/continue/i)
    fireEvent.click(await screen.findByRole('button', { name: /philippines/i }))

    await waitFor(() => { expect(api.PATCH).toHaveBeenCalledTimes(2) })
    expect(patchBodies()[1]).toEqual({ jurisdiction: 'PH' })
    expect(await screen.findByText(/RA 4200/)).toBeInTheDocument()
  })

  it('returns the user to the screen the gate interrupted', async () => {
    withTimezone('America/New_York')
    vi.mocked(api.PATCH).mockResolvedValue(patchResponse({ role_title: 'rn' }))

    renderOnboarding('/visits/abc/processing')
    chooseRole('rn')
    click(/continue/i)
    fireEvent.click(await screen.findByRole('button', { name: /finish setup/i }))

    expect(await screen.findByText('processing screen')).toBeInTheDocument()
  })

  it('goes to capture when nothing was interrupted', async () => {
    withTimezone('America/New_York')
    vi.mocked(api.PATCH).mockResolvedValue(patchResponse({ role_title: 'rn' }))

    renderOnboarding()
    chooseRole('rn')
    click(/continue/i)
    fireEvent.click(await screen.findByRole('button', { name: /finish setup/i }))

    expect(await screen.findByText('capture screen')).toBeInTheDocument()
  })

  it('keeps the user on the form when the save fails', async () => {
    withTimezone('America/New_York')
    vi.mocked(api.PATCH).mockResolvedValue({
      // FastAPI's OpenAPI export types every 422 `detail` as a list of validation
      // errors, but a route's own HTTPException sends a plain string. The cast
      // records that the generated type is wrong about this response, not the test.
      error: { detail: 'Unsupported time zone' } as unknown as never,
      response: new Response(null, { status: 422 }),
    })

    renderOnboarding()
    chooseRole('rn')
    click(/continue/i)

    expect(await screen.findByText(/Unsupported time zone/)).toBeInTheDocument()
    expect(screen.getByLabelText(/what you do/i)).toBeInTheDocument()
  })
})
