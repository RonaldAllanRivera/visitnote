import { useQuery } from '@tanstack/react-query'
import { useRef } from 'react'
import { Link, useParams } from 'react-router'

import { api } from '@/api/client'
import { describeStage, isTerminal, pollIntervalMs, stageProgress } from '@/lib/processingStatus'
import { queryKeys } from '@/lib/queryClient'

/**
 * What the caregiver watches while their note is written.
 *
 * The screen reports the pipeline *stage*, not just "processing". A shift recording
 * can take minutes to transcribe, and an indicator that says nothing for that long
 * is indistinguishable from one that has hung -- which is how someone ends up
 * re-recording a visit that was working perfectly well.
 */
export function Processing() {
  const { visitId = '' } = useParams<{ visitId: string }>()

  // Wall-clock since the screen opened, which is what the poll schedule backs off
  // against. A ref rather than state: it must not itself cause a render.
  const openedAt = useRef(Date.now())

  const { data, isPending, isError, error } = useQuery({
    queryKey: queryKeys.visitStatus(visitId),
    queryFn: async () => {
      const { data, error, response } = await api.GET('/api/v1/visits/{visit_id}/status', {
        params: { path: { visit_id: visitId } },
      })
      if (error ?? !response.ok) {
        throw new Error(`status check failed with status ${String(response.status)}`)
      }
      return data
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status
      // Nothing to decide on before the first response; poll at the fast rate
      // rather than stopping.
      if (status === undefined) return 2_000
      return pollIntervalMs(status, Date.now() - openedAt.current)
    },
  })

  if (isPending) return <p className="text-muted">Checking…</p>
  if (isError) {
    return (
      <p role="alert" className="text-critical">
        Could not check this visit. {error.message}
      </p>
    )
  }

  const stage = data.stage ?? null
  const finished = isTerminal(data.status)
  const failed = data.status === 'failed'
  const label = describeStage(data.status, stage)
  const progress = failed ? undefined : finished ? 1 : stageProgress(stage)

  return (
    <section className="space-y-5">
      <h2 className="text-lg font-medium">Writing your note</h2>

      <div className="space-y-2">
        <p role="status" className={failed ? 'text-critical' : undefined}>
          {label}
        </p>

        {/* A real <progress> rather than a styled div, so a screen reader announces
            the value -- and so the failed case can be left valueless instead of
            showing a bar that reads as "still working on it". */}
        <progress
          className="w-full max-w-md"
          value={progress}
          max={1}
          aria-label="Processing progress"
        />
      </div>

      {failed && (
        <div className="space-y-2 text-sm">
          <p className="text-muted">{data.error ?? 'No further detail was recorded.'}</p>
          {/* Deliberately not a retry button. A caregiver cannot fix a corrupt
              recording by asking again, and a visit that failed for a transient
              reason has already been retried by the worker three times. */}
          <p>This visit is recorded as failed. Contact support if the recording was good.</p>
        </div>
      )}

      {finished && !failed && (
        <p className="text-sm">
          <Link to="/new" className="underline">
            Record another visit
          </Link>
        </p>
      )}

      {!finished && data.attempts > 1 && (
        <p className="text-sm text-muted">
          Attempt {data.attempts}. An earlier attempt did not complete, so it is being
          tried again.
        </p>
      )}
    </section>
  )
}
