/**
 * Serialises access-token refreshes.
 *
 * Refresh tokens on this API are single-use: presenting one rotates it, and
 * presenting an already-rotated token is treated as theft and destroys the session.
 *
 * That makes concurrency a correctness problem, not a performance one. A dashboard
 * that mounts six queries against an expired access token produces six simultaneous
 * 401s; six independent refreshes would send the same refresh token six times, and
 * the server would quite correctly conclude the token had been stolen and log the
 * user out. The client would have attacked itself.
 *
 * So: at most one refresh is ever in flight, and every caller that arrives while it
 * is running waits on the same promise.
 */
export class RefreshCoordinator {
  #inFlight: Promise<string> | null = null

  constructor(private readonly performRefresh: () => Promise<string>) {}

  refresh(): Promise<string> {
    // Callers arriving mid-flight join the existing attempt rather than starting one.
    this.#inFlight ??= this.performRefresh().finally(() => {
      // Cleared on settle, success or failure, so a later attempt is never blocked
      // by a stale rejected promise. A user who signs back in must be able to
      // refresh again in the same page session.
      this.#inFlight = null
    })

    return this.#inFlight
  }
}
