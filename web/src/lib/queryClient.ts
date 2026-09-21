import { QueryClient } from '@tanstack/react-query'

/**
 * Server state lives here; nothing is fetched inside useEffect.
 *
 * The retry rule matters for a field client on cellular: a 4xx means the request was
 * wrong and repeating it wastes the user's battery and data, while a 5xx or a dropped
 * connection is worth another attempt.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        const status = (error as { status?: number }).status
        if (status !== undefined && status >= 400 && status < 500) return false
        return failureCount < 3
      },
      refetchOnWindowFocus: false,
    },
  },
})

/**
 * Query keys are built here rather than spelled inline at each call site, so
 * invalidating everything under a resource cannot miss a caller that spelled its key
 * slightly differently.
 */
export const queryKeys = {
  health: () => ['health'] as const,
  // Keyed by visit so two capture screens open at once poll independently, and so
  // the review screen can invalidate exactly one visit's status once it lands.
  visitStatus: (visitId: string) => ['visits', visitId, 'status'] as const,
} as const
