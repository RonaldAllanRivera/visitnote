import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '@/stores/auth'

import { createAuthenticatedFetch } from './authenticatedFetch'

/** Reads the Request a mocked fetch received, failing loudly rather than asserting. */
function requestAt(mock: { mock: { calls: unknown[][] } }, index: number): Request {
  const call = mock.mock.calls.at(index)
  if (!call) throw new Error(`no fetch call at index ${String(index)}`)
  return call[0] as Request
}

function jsonResponse(status: number, body: unknown = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('createAuthenticatedFetch', () => {
  let onSessionExpired: ReturnType<typeof vi.fn>

  beforeEach(() => {
    localStorage.clear()
    useAuthStore.getState().clear()
    onSessionExpired = vi.fn()
  })

  it('sends the access token as a bearer credential', async () => {
    useAuthStore.getState().setSession({ accessToken: 'access-1', refreshToken: 'refresh-1' })
    const baseFetch = vi.fn().mockResolvedValue(jsonResponse(200))

    await createAuthenticatedFetch({ baseFetch, onSessionExpired })('/api/v1/auth/me')

    expect(requestAt(baseFetch, 0).headers.get('Authorization')).toBe('Bearer access-1')
  })

  it('sends no authorization header when there is no session', async () => {
    const baseFetch = vi.fn().mockResolvedValue(jsonResponse(200))

    await createAuthenticatedFetch({ baseFetch, onSessionExpired })('/api/v1/plans')

    expect(requestAt(baseFetch, 0).headers.get('Authorization')).toBeNull()
  })

  it('refreshes and retries once when the access token has expired', async () => {
    useAuthStore.getState().setSession({ accessToken: 'stale', refreshToken: 'refresh-1' })
    const baseFetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(200, { access_token: 'fresh', refresh_token: 'r2' }))
      .mockResolvedValueOnce(jsonResponse(200, { email: 'a@b.com' }))

    const response = await createAuthenticatedFetch({ baseFetch, onSessionExpired })(
      '/api/v1/auth/me',
    )

    expect(response.status).toBe(200)
    expect(requestAt(baseFetch, 2).headers.get('Authorization')).toBe('Bearer fresh')
  })

  it('stores the rotated refresh token after a successful refresh', async () => {
    useAuthStore.getState().setSession({ accessToken: 'stale', refreshToken: 'refresh-1' })
    const baseFetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(200, { access_token: 'fresh', refresh_token: 'r2' }))
      .mockResolvedValueOnce(jsonResponse(200))

    await createAuthenticatedFetch({ baseFetch, onSessionExpired })('/api/v1/auth/me')

    // Dropping the rotated token would make the *next* refresh replay the old one,
    // which the server reads as theft and answers by killing the session.
    expect(useAuthStore.getState().getRefreshToken()).toBe('r2')
  })

  it('gives up and ends the session when the refresh is rejected', async () => {
    useAuthStore.getState().setSession({ accessToken: 'stale', refreshToken: 'revoked' })
    const baseFetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401))
      .mockResolvedValueOnce(jsonResponse(401))

    const response = await createAuthenticatedFetch({ baseFetch, onSessionExpired })(
      '/api/v1/auth/me',
    )

    expect(response.status).toBe(401)
    expect(onSessionExpired).toHaveBeenCalledOnce()
    expect(useAuthStore.getState().accessToken).toBeNull()
  })

  it('does not attempt a refresh when there is no refresh token', async () => {
    const baseFetch = vi.fn().mockResolvedValue(jsonResponse(401))

    await createAuthenticatedFetch({ baseFetch, onSessionExpired })('/api/v1/auth/me')

    expect(baseFetch).toHaveBeenCalledTimes(1)
  })

  it('never tries to refresh a failing refresh call', async () => {
    // Infinite recursion otherwise: refresh 401s, which triggers a refresh, which
    // 401s. This is the classic way an interceptor takes down a browser tab.
    useAuthStore.getState().setSession({ accessToken: 'stale', refreshToken: 'revoked' })
    const baseFetch = vi.fn().mockResolvedValue(jsonResponse(401))

    await createAuthenticatedFetch({ baseFetch, onSessionExpired })('/api/v1/auth/refresh', {
      method: 'POST',
    })

    expect(baseFetch).toHaveBeenCalledTimes(1)
  })

  it('refreshes once when several requests expire together', async () => {
    useAuthStore.getState().setSession({ accessToken: 'stale', refreshToken: 'refresh-1' })
    const baseFetch = vi.fn().mockImplementation((request: Request) => {
      if (request.url.includes('/auth/refresh')) {
        return Promise.resolve(jsonResponse(200, { access_token: 'fresh', refresh_token: 'r2' }))
      }
      const auth = request.headers.get('Authorization')
      return Promise.resolve(auth === 'Bearer fresh' ? jsonResponse(200) : jsonResponse(401))
    })

    const authFetch = createAuthenticatedFetch({ baseFetch, onSessionExpired })
    await Promise.all([authFetch('/api/v1/a'), authFetch('/api/v1/b'), authFetch('/api/v1/c')])

    const refreshCalls = baseFetch.mock.calls.filter(([request]) =>
      (request as Request).url.includes('/auth/refresh'),
    )
    expect(refreshCalls).toHaveLength(1)
  })

  it('leaves a non-401 failure alone', async () => {
    useAuthStore.getState().setSession({ accessToken: 'access-1', refreshToken: 'refresh-1' })
    const baseFetch = vi.fn().mockResolvedValue(jsonResponse(500))

    const response = await createAuthenticatedFetch({ baseFetch, onSessionExpired })('/api/v1/x')

    expect(response.status).toBe(500)
    expect(baseFetch).toHaveBeenCalledTimes(1)
  })
})
