import { Navigate, Outlet, useLocation } from 'react-router'

import { needsOnboarding, useProfile } from '@/lib/profile'

/**
 * Keeps capture behind the question that decides which rules apply.
 *
 * Every account is created as `US` -- the permissive regime -- and the only code path
 * that ever changes that is this product's onboarding PATCH. Until a user has been
 * through it, a Philippine nurse is a US account: they resolve to US templates rather
 * than FDAR, and the RA 4200 refusal on `live_audio` cannot fire for them, because
 * their row says they are somewhere it does not apply. The server is right in both
 * cases; it is simply answering about the wrong jurisdiction.
 *
 * Nested inside `RequireAuth`, and the onboarding route itself is deliberately left
 * outside this guard -- gating the screen that clears the gate would loop.
 */
export function RequireOnboarding() {
  const location = useLocation()
  const { data: profile, isPending } = useProfile()

  // Neither branch until the answer is in. Deciding on an unresolved profile would
  // send an onboarded user back to the form on every reload, and rendering the
  // capture screen optimistically would be the exact silent-default this prevents.
  if (isPending) return null

  if (needsOnboarding(profile)) {
    // `replace` keeps the gated URL out of history, so Back from onboarding does not
    // return to a page that only redirects again. `state` carries the destination so
    // onboarding can finish by sending the user where they were going.
    return <Navigate to="/onboarding" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
