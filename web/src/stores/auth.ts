import { create } from 'zustand'

/**
 * Client-side session state.
 *
 * The access token is held in memory only -- never localStorage. A token in
 * localStorage is readable by any script that manages to run on the page, and this
 * application handles clinical documentation. The refresh token is handled separately
 * by the auth flow in phase 2, and survives a reload; the access token does not.
 */
interface AuthState {
  accessToken: string | null
  setAccessToken: (token: string | null) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  setAccessToken: (accessToken) => {
    set({ accessToken })
  },
  clear: () => {
    set({ accessToken: null })
  },
}))
