import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { useAuthStore } from '@/stores/auth'

import { isSessionRestorable } from './RequireAuth'

describe('isSessionRestorable', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.getState().clear()
  })

  it('is false with no tokens at all', () => {
    expect(isSessionRestorable()).toBe(false)
  })

  it('is true while an access token is held', () => {
    useAuthStore.getState().setSession({ accessToken: 'a', refreshToken: 'r' })
    expect(isSessionRestorable()).toBe(true)
  })

  it('is true after a reload, when only the refresh token survives', () => {
    // The access token is memory-only, so every reload starts without one. Treating
    // that as signed-out would bounce the user to the login page on every refresh of
    // the browser, despite holding a perfectly good session.
    useAuthStore.getState().setSession({ accessToken: 'a', refreshToken: 'r' })
    useAuthStore.setState({ accessToken: null })

    expect(isSessionRestorable()).toBe(true)
  })

  it('is false once the session has been cleared', () => {
    useAuthStore.getState().setSession({ accessToken: 'a', refreshToken: 'r' })
    useAuthStore.getState().clear()

    expect(isSessionRestorable()).toBe(false)
  })
})

describe('render smoke', () => {
  it('renders nothing meaningful without a router, but imports cleanly', () => {
    render(<span>ok</span>)
    expect(screen.getByText('ok')).toBeInTheDocument()
  })
})
