import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'

import { Processing } from './Processing'

vi.mock('@/api/client', () => ({ api: { GET: vi.fn() } }))

type StatusBody = {
  visit_id: string
  status: string
  stage: string | null
  job_status: string | null
  attempts: number
  error: string | null
  note_id: string | null
}

const VISIT_ID = '11111111-1111-1111-1111-111111111111'
const NOTE_ID = '22222222-2222-2222-2222-222222222222'

function statusResponse(overrides: Partial<StatusBody> = {}) {
  return {
    data: {
      visit_id: VISIT_ID,
      status: 'processing',
      stage: 'transcribe',
      job_status: 'running',
      attempts: 1,
      error: null,
      note_id: null,
      ...overrides,
    },
    error: undefined,
    response: new Response(null, { status: 200 }),
  }
}

function renderProcessing() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/visits/${VISIT_ID}/processing`]}>
        <Routes>
          <Route path="/visits/:visitId/processing" element={<Processing />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.GET).mockReset()
})

describe('Processing', () => {
  it('names the stage the pipeline is on', async () => {
    // "Processing" for two minutes is indistinguishable from "hung", which is how a
    // caregiver ends up re-recording a visit that was working fine.
    vi.mocked(api.GET).mockResolvedValue(statusResponse())

    renderProcessing()

    expect(await screen.findByText('Transcribing the recording')).toBeInTheDocument()
  })

  it('reports a visit that has not been picked up yet', async () => {
    vi.mocked(api.GET).mockResolvedValue(statusResponse({ status: 'uploaded', stage: null }))

    renderProcessing()

    expect(await screen.findByText('Waiting for a free worker')).toBeInTheDocument()
  })

  it('announces a finished note', async () => {
    vi.mocked(api.GET).mockResolvedValue(
      statusResponse({ status: 'ready', stage: 'complete', job_status: 'succeeded' }),
    )

    renderProcessing()

    expect(await screen.findByText('Note ready')).toBeInTheDocument()
  })

  it('links to the note once one exists', async () => {
    // Every existing fixture here leaves note_id null, so this branch -- the whole
    // reason a nurse would visit this screen -- was previously untested.
    vi.mocked(api.GET).mockResolvedValue(
      statusResponse({ status: 'ready', stage: 'complete', note_id: NOTE_ID }),
    )

    renderProcessing()

    const link = await screen.findByRole('link', { name: /read and correct your note/i })
    expect(link).toHaveAttribute('href', `/notes/${NOTE_ID}`)
  })

  it('shows the recorded reason when processing failed', async () => {
    vi.mocked(api.GET).mockResolvedValue(
      statusResponse({
        status: 'failed',
        stage: 'normalize',
        job_status: 'failed',
        error: 'audio could not be decoded',
      }),
    )

    renderProcessing()

    expect(await screen.findByText('Processing failed')).toBeInTheDocument()
    expect(screen.getByText(/audio could not be decoded/)).toBeInTheDocument()
  })

  it('does not claim to be busy while a visit is failed', async () => {
    vi.mocked(api.GET).mockResolvedValue(
      statusResponse({ status: 'failed', stage: 'generate', error: null }),
    )

    renderProcessing()

    await screen.findByText('Processing failed')
    // An indeterminate bar next to "failed" reads as "still working on it".
    expect(screen.getByRole('progressbar')).not.toHaveValue()
  })

  it('tells the user when the work is on a second attempt', async () => {
    // Otherwise a retry looks identical to a first run that is simply slow.
    vi.mocked(api.GET).mockResolvedValue(statusResponse({ attempts: 2 }))

    renderProcessing()

    expect(await screen.findByText(/Attempt 2/)).toBeInTheDocument()
  })

  it('does not nag about attempts once the note is ready', async () => {
    vi.mocked(api.GET).mockResolvedValue(
      statusResponse({ status: 'ready', stage: 'complete', attempts: 2 }),
    )

    renderProcessing()

    await screen.findByText('Note ready')
    expect(screen.queryByText(/Attempt 2/)).not.toBeInTheDocument()
  })

  it('surfaces an unreachable API rather than an empty screen', async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 500 }),
    })

    renderProcessing()

    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('stops polling once the visit reaches a terminal state', async () => {
    // The bug this prevents: a forgotten tab polling forever on mobile data.
    vi.mocked(api.GET).mockResolvedValue(
      statusResponse({ status: 'ready', stage: 'complete' }),
    )

    renderProcessing()
    await screen.findByText('Note ready')
    const callsAfterSettling = vi.mocked(api.GET).mock.calls.length

    await new Promise((resolve) => setTimeout(resolve, 150))

    expect(vi.mocked(api.GET).mock.calls.length).toBe(callsAfterSettling)
  })
})
