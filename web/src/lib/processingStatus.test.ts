import { describe, expect, it } from 'vitest'

import {
  describeStage,
  isTerminal,
  pollIntervalMs,
  stageProgress,
} from '@/lib/processingStatus'

describe('isTerminal', () => {
  it('treats a ready visit as finished', () => {
    expect(isTerminal('ready')).toBe(true)
  })

  it('treats a failed visit as finished', () => {
    expect(isTerminal('failed')).toBe(true)
  })

  it('treats a signed visit as finished', () => {
    // A note signed before this screen was reopened must not restart polling.
    expect(isTerminal('signed')).toBe(true)
  })

  it('keeps polling while the visit is processing', () => {
    expect(isTerminal('processing')).toBe(false)
  })

  it('keeps polling a visit that is only uploaded', () => {
    // The worker may not have picked it up yet; that is not a finished state.
    expect(isTerminal('uploaded')).toBe(false)
  })
})

describe('pollIntervalMs', () => {
  it('stops polling once the visit is finished', () => {
    // The bug this prevents: a forgotten tab polling the API every two seconds
    // until the phone is closed, on a caregiver's mobile data.
    expect(pollIntervalMs('ready', 0)).toBe(false)
  })

  it('stops polling a failed visit', () => {
    expect(pollIntervalMs('failed', 60_000)).toBe(false)
  })

  it('polls quickly at first, while a short note may already be done', () => {
    expect(pollIntervalMs('processing', 0)).toBe(2_000)
  })

  it('backs off once the work is clearly going to take a while', () => {
    const early = pollIntervalMs('processing', 0)
    const later = pollIntervalMs('processing', 120_000)

    expect(later).toBeGreaterThan(early as number)
  })

  it('never backs off beyond a ceiling a person would notice', () => {
    // A finished note must still appear promptly; ten seconds is the most a user
    // should wait to be told their note is ready.
    expect(pollIntervalMs('processing', 3_600_000)).toBe(10_000)
  })
})

describe('describeStage', () => {
  it('names the stage in the user’s terms, not the pipeline’s', () => {
    expect(describeStage('processing', 'transcribe')).toBe('Transcribing the recording')
  })

  it('explains a visit that is queued but not yet started', () => {
    expect(describeStage('uploaded', null)).toBe('Waiting for a free worker')
  })

  it('reports a finished note', () => {
    expect(describeStage('ready', 'complete')).toBe('Note ready')
  })

  it('reports a failure without pretending to be busy', () => {
    expect(describeStage('failed', 'normalize')).toBe('Processing failed')
  })

  it('falls back to a neutral label for a stage it does not know', () => {
    // A new pipeline stage must not render as blank or as "undefined".
    expect(describeStage('processing', 'a-stage-from-the-future')).toBe('Processing')
  })
})

describe('stageProgress', () => {
  it('reports no progress before the work starts', () => {
    expect(stageProgress('queued')).toBe(0)
  })

  it('reports completion at the end', () => {
    expect(stageProgress('complete')).toBe(1)
  })

  it('advances monotonically through the pipeline', () => {
    const stages = ['queued', 'download', 'normalize', 'transcribe', 'generate', 'persist', 'complete'] as const
    const values = stages.map(stageProgress)

    expect(values).toEqual([...values].sort((a, b) => a - b))
    expect(new Set(values).size).toBe(values.length)
  })

  it('reports no progress for an unknown stage rather than guessing', () => {
    expect(stageProgress(null)).toBe(0)
  })
})
