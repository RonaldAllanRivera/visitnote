import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '@/api/client'
import { detailMessage } from '@/lib/apiError'
import { useProfile } from '@/lib/profile'
import { queryKeys } from '@/lib/queryClient'
import { type Jurisdiction, otherJurisdiction, REGIMES } from '@/lib/regimes'

/**
 * Where you practise, after onboarding has already asked once.
 *
 * Onboarding is a gate, and a gate you pass through once is not a place to correct a
 * mistake. This screen exists because the answer genuinely changes: a nurse works in
 * both regimes, a tester needs to exercise both, and a device timezone can be wrong
 * in a way nobody notices until the wrong note format comes back.
 *
 * Safe by design rather than by care here: `visits` copy the jurisdiction they were
 * captured under, so switching changes which template the *next* note resolves
 * against and leaves every note already written exactly as it was.
 */
export function Settings() {
  const queryClient = useQueryClient()
  const { data: profile } = useProfile()

  const switchTo = useMutation({
    mutationFn: async (jurisdiction: Jurisdiction) => {
      // Jurisdiction and nothing else. The server derives the note format from it
      // and reconciles a format the switch would strand -- a PH RN defaults to fdar,
      // and there is no (US, fdar) template. A client that also sent a format would
      // be overriding a decision it is not equipped to make.
      const { data, error } = await api.PATCH('/api/v1/auth/me', { body: { jurisdiction } })
      if (error ?? !data) {
        throw new Error(detailMessage(error, 'Could not change where you practise'))
      }
      return data
    },
    onSuccess: (updated) => {
      // Written straight into the cache rather than invalidated: the response *is*
      // the server's updated profile, so a refetch would ask a question already
      // answered and leave the old regime on screen until it came back.
      queryClient.setQueryData(queryKeys.profile(), updated)
    },
  })

  if (profile === undefined) {
    return <p className="text-sm text-muted">Loading your settings…</p>
  }

  const regime = REGIMES[profile.jurisdiction]
  const other = otherJurisdiction(profile.jurisdiction)

  return (
    <section className="max-w-lg space-y-8">
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>

      <div className="space-y-4">
        <h2 className="text-sm font-medium">You practise in {regime.name}</h2>

        <div className="space-y-3 rounded-md border border-line p-4 text-sm">
          <p>{regime.capture}</p>
          <p className="text-muted">{regime.record}</p>
        </div>

        <p className="text-xs text-muted">
          Notes you have already written keep the rules they were written under.
          Changing this affects your next note, not your past ones.
        </p>

        <button
          type="button"
          onClick={() => { switchTo.mutate(other) }}
          disabled={switchTo.isPending}
          className="rounded-md border border-line px-3 py-2 text-sm disabled:opacity-50"
        >
          I practise in {REGIMES[other].name} instead
        </button>

        {switchTo.isError && <p className="text-sm text-critical">{switchTo.error.message}</p>}
      </div>
    </section>
  )
}
