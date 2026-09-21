import { beforeEach, describe, expect, it, vi } from 'vitest'

import { REFRESH_TOKEN_KEY, useAuthStore } from './auth'

describe('auth session store', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.getState().clear()
  })

  it('holds the access token in memory only', () => {
    // An access token in localStorage is readable by any script that gets to run on
    // the page. It is short-lived, so keeping it in memory costs nothing.
    useAuthStore.getState().setSession({ accessToken: 'access', refreshToken: 'refresh' })

    expect(useAuthStore.getState().accessToken).toBe('access')
    expect(localStorage.getItem('accessToken')).toBeNull()
    expect(JSON.stringify(localStorage)).not.toContain('access')
  })

  it('persists the refresh token so a reload can restore the session', () => {
    useAuthStore.getState().setSession({ accessToken: 'access', refreshToken: 'refresh' })

    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe('refresh')
  })

  it('reports an unauthenticated state before any session exists', () => {
    expect(useAuthStore.getState().isAuthenticated()).toBe(false)
  })

  it('reports authenticated once an access token is held', () => {
    useAuthStore.getState().setSession({ accessToken: 'access', refreshToken: 'refresh' })

    expect(useAuthStore.getState().isAuthenticated()).toBe(true)
  })

  it('clears both tokens on sign out', () => {
    useAuthStore.getState().setSession({ accessToken: 'access', refreshToken: 'refresh' })
    useAuthStore.getState().clear()

    expect(useAuthStore.getState().accessToken).toBeNull()
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull()
  })

  it('reads a persisted refresh token back', () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, 'from-a-previous-visit')

    expect(useAuthStore.getState().getRefreshToken()).toBe('from-a-previous-visit')
  })

  it('survives storage being unavailable', () => {
    // Private browsing and blocked site data make localStorage throw on access. A
    // storage failure must degrade to "not signed in", never crash the application.
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError')
    })
    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('SecurityError')
    })

    expect(() => {
      useAuthStore.getState().setSession({ accessToken: 'a', refreshToken: 'r' })
    }).not.toThrow()
    expect(useAuthStore.getState().getRefreshToken()).toBeNull()
    expect(useAuthStore.getState().accessToken).toBe('a')

    setItem.mockRestore()
    getItem.mockRestore()
  })
})
