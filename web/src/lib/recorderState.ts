/**
 * Recorder state, as a reducer.
 *
 * Kept separate from the `MediaRecorder` API so the rules that matter -- what the
 * clock does when paused, when the maximum length is reached, whether a stale timer
 * tick can inflate the duration -- are testable without a microphone, a browser
 * permission prompt, or a real recording.
 */

/** Ninety minutes. Transcription cost and job duration both scale with length, and a
 *  recording accidentally left running is the usual cause of both. */
export const MAX_DURATION_SECONDS = 90 * 60

export type RecorderPhase = 'idle' | 'recording' | 'paused' | 'stopped' | 'error'

export interface RecorderState {
  phase: RecorderPhase
  elapsedSeconds: number
  blob: Blob | null
  error: string | null
  atMaxDuration: boolean
}

export type RecorderAction =
  | { type: 'started' }
  | { type: 'paused' }
  | { type: 'resumed' }
  | { type: 'tick'; seconds: number }
  | { type: 'stopped'; blob: Blob }
  | { type: 'failed'; reason: string }
  | { type: 'reset' }

export const initialRecorderState: RecorderState = {
  phase: 'idle',
  elapsedSeconds: 0,
  blob: null,
  error: null,
  atMaxDuration: false,
}

export function recorderReducer(
  state: RecorderState,
  action: RecorderAction,
): RecorderState {
  switch (action.type) {
    case 'started':
      // Clears any previous error, so a retry after a denied permission prompt does
      // not show the old message beside a working recorder.
      return { ...initialRecorderState, phase: 'recording' }

    case 'paused':
      return state.phase === 'recording' ? { ...state, phase: 'paused' } : state

    case 'resumed':
      return state.phase === 'paused' ? { ...state, phase: 'recording' } : state

    case 'tick':
      // Only while actually recording. A timer that fires once more after stop would
      // report a duration longer than the audio, which then disagrees with the note.
      if (state.phase !== 'recording') return state
      return {
        ...state,
        elapsedSeconds: action.seconds,
        atMaxDuration: action.seconds >= MAX_DURATION_SECONDS,
      }

    case 'stopped':
      return { ...state, phase: 'stopped', blob: action.blob }

    case 'failed':
      return { ...state, phase: 'error', error: action.reason }

    case 'reset':
      return initialRecorderState
  }
}

/** mm:ss, or h:mm:ss once past an hour. */
export function formatElapsed(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const pad = (value: number) => String(value).padStart(2, '0')

  return hours > 0
    ? `${String(hours)}:${pad(minutes)}:${pad(seconds)}`
    : `${pad(minutes)}:${pad(seconds)}`
}
