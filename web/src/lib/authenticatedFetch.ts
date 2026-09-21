import { useAuthStore } from '@/stores/auth'

import { RefreshCoordinator } from './refreshCoordinator'

/**
 * A fetch wrapper that attaches the access token and transparently recovers from an
 * expired one.
 *
 * Built as a fetch wrapper rather than as response middleware because recovering
 * from a 401 requires *replaying* the original request, and a middleware hook that
 * only observes the response cannot do that.
 *
 * Three failure modes this is shaped to avoid:
 *
 *  1. **Refresh storms.** Refresh tokens are single-use. Several concurrent 401s must
 *     produce exactly one refresh, or the client replays a rotated token and the
 *     server correctly concludes it was stolen.
 *  2. **Infinite recursion.** A failing refresh call must never itself trigger a
 *     refresh.
 *  3. **Dropping the rotated token.** Each refresh returns a *new* refresh token. Not
 *     storing it means the next refresh replays the old one, with the same outcome
 *     as (1).
 */

const REFRESH_PATH = '/api/v1/auth/refresh'

/**
 * Resolve a possibly-relative path to an absolute URL.
 *
 * `new Request('/path')` resolves against the document base in a browser but throws
 * in Node. Resolving explicitly is needed regardless: in production the API is on a
 * different origin from the static site, so a bare path would address the wrong host.
 */
function absolute(input: RequestInfo | URL): RequestInfo | URL {
  if (typeof input !== 'string') return input
  if (/^https?:\/\//.test(input)) return input

  const base =
    import.meta.env.VITE_API_BASE_URL ??
    (typeof location === 'undefined' ? 'http://localhost' : location.origin)

  return new URL(input, base).toString()
}

interface RefreshResponse {
  access_token: string
  refresh_token: string
}

interface Options {
  baseFetch?: typeof fetch
  onSessionExpired?: () => void
}

export function createAuthenticatedFetch({
  baseFetch = globalThis.fetch.bind(globalThis),
  onSessionExpired,
}: Options = {}): typeof fetch {
  const store = useAuthStore

  const coordinator = new RefreshCoordinator(async () => {
    const refreshToken = store.getState().getRefreshToken()
    if (refreshToken === null) throw new Error('no refresh token')

    const response = await baseFetch(
      new Request(absolute(REFRESH_PATH), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      }),
    )
    if (!response.ok) throw new Error('refresh rejected')

    const body = (await response.json()) as RefreshResponse
    store.getState().setSession({
      accessToken: body.access_token,
      refreshToken: body.refresh_token,
    })
    return body.access_token
  })

  return async (input, init) => {
    const build = (token: string | null): Request => {
      const request = new Request(absolute(input), init)
      if (token !== null) request.headers.set('Authorization', `Bearer ${token}`)
      return request
    }

    const response = await baseFetch(build(store.getState().accessToken))

    const isRefreshCall = new Request(absolute(input)).url.includes(REFRESH_PATH)
    if (response.status !== 401 || isRefreshCall) return response

    if (store.getState().getRefreshToken() === null) return response

    try {
      const accessToken = await coordinator.refresh()
      return await baseFetch(build(accessToken))
    } catch {
      // The session is genuinely over. Clear it and hand the original 401 back so the
      // caller still sees a normal failed response rather than a thrown error.
      store.getState().clear()
      onSessionExpired?.()
      return response
    }
  }
}
