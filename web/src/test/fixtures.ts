import type { components } from '@/api/schema'
import type { UserProfile } from '@/lib/profile'

type Jurisdiction = components['schemas']['Jurisdiction']

/**
 * The capabilities the API really publishes for each regime.
 *
 * Copied from the server's own values rather than invented, including the RA 4200
 * wording verbatim -- a fixture that paraphrases the message would let a test pass
 * while the screen showed text the server never sent.
 */
const CAPABILITIES: Record<Jurisdiction, UserProfile['capabilities']> = {
  US: {
    allowed_capture_modes: ['live_audio', 'spoken_recap'],
    capture_restriction: null,
    available_formats: ['shift_note', 'soapie'],
  },
  PH: {
    allowed_capture_modes: ['spoken_recap'],
    capture_restriction: {
      code: 'RA_4200',
      mode: 'live_audio',
      message:
        'RA 4200 (Anti-Wiretapping Act) requires the consent of all parties to a private communication. Record a spoken recap instead.',
    },
    available_formats: ['fdar', 'soapie'],
  },
}

/**
 * A profile shaped like the API's, with capabilities that agree with its
 * jurisdiction. One definition, so a contract change breaks every test that depends
 * on it at once rather than a handful at a time.
 */
export function profileFixture(overrides: Partial<UserProfile> = {}): UserProfile {
  const jurisdiction = overrides.jurisdiction ?? 'US'
  return {
    id: '11111111-1111-1111-1111-111111111111',
    email: 'nurse@example.test',
    full_name: null,
    role_title: 'rn',
    default_note_format: jurisdiction === 'PH' ? 'fdar' : 'soapie',
    timezone: jurisdiction === 'PH' ? 'Asia/Manila' : 'America/New_York',
    jurisdiction,
    is_staff: false,
    capabilities: CAPABILITIES[jurisdiction],
    ...overrides,
  }
}
