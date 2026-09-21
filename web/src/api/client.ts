import createClient from 'openapi-fetch'

import { createAuthenticatedFetch } from '@/lib/authenticatedFetch'

import type { paths } from './schema'

/**
 * The single typed entry point to the API.
 *
 * Types are generated from the FastAPI OpenAPI schema, so a backend contract change
 * surfaces here as a compile error rather than as a runtime surprise in a caregiver's
 * hands. Nothing in the app calls `fetch` directly.
 *
 * The custom fetch attaches the access token and recovers from an expired one. That
 * recovery is a single shared coordinator, because refresh tokens are single-use and
 * two concurrent refreshes would look like token theft to the server.
 */

/** Set when the session ends irrecoverably, so the router can send the user to sign in. */
let sessionExpiredHandler: (() => void) | undefined

export function onSessionExpired(handler: () => void): void {
  sessionExpiredHandler = handler
}

export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? '',
  fetch: createAuthenticatedFetch({
    onSessionExpired: () => sessionExpiredHandler?.(),
  }),
})

export type ApiPaths = paths
