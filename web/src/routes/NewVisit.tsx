import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { api } from '@/api/client'
import { formatElapsed } from '@/lib/recorderState'
import { uploadAudio } from '@/lib/uploadAudio'
import { useRecorder } from '@/lib/useRecorder'

type CaptureMode = 'live_audio' | 'spoken_recap'

/**
 * Visit creation's 422s (an unsupported note format, the RA 4200 capture-mode
 * refusal) carry a plain-string `detail`, but the generated type says `detail` is a
 * list of validation errors -- FastAPI's OpenAPI export always shapes 422 that way,
 * regardless of what a route's own HTTPException actually sends. Read it as unknown
 * rather than trust the generated shape, so the reason reaches the user instead of
 * being thrown away.
 */
function detailMessage(error: unknown, fallback: string): string {
  const detail = (error as { detail?: unknown } | null | undefined)?.detail
  return typeof detail === 'string' ? detail : fallback
}

/**
 * Capture: choose who and how, acknowledge consent, record, upload.
 *
 * The consent gate is presented as a step rather than a checkbox in a corner because
 * it is the clearest legal exposure in the product. The server refuses a live
 * recording without it regardless of what this screen does -- the UI states the
 * obligation, the API enforces it.
 */
export function NewVisit() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const recorder = useRecorder()

  const [clientId, setClientId] = useState('')
  const [mode, setMode] = useState<CaptureMode>('spoken_recap')
  const [consented, setConsented] = useState(false)
  const [progress, setProgress] = useState(0)

  const clients = useQuery({
    queryKey: ['clients'],
    queryFn: async () => {
      const { data, response } = await api.GET('/api/v1/clients')
      // Checked on the response rather than the typed `error` branch: an
      // authenticated route's 401 comes from a dependency and is not declared in
      // the schema, so the generated error type is `never`.
      if (!response.ok || !data) throw new Error('Could not load care recipients')
      return data
    },
  })

  const needsConsent = mode === 'live_audio'
  const canRecord = clientId !== '' && (!needsConsent || consented)

  const submit = useMutation({
    mutationFn: async (blob: Blob) => {
      // The key is generated per attempt, so a retry after a dropped connection
      // resolves to the visit that already exists instead of creating a second one
      // and consuming another unit of the monthly quota.
      const idempotencyKey = crypto.randomUUID()

      const visit = await api.POST('/api/v1/visits', {
        body: {
          client_id: clientId,
          capture_mode: mode,
          idempotency_key: idempotencyKey,
          consent_acknowledged: consented,
        },
      })
      if (visit.error ?? !visit.data) {
        throw new Error(detailMessage(visit.error, 'Could not open the visit'))
      }
      const visitId = visit.data.id

      const ticket = await api.POST('/api/v1/visits/{visit_id}/upload', {
        params: { path: { visit_id: visitId } },
        body: { content_type: blob.type || 'audio/webm', size_bytes: blob.size },
      })
      if (ticket.error ?? !ticket.data) throw new Error('Could not prepare the upload')

      const { parts } = await uploadAudio({
        blob,
        ticket: ticket.data,
        onProgress: setProgress,
        putPart: async (url, body) => {
          // Raw fetch is correct here and only here: this is a presigned URL for the
          // object store, not an endpoint of our API, so there are no generated types
          // to use and no access token to attach. Sending our bearer token to a third
          // party would be the actual mistake.
          // eslint-disable-next-line no-restricted-globals
          const response = await fetch(url, { method: 'PUT', body })
          if (!response.ok) {
            throw Object.assign(new Error('part upload failed'), { status: response.status })
          }
          // S3 returns the part's ETag in a header; completion cannot assemble the
          // object without it.
          return response.headers.get('ETag') ?? ''
        },
        reissue: async (partNumbers) => {
          const fresh = await api.POST('/api/v1/visits/{visit_id}/upload/parts', {
            params: { path: { visit_id: visitId } },
            body: { part_numbers: partNumbers },
          })
          if (fresh.error ?? !fresh.data) throw new Error('Could not refresh the upload')
          return fresh.data.parts
        },
      })

      const completed = await api.POST('/api/v1/visits/{visit_id}/upload/complete', {
        params: { path: { visit_id: visitId } },
        body: { parts },
      })
      if (completed.error ?? !completed.data) throw new Error('Could not finish the upload')
      return completed.data
    },
    onSuccess: (visit) => {
      void queryClient.invalidateQueries({ queryKey: ['visits'] })
      recorder.reset()
      setProgress(0)
      // Completing the upload enqueues the pipeline, so the next thing the user
      // needs is the screen that says what it is doing -- not a success message on
      // a form they have finished with.
      void navigate(`/visits/${visit.id}/processing`)
    },
  })

  return (
    <section className="space-y-8">
      <h1 className="text-2xl font-semibold tracking-tight">New note</h1>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Who is this visit for?</legend>
        <select
          value={clientId}
          onChange={(event) => { setClientId(event.target.value) }}
          className="w-full max-w-sm rounded-md border border-line bg-transparent px-3 py-2"
        >
          <option value="">Select…</option>
          {clients.data?.map((record) => (
            <option key={record.id} value={record.id}>{record.label}</option>
          ))}
        </select>
        <p className="text-xs text-muted">
          Use an initial or a nickname. Never a full name.
        </p>
      </fieldset>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">How are you capturing this?</legend>
        {(
          [
            ['spoken_recap', 'I will describe the visit afterwards', 'Records only you.'],
            ['live_audio', 'Record the visit itself', 'Records the client. Consent required.'],
          ] as const
        ).map(([value, label, hint]) => (
          <label key={value} className="flex gap-3 rounded-md border border-line p-3">
            <input
              type="radio"
              name="capture-mode"
              value={value}
              checked={mode === value}
              onChange={() => {
                setMode(value)
                setConsented(false)
              }}
              className="mt-1"
            />
            <span>
              <span className="block text-sm">{label}</span>
              <span className="block text-xs text-muted">{hint}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {needsConsent && (
        <div className="space-y-2 rounded-md border border-critical/40 p-4">
          <p className="text-sm">
            Before recording, tell the client you are recording this visit for your
            documentation, and confirm they agree.
          </p>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={consented}
              onChange={(event) => { setConsented(event.target.checked) }}
              className="mt-1"
            />
            I have told the client and they agreed to be recorded.
          </label>
        </div>
      )}

      <div className="space-y-3 rounded-md border border-line p-4">
        <div className="flex items-baseline justify-between">
          <span className="font-mono text-2xl tabular-nums">
            {formatElapsed(recorder.elapsedSeconds)}
          </span>
          <span className="text-xs text-muted">
            {recorder.phase === 'recording' && 'Recording — keep this tab open'}
            {recorder.phase === 'paused' && 'Paused'}
            {recorder.phase === 'stopped' && 'Ready to upload'}
          </span>
        </div>

        {recorder.error !== null && (
          <p role="alert" className="text-sm text-critical">{recorder.error}</p>
        )}
        {recorder.atMaxDuration && (
          <p role="status" className="text-sm text-muted">
            Reached the 90 minute limit and stopped automatically.
          </p>
        )}

        <div className="flex gap-2">
          {recorder.phase === 'idle' || recorder.phase === 'error' ? (
            <button
              type="button"
              onClick={recorder.start}
              disabled={!canRecord}
              className="rounded-md bg-accent px-4 py-2 text-surface disabled:opacity-50"
            >
              Start recording
            </button>
          ) : null}

          {recorder.phase === 'recording' && (
            <>
              <button type="button" onClick={recorder.pause} className="rounded-md border border-line px-4 py-2">
                Pause
              </button>
              <button type="button" onClick={recorder.stop} className="rounded-md bg-accent px-4 py-2 text-surface">
                Stop
              </button>
            </>
          )}

          {recorder.phase === 'paused' && (
            <>
              <button type="button" onClick={recorder.resume} className="rounded-md border border-line px-4 py-2">
                Resume
              </button>
              <button type="button" onClick={recorder.stop} className="rounded-md bg-accent px-4 py-2 text-surface">
                Stop
              </button>
            </>
          )}

          {recorder.phase === 'stopped' && recorder.blob !== null && (
            <button
              type="button"
              onClick={() => { submit.mutate(recorder.blob as Blob) }}
              disabled={submit.isPending}
              className="rounded-md bg-accent px-4 py-2 text-surface disabled:opacity-60"
            >
              {submit.isPending ? `Uploading ${String(Math.round(progress * 100))}%` : 'Upload'}
            </button>
          )}
        </div>

        {submit.isError && (
          <p role="alert" className="text-sm text-critical">{submit.error.message}</p>
        )}
        {submit.isSuccess && (
          <p role="status" className="text-sm">Uploaded. Taking you to your note…</p>
        )}
      </div>
    </section>
  )
}
