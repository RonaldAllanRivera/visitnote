import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'

import { SystemStatus } from './SystemStatus'

vi.mock('@/api/client', () => ({
  api: {
    GET: vi.fn().mockResolvedValue({
      data: {
        status: 'ok',
        environment: 'test',
        version: '0.1.0',
        dependencies: {
          database: { status: 'ok', latency_ms: 1.2, error: null },
          redis: { status: 'error', latency_ms: null, error: 'unreachable' },
        },
      },
      error: undefined,
      // The component inspects the response status so a 503 -- which carries a valid
      // HealthResponse body -- is surfaced as an error instead of rendered as health.
      response: new Response(null, { status: 200 }),
    }),
  },
}))

function renderWithQuery(ui: React.ReactNode) {
  // Retries off: a test asserting an error path should fail immediately, not after
  // three backoff delays.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('SystemStatus', () => {
  it('renders each dependency with its latency', async () => {
    renderWithQuery(<SystemStatus />)

    expect(await screen.findByText('database')).toBeInTheDocument()
    expect(screen.getByText('1.2 ms')).toBeInTheDocument()
  })

  it('shows an em dash rather than a zero when latency is unavailable', async () => {
    renderWithQuery(<SystemStatus />)

    // A failed dependency has no latency. Rendering 0 ms would read as "instant",
    // which is the opposite of what happened.
    expect(await screen.findByText('redis')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('reports the API as unreachable on a 503 instead of rendering its body', async () => {
    // A degraded API answers 503 with a well-formed HealthResponse. Rendering that
    // body would show a reassuring table while the service is actually down.
    vi.mocked(api.GET).mockResolvedValueOnce({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 503 }),
    } as unknown as Awaited<ReturnType<typeof api.GET>>)

    renderWithQuery(<SystemStatus />)

    expect(await screen.findByText('API unreachable.')).toBeInTheDocument()
  })
})
