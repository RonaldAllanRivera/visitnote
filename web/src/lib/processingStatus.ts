/**
 * The polling policy for a visit being processed.
 *
 * Kept out of the component and free of React so it can be tested directly. Two of
 * the decisions here are the sort that only show up in production: when to *stop*
 * polling, and how fast to poll while waiting.
 */

/** Statuses after which nothing further will happen on its own. */
const TERMINAL = new Set(['ready', 'signed', 'failed'])

/**
 * Poll fast at first, then back off.
 *
 * A short recap is often transcribed and written within a few seconds, so an
 * immediate two-second poll makes the common case feel instant. A 45-minute shift
 * recording is not going to finish sooner because we asked more often -- and the
 * client doing the asking is a phone on mobile data in someone's pocket.
 */
const SCHEDULE: readonly { untilMs: number; intervalMs: number }[] = [
  { untilMs: 30_000, intervalMs: 2_000 },
  { untilMs: 90_000, intervalMs: 5_000 },
]

/**
 * The slowest we will ever poll. A finished note has to appear promptly: ten
 * seconds is about the longest someone will stare at a spinner without deciding
 * the product is broken.
 */
const MAX_INTERVAL_MS = 10_000

/** Written for the person waiting, not for whoever named the pipeline stages. */
const STAGE_LABELS: Readonly<Record<string, string>> = {
  queued: 'Waiting for a free worker',
  download: 'Fetching the recording',
  normalize: 'Preparing the audio',
  transcribe: 'Transcribing the recording',
  generate: 'Writing the note',
  persist: 'Saving the note',
  complete: 'Note ready',
}

/**
 * Where each stage sits in the run. Approximate and deliberately uneven:
 * transcription is by far the longest step, so spacing these evenly would show a
 * bar that races to the middle and then appears to hang.
 */
const STAGE_PROGRESS: Readonly<Record<string, number>> = {
  queued: 0,
  download: 0.1,
  normalize: 0.25,
  transcribe: 0.55,
  generate: 0.85,
  persist: 0.95,
  complete: 1,
}

export function isTerminal(status: string): boolean {
  return TERMINAL.has(status)
}

/**
 * How long to wait before asking again, or `false` to stop.
 *
 * `false` rather than a large number: TanStack Query treats it as "do not refetch",
 * which is the difference between a finished screen and a tab quietly polling the
 * API until the phone is closed.
 */
export function pollIntervalMs(status: string, elapsedMs: number): number | false {
  if (isTerminal(status)) return false

  for (const step of SCHEDULE) {
    if (elapsedMs < step.untilMs) return step.intervalMs
  }
  return MAX_INTERVAL_MS
}

export function describeStage(status: string, stage: string | null): string {
  if (status === 'failed') return 'Processing failed'
  if (status === 'ready' || status === 'signed') return 'Note ready'
  // Enqueued but not yet picked up: there is no stage to report, and "processing"
  // would overstate what is happening.
  if (status === 'uploaded') return 'Waiting for a free worker'

  const label = stage === null ? undefined : STAGE_LABELS[stage]
  // A stage added to the pipeline later must not render as blank or "undefined".
  return label ?? 'Processing'
}

export function stageProgress(stage: string | null): number {
  const progress = stage === null ? undefined : STAGE_PROGRESS[stage]
  return progress ?? 0
}
