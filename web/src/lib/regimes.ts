import type { components } from '@/api/schema'

export type Jurisdiction = components['schemas']['Jurisdiction']

export interface Regime {
  /** Reads inside a sentence: "You practise in {name}." */
  name: string
  /** What this regime permits when capturing. */
  capture: string
  /** Which document is the legal record, and what that asks of the user. */
  record: string
  /** The standing disclaimer shown on every screen. */
  disclaimer: string
}

/**
 * What each regulatory regime means for the person using the product.
 *
 * One definition, read by onboarding, by settings, and by the app shell's footer.
 * Three copies of a legal disclaimer is three chances for one of them to be edited
 * and the others left behind.
 *
 * The disclaimers are not two phrasings of one idea. In US home health the note *is*
 * the record the agency keeps and signs. On a Philippine hospital ward the legal
 * record is the hospital chart and this product produces a draft the nurse
 * transcribes into it. Showing a PH nurse the US wording would misstate which
 * document carries legal weight.
 */
export const REGIMES: Record<Jurisdiction, Regime> = {
  US: {
    name: 'the United States',
    capture:
      'You can record a visit once the client has agreed to it, or dictate a recap afterwards.',
    record: 'Your notes are the record your agency keeps. Review every draft before you sign it.',
    disclaimer:
      'Drafts must be reviewed by the responsible caregiver or clinician before use. Not medical advice or a medical device.',
  },
  PH: {
    name: 'the Philippines',
    capture:
      'Recording a ward conversation is not available: RA 4200 requires the consent of every party, which a ward cannot give. You will dictate a recap after your shift instead.',
    record:
      "The patient's chart stays the legal record. Review every entry before you transcribe it.",
    disclaimer:
      'This is a drafting aid. The patient’s chart remains the legal record. Review every entry before transcribing it.',
  },
}

/**
 * The regime to state when nobody is signed in.
 *
 * The landing page renders the shell too, and a public page must say something. US
 * is the safe default for the same reason `jurisdiction_for_timezone` defaults to it
 * server-side: it is the permissive regime, so defaulting to it never tells a PH
 * nurse they may do something RA 4200 forbids -- PH is only ever reached by a
 * signed-in profile that says so.
 */
export const DEFAULT_REGIME: Jurisdiction = 'US'

export function regimeFor(jurisdiction: Jurisdiction | undefined): Regime {
  return REGIMES[jurisdiction ?? DEFAULT_REGIME]
}

/** The regime that is not this one. With two, the switch target is just "the other". */
export function otherJurisdiction(jurisdiction: Jurisdiction): Jurisdiction {
  return jurisdiction === 'PH' ? 'US' : 'PH'
}
