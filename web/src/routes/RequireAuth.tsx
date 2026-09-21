import { Navigate, Outlet, useLocation } from 'react-router'

import { useAuthStore } from '@/stores/auth'

/**
 * Whether a session might still be alive.
 *
 * The access token lives in memory only, so it is always absent immediately after a
 * page reload. Treating that as signed-out would bounce the user to the login screen
 * every time they refresh the browser while holding a perfectly good session. A
 * surviving refresh token means the session is worth attempting to restore -- the
 * authenticated fetch layer will exchange it on the first request.
 */
export function isSessionRestorable(): boolean {
  const state = useAuthStore.getState()
  return state.isAuthenticated() || state.getRefreshToken() !== null
}

export function RequireAuth() {
  const accessToken = useAuthStore((state) => state.accessToken)
  const location = useLocation()

  if (accessToken === null && !isSessionRestorable()) {
    // `replace` keeps the protected URL out of history, so Back after signing out
    // does not return to a page that will only redirect again. `state` carries the
    // intended destination so sign-in can return the user to it.
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
