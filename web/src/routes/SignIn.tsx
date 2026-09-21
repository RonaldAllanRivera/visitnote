import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { api } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

type Mode = 'sign-in' | 'register'

export function SignIn() {
  const [mode, setMode] = useState<Mode>('sign-in')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const navigate = useNavigate()
  const location = useLocation()
  const setSession = useAuthStore((state) => state.setSession)

  const destination = (location.state as { from?: string } | null)?.from ?? '/status'

  const submit = useMutation({
    mutationFn: async () => {
      // Branched rather than computing the path, because a dynamic path erases the
      // per-endpoint response type -- the generated client can only guarantee the
      // shape of a call it can see the literal path for.
      const body = { email, password }
      const { data, error, response } =
        mode === 'sign-in'
          ? await api.POST('/api/v1/auth/login', { body })
          : await api.POST('/api/v1/auth/register', { body })

      if (error ?? !response.ok) {
        // The server deliberately returns one message for every credential failure,
        // so there is nothing more specific to show. 429 is the exception: the user
        // genuinely needs to know to wait.
        throw new Error(
          response.status === 429
            ? 'Too many attempts. Please wait a few minutes and try again.'
            : mode === 'register'
              ? 'Could not create that account. It may already exist.'
              : 'Invalid email or password.',
        )
      }
      return data
    },
    onSuccess: (data) => {
      setSession({ accessToken: data.access_token, refreshToken: data.refresh_token })
      void navigate(destination, { replace: true })
    },
  })

  return (
    <section className="mx-auto max-w-sm space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">
        {mode === 'sign-in' ? 'Sign in' : 'Create an account'}
      </h1>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          submit.mutate()
        }}
        className="space-y-4"
        noValidate
      >
        <div className="space-y-1">
          <label htmlFor="email" className="block text-sm text-muted">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => { setEmail(event.target.value) }}
            className="w-full rounded-md border border-line bg-transparent px-3 py-2"
          />
        </div>

        <div className="space-y-1">
          <label htmlFor="password" className="block text-sm text-muted">Password</label>
          <input
            id="password"
            type="password"
            // Tells a password manager to offer a generated password on signup and
            // the saved one on sign-in. The wrong value here trains people to pick
            // weak passwords.
            autoComplete={mode === 'sign-in' ? 'current-password' : 'new-password'}
            required
            minLength={mode === 'register' ? 12 : undefined}
            value={password}
            onChange={(event) => { setPassword(event.target.value) }}
            className="w-full rounded-md border border-line bg-transparent px-3 py-2"
          />
          {mode === 'register' && (
            <p className="text-xs text-muted">At least 12 characters. Length beats complexity.</p>
          )}
        </div>

        {submit.isError && (
          <p role="alert" className="text-sm text-critical">
            {submit.error.message}
          </p>
        )}

        <button
          type="submit"
          disabled={submit.isPending}
          className="w-full rounded-md bg-accent px-3 py-2 text-surface disabled:opacity-60"
        >
          {submit.isPending ? 'Working…' : mode === 'sign-in' ? 'Sign in' : 'Create account'}
        </button>
      </form>

      <button
        type="button"
        onClick={() => {
          setMode(mode === 'sign-in' ? 'register' : 'sign-in')
          submit.reset()
        }}
        className="text-sm text-muted underline underline-offset-4"
      >
        {mode === 'sign-in' ? 'Need an account?' : 'Already have an account?'}
      </button>
    </section>
  )
}
