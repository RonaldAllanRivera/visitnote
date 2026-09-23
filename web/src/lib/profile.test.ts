import { describe, expect, it } from 'vitest'

import { profileFixture } from '@/test/fixtures'

import { needsOnboarding } from './profile'

describe('needsOnboarding', () => {
  it('is true for a freshly registered account', () => {
    // Registration sets a default format but never a role: `default_note_format`
    // being populated is therefore not evidence that anyone was asked anything.
    expect(needsOnboarding(profileFixture({ role_title: null }))).toBe(true)
  })

  it('is false once a role has been chosen', () => {
    expect(needsOnboarding(profileFixture({ role_title: 'rn' }))).toBe(false)
  })

  it('is true while the profile is still unknown', () => {
    // An in-flight or failed profile fetch is not permission to skip the gate. The
    // caller decides whether to render a spinner or the form; what it must not do is
    // treat "no answer yet" as "already onboarded".
    expect(needsOnboarding(undefined)).toBe(true)
  })
})
