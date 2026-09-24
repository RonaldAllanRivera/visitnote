import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { FlagsPanel } from './FlagsPanel'

const FLAGS = [
  { code: 'MISSING_VITALS_TIME', message: 'Vitals with no time.', severity: 'warning' },
  { code: 'MISSING_RESPONSE', message: 'An action with no response.', severity: 'critical' },
] as const

describe('FlagsPanel', () => {
  it('puts critical findings above warnings', () => {
    // A nurse working down the list should meet the thing that matters first.
    render(<FlagsPanel flags={[...FLAGS]} />)

    const codes = screen.getAllByTestId('flag-code').map((node) => node.textContent)
    expect(codes).toEqual(['MISSING_RESPONSE', 'MISSING_VITALS_TIME'])
  })

  it('says so plainly when the model found nothing', () => {
    render(<FlagsPanel flags={[]} />)

    expect(screen.getByText(/no findings/i)).toBeInTheDocument()
  })
})
