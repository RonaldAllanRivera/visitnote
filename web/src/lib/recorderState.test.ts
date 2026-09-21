import { describe, expect, it } from 'vitest'

import { initialRecorderState, recorderReducer } from './recorderState'

describe('recorderReducer', () => {
  it('starts idle', () => {
    expect(initialRecorderState.phase).toBe('idle')
  })

  it('moves to recording when permission is granted', () => {
    const state = recorderReducer(initialRecorderState, { type: 'started' })
    expect(state.phase).toBe('recording')
  })

  it('records the reason when permission is denied', () => {
    // The browser gives a generic error. The user needs to know it is their
    // microphone permission, not a bug in the app.
    const state = recorderReducer(initialRecorderState, {
      type: 'failed',
      reason: 'Microphone permission denied',
    })
    expect(state.phase).toBe('error')
    expect(state.error).toBe('Microphone permission denied')
  })

  it('accumulates elapsed seconds while recording', () => {
    let state = recorderReducer(initialRecorderState, { type: 'started' })
    state = recorderReducer(state, { type: 'tick', seconds: 5 })
    expect(state.elapsedSeconds).toBe(5)
  })

  it('ignores ticks when not recording', () => {
    // A timer that fires once more after stop would show a duration longer than the
    // audio, which then disagrees with the note.
    const state = recorderReducer(initialRecorderState, { type: 'tick', seconds: 5 })
    expect(state.elapsedSeconds).toBe(0)
  })

  it('keeps the elapsed time when paused', () => {
    let state = recorderReducer(initialRecorderState, { type: 'started' })
    state = recorderReducer(state, { type: 'tick', seconds: 12 })
    state = recorderReducer(state, { type: 'paused' })

    expect(state.phase).toBe('paused')
    expect(state.elapsedSeconds).toBe(12)
  })

  it('does not advance the clock while paused', () => {
    let state = recorderReducer(initialRecorderState, { type: 'started' })
    state = recorderReducer(state, { type: 'tick', seconds: 12 })
    state = recorderReducer(state, { type: 'paused' })
    state = recorderReducer(state, { type: 'tick', seconds: 20 })

    expect(state.elapsedSeconds).toBe(12)
  })

  it('resumes from where it paused', () => {
    let state = recorderReducer(initialRecorderState, { type: 'started' })
    state = recorderReducer(state, { type: 'tick', seconds: 12 })
    state = recorderReducer(state, { type: 'paused' })
    state = recorderReducer(state, { type: 'resumed' })

    expect(state.phase).toBe('recording')
    expect(state.elapsedSeconds).toBe(12)
  })

  it('carries the recording when it stops', () => {
    const recording = new Blob(['x'], { type: 'audio/webm' })
    let state = recorderReducer(initialRecorderState, { type: 'started' })
    state = recorderReducer(state, { type: 'stopped', blob: recording })

    expect(state.phase).toBe('stopped')
    expect(state.blob).toBe(recording)
  })

  it('reports when the maximum length has been reached', () => {
    // Ninety minutes. Transcription cost and job duration both scale with length,
    // and a recording left running by accident is the usual cause of both.
    let state = recorderReducer(initialRecorderState, { type: 'started' })
    state = recorderReducer(state, { type: 'tick', seconds: 90 * 60 })

    expect(state.atMaxDuration).toBe(true)
  })

  it('is not at the maximum a second earlier', () => {
    let state = recorderReducer(initialRecorderState, { type: 'started' })
    state = recorderReducer(state, { type: 'tick', seconds: 90 * 60 - 1 })

    expect(state.atMaxDuration).toBe(false)
  })

  it('clears a previous error when recording starts again', () => {
    let state = recorderReducer(initialRecorderState, { type: 'failed', reason: 'denied' })
    state = recorderReducer(state, { type: 'started' })

    expect(state.error).toBeNull()
  })

  it('returns to idle on reset, discarding the recording', () => {
    let state = recorderReducer(initialRecorderState, { type: 'started' })
    state = recorderReducer(state, { type: 'stopped', blob: new Blob(['x']) })
    state = recorderReducer(state, { type: 'reset' })

    expect(state).toEqual(initialRecorderState)
  })
})
