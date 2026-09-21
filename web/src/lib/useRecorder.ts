import { useCallback, useEffect, useReducer, useRef } from 'react'

import {
  initialRecorderState,
  MAX_DURATION_SECONDS,
  recorderReducer,
} from './recorderState'

/**
 * Binds the recorder state machine to the browser's MediaRecorder.
 *
 * This layer is deliberately thin. Every rule worth testing lives in the reducer,
 * because `MediaRecorder` does not exist in jsdom and a test that mocks it would be
 * asserting on the mock rather than on behaviour.
 *
 * Browser recording has a real limitation that the native client will not: closing
 * the tab ends the recording. A Wake Lock keeps the screen from sleeping, which
 * covers the common case of a phone left on a table mid-visit, but it cannot survive
 * the tab being closed. The UI says so rather than pretending otherwise.
 */

/** Ordered by preference; the first the browser supports wins. Safari only does mp4. */
const CANDIDATE_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
]

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined
  return CANDIDATE_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type))
}

export function useRecorder() {
  const [state, dispatch] = useReducer(recorderReducer, initialRecorderState)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const wakeLockRef = useRef<WakeLockSentinel | null>(null)
  const startedAtRef = useRef<number>(0)

  const releaseHardware = useCallback(() => {
    // Every track must be stopped explicitly. Leaving one live keeps the browser's
    // recording indicator lit, which looks — reasonably — like the app is still
    // listening after the visit ended.
    streamRef.current?.getTracks().forEach((track) => { track.stop() })
    streamRef.current = null
    void wakeLockRef.current?.release()
    wakeLockRef.current = null
  }, [])

  const start = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      })
      streamRef.current = stream

      const mimeType = pickMimeType()
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      chunksRef.current = []

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        dispatch({
          type: 'stopped',
          blob: new Blob(chunksRef.current, { type: recorder.mimeType }),
        })
        releaseHardware()
      }

      // A timeslice means chunks arrive continuously rather than only at stop, so a
      // crash mid-visit loses seconds instead of the whole recording.
      recorder.start(5000)
      recorderRef.current = recorder
      startedAtRef.current = Date.now()

      try {
        wakeLockRef.current = await navigator.wakeLock.request('screen')
      } catch {
        // Unsupported or refused. Recording still works; the screen may sleep.
      }

      dispatch({ type: 'started' })
    } catch (error) {
      releaseHardware()
      dispatch({
        type: 'failed',
        reason:
          error instanceof DOMException && error.name === 'NotAllowedError'
            ? 'Microphone permission was denied. Allow access and try again.'
            : 'Could not start recording on this device.',
      })
    }
  }, [releaseHardware])

  const stop = useCallback(() => {
    recorderRef.current?.stop()
    recorderRef.current = null
  }, [])

  const pause = useCallback(() => {
    recorderRef.current?.pause()
    dispatch({ type: 'paused' })
  }, [])

  const resume = useCallback(() => {
    recorderRef.current?.resume()
    // The elapsed baseline shifts so paused time is not counted as recorded time.
    startedAtRef.current = Date.now() - state.elapsedSeconds * 1000
    dispatch({ type: 'resumed' })
  }, [state.elapsedSeconds])

  // Elapsed time is derived from wall-clock rather than counted, because an interval
  // in a backgrounded tab is throttled and would under-report the real duration.
  useEffect(() => {
    if (state.phase !== 'recording') return
    const id = setInterval(() => {
      dispatch({
        type: 'tick',
        seconds: Math.floor((Date.now() - startedAtRef.current) / 1000),
      })
    }, 1000)
    return () => { clearInterval(id) }
  }, [state.phase])

  useEffect(() => {
    if (state.atMaxDuration) stop()
  }, [state.atMaxDuration, stop])

  useEffect(() => releaseHardware, [releaseHardware])

  return {
    ...state,
    start: () => { void start() },
    stop,
    pause,
    resume,
    reset: () => { dispatch({ type: 'reset' }) },
    maxDurationSeconds: MAX_DURATION_SECONDS,
  }
}
