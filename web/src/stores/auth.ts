import { create } from 'zustand'

/**
 * Client-side session state.
 *
 * The split between the two tokens is deliberate:
 *
 * - The **access token lives in memory only**. It is short-lived, and anything in
 *   localStorage is readable by any script that manages to run on the page.
 * - The **refresh token is persisted**, because without it a page reload would sign
 *   the user out. This API is header-authenticated with no cookies, so there is no
 *   HttpOnly option available; the mitigation is that refresh tokens are single-use
 *   and rotated, so a stolen one is detected the moment the real user refreshes.
 *
 * The native client stores the refresh token in the platform keystore instead, which
 * is why this concern is isolated behind these accessors rather than spread through
 * the app.
 */

export const REFRESH_TOKEN_KEY = 'visitnote.refresh'

interface Session {
  accessToken: string
  refreshToken: string
}

interface AuthState {
  accessToken: string | null
  setSession: (session: Session) => void
  setAccessToken: (token: string) => void
  getRefreshToken: () => string | null
  isAuthenticated: () => boolean
  clear: () => void
}

/**
 * Storage access is wrapped because it genuinely throws: private browsing, blocked
 * site data, and exhausted quota all raise on read or write. A storage failure must
 * degrade to "not signed in", never take down the page.
 */
function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    // Session simply will not survive a reload. Everything else still works.
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,

  setSession: ({ accessToken, refreshToken }) => {
    writeStored(REFRESH_TOKEN_KEY, refreshToken)
    set({ accessToken })
  },

  setAccessToken: (accessToken) => {
    set({ accessToken })
  },

  getRefreshToken: () => readStored(REFRESH_TOKEN_KEY),

  isAuthenticated: () => get().accessToken !== null,

  clear: () => {
    writeStored(REFRESH_TOKEN_KEY, null)
    set({ accessToken: null })
  },
}))
