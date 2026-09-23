import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { profileFixture } from '@/test/fixtures'

import { SignIn } from './SignIn'

vi.mock('@/api/client', () => ({ api: { GET: vi.fn(), POST: vi.fn() } }))

function renderSignIn() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SignIn />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function signIn() {
  fireEvent.change(screen.getByLabelText(/email/i), {
    target: { value: 'nurse@example.test' },
  })
  fireEvent.change(screen.getByLabelText(/password/i), {
    target: { value: 'a-sufficiently-long-password' },
  })
  fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }))
}

beforeEach(() => {
  localStorage.clear()
  useAuthStore.getState().clear()
  vi.mocked(api.GET).mockReset()
  vi.mocked(api.POST).mockReset()
  vi.mocked(api.GET).mockResolvedValue({
    data: profileFixture(),
    response: new Response(null, { status: 200 }),
  })
})

describe('SignIn', () => {
  it('has the account limits in hand before the first screen needs them', async () => {
    // "Set on login" without minting anything into the token: the client fetches the
    // profile as part of finishing sign-in, so the capture screen knows which modes
    // are permitted rather than rendering an empty set and filling it in late.
    vi.mocked(api.POST).mockResolvedValue({
      data: { access_token: 'a', refresh_token: 'r', token_type: 'bearer', expires_in: 900 },
      response: new Response(null, { status: 200 }),
    })

    renderSignIn()
    signIn()

    await waitFor(() => { expect(api.GET).toHaveBeenCalledWith('/api/v1/auth/me') })
  })

  it('does not fetch a profile when the credentials were refused', async () => {
    vi.mocked(api.POST).mockResolvedValue({
      error: { detail: 'Invalid email or password.' } as unknown as never,
      response: new Response(null, { status: 401 }),
    })

    renderSignIn()
    signIn()

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(api.GET).not.toHaveBeenCalled()
  })
})
