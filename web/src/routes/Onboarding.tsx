import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { detailMessage } from '@/lib/apiError'
import type { UserProfile } from '@/lib/profile'
import { queryKeys } from '@/lib/queryClient'
import { otherJurisdiction, REGIMES } from '@/lib/regimes'

type RoleTitle = components['schemas']['RoleTitle']

const ROLES: readonly (readonly [RoleTitle, string])[] = [
  ['rn', 'Registered Nurse'],
  ['lpn', 'Licensed Practical Nurse'],
  ['cna', 'Certified Nursing Assistant'],
  ['hha', 'Home Health Aide'],
  ['caregiver', 'Caregiver'],
  ['other', 'Something else'],
]

/**
 * The question that decides which rules apply to everything after it.
 *
 * Two steps on purpose. The first asks for a timezone, because that is a question a
 * nurse can answer; the second shows what the server concluded from it and offers
 * the correction. The zone-to-jurisdiction mapping is deliberately *not* duplicated
 * here -- it is a legal rule with real consequences, it lives in
 * `app/core/jurisdiction.py`, and a second copy in TypeScript would be a second
 * place for it to be wrong.
 */
export function Onboarding() {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()

  const destination = (location.state as { from?: string } | null)?.from ?? '/new'

  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState<RoleTitle>('rn')
  const [timezone, setTimezone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone)
  const [saved, setSaved] = useState<UserProfile | null>(null)

  const save = useMutation({
    mutationFn: async (body: components['schemas']['OnboardingRequest']) => {
      const { data, error } = await api.PATCH('/api/v1/auth/me', { body })
      if (error ?? !data) throw new Error(detailMessage(error, 'Could not save your details'))
      return data
    },
    onSuccess: (profile) => {
      setSaved(profile)
      // Written straight into the cache rather than invalidated. The guard reads
      // this query to decide whether to let the user past; a refetch would leave it
      // briefly holding the un-onboarded profile and bounce the user back here.
      queryClient.setQueryData(queryKeys.profile(), profile)
    },
  })

  if (saved !== null) {
    const regime = REGIMES[saved.jurisdiction]
    const other = otherJurisdiction(saved.jurisdiction)

    return (
      <section className="max-w-lg space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">You work in {regime.name}</h1>

        <div className="space-y-3 rounded-md border border-line p-4 text-sm">
          <p>{regime.capture}</p>
          <p className="text-muted">{regime.record}</p>
        </div>

        <div className="space-y-2">
          <p className="text-xs text-muted">
            We worked this out from your time zone. If that is not where you practise,
            change it here.
          </p>
          <button
            type="button"
            onClick={() => { save.mutate({ jurisdiction: other }) }}
            disabled={save.isPending}
            className="rounded-md border border-line px-3 py-2 text-sm disabled:opacity-50"
          >
            I work in {REGIMES[other].name} instead
          </button>
        </div>

        {save.isError && <p className="text-sm text-critical">{save.error.message}</p>}

        <button
          type="button"
          onClick={() => { void navigate(destination, { replace: true }) }}
          className="rounded-md bg-accent px-4 py-2 text-surface"
        >
          Finish setup
        </button>
      </section>
    )
  }

  return (
    <section className="max-w-lg space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Set up your account</h1>
      <p className="text-sm text-muted">
        Where you practise decides which note format you get and how you are allowed to
        record. We ask once.
      </p>

      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault()
          // Only what was answered. Every field on the server is apply-if-present, so
          // an omitted name leaves the existing one alone -- an empty string would
          // overwrite it with nothing.
          save.mutate({
            role_title: role,
            timezone,
            ...(fullName.trim() === '' ? {} : { full_name: fullName.trim() }),
          })
        }}
      >
        <div className="space-y-2">
          <label htmlFor="full-name" className="block text-sm font-medium">
            Your name <span className="font-normal text-muted">(optional)</span>
          </label>
          <input
            id="full-name"
            value={fullName}
            onChange={(event) => { setFullName(event.target.value) }}
            className="w-full rounded-md border border-line bg-transparent px-3 py-2"
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="role" className="block text-sm font-medium">
            What you do
          </label>
          <select
            id="role"
            value={role}
            onChange={(event) => { setRole(event.target.value as RoleTitle) }}
            className="w-full rounded-md border border-line bg-transparent px-3 py-2"
          >
            {ROLES.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>

        <div className="space-y-2">
          <label htmlFor="timezone" className="block text-sm font-medium">
            Time zone
          </label>
          <input
            id="timezone"
            value={timezone}
            onChange={(event) => { setTimezone(event.target.value) }}
            className="w-full rounded-md border border-line bg-transparent px-3 py-2 font-mono text-sm"
          />
          <p className="text-xs text-muted">
            Taken from this device. Your notes are timestamped in this zone, so a night
            shift crossing midnight is dated the way you worked it.
          </p>
        </div>

        {save.isError && <p className="text-sm text-critical">{save.error.message}</p>}

        <button
          type="submit"
          disabled={save.isPending}
          className="rounded-md bg-accent px-4 py-2 text-surface disabled:opacity-50"
        >
          Continue
        </button>
      </form>
    </section>
  )
}
