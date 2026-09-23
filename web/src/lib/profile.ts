import { useQuery } from '@tanstack/react-query'

import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { queryKeys } from '@/lib/queryClient'
import { useAuthStore } from '@/stores/auth'

export type UserProfile = components['schemas']['UserProfile']

/**
 * The signed-in user's profile, as server state rather than store state.
 *
 * It lives here instead of in the auth store because it is the server's answer and
 * not the client's: jurisdiction is derived server-side from the timezone, and a
 * copy in the store would be a second place for it to be wrong.
 */
/**
 * The query itself, separate from the hook that subscribes to it.
 *
 * Shared so sign-in can prefetch the profile with exactly the query a component will
 * later read. A prefetch that used a different key, or a different fetcher, would
 * warm a cache entry nobody looks at.
 */
export const profileQuery = {
  queryKey: queryKeys.profile(),
  queryFn: async (): Promise<UserProfile> => {
    const { data, response } = await api.GET('/api/v1/auth/me')
    // Checked on the response rather than the typed `error` branch: an authenticated
    // route's 401 comes from a dependency and is not declared in the schema, so the
    // generated error type is `never`.
    if (!response.ok || !data) throw new Error('Could not load your profile')
    return data
  },
}

export function useProfile() {
  // Subscribed rather than read once, so signing in starts the fetch. The refresh
  // token covers the moment just after a reload, when the access token is always
  // absent but the session is perfectly good.
  const accessToken = useAuthStore((state) => state.accessToken)
  const hasSession = accessToken !== null || useAuthStore.getState().getRefreshToken() !== null

  return useQuery({
    ...profileQuery,
    // The public landing page renders the app shell, which reads this. Fetching a
    // profile with no session would 401 on every anonymous visit and trip the
    // session-expired handler on a page that never claimed anyone was signed in.
    enabled: hasSession,
  })
}

/**
 * Whether this account still has to be asked where and how it works.
 *
 * `role_title` is the signal because it is the only profile field registration
 * leaves unset -- `default_note_format` is populated from the account's defaulted
 * jurisdiction at sign-up, so a populated format proves nothing about whether a
 * human was ever asked anything.
 *
 * An absent profile counts as not onboarded. The gate exists to keep a visit from
 * being captured under a jurisdiction nobody chose, and an unanswered fetch is not
 * evidence that someone chose one.
 */
export function needsOnboarding(profile: UserProfile | undefined): boolean {
  return profile?.role_title == null
}
