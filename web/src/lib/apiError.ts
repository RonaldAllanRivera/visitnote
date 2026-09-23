/**
 * The reason the server gave, or a fallback.
 *
 * FastAPI's OpenAPI export always shapes a 422 `detail` as a list of validation
 * errors, regardless of what a route's own `HTTPException` actually sends -- and
 * several of this API's refusals send a plain string instead: an unsupported note
 * format, the RA 4200 capture-mode rejection. Reading `detail` as unknown rather
 * than trusting the generated shape is what lets those reasons reach the user
 * instead of being thrown away as a type mismatch.
 */
export function detailMessage(error: unknown, fallback: string): string {
  const detail = (error as { detail?: unknown } | null | undefined)?.detail
  return typeof detail === 'string' ? detail : fallback
}
