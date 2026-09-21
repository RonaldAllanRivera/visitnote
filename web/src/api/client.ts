import createClient from 'openapi-fetch'

import type { paths } from './schema'

/**
 * The single typed entry point to the API.
 *
 * Types are generated from the FastAPI OpenAPI schema, so a backend contract change
 * surfaces here as a compile error rather than as a runtime surprise in a caregiver's
 * hands. Nothing in the app calls `fetch` directly.
 */
export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? '',
})

export type ApiPaths = paths
