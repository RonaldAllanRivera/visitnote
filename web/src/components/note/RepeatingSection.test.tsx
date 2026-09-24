import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { SectionSpec } from '@/lib/note'

import { RepeatingSection } from './RepeatingSection'

const SECTION: SectionSpec = {
  key: 'focus_entries',
  label: 'Focus entries',
  order: 2,
  description: 'One F-D-A-R entry per nursing focus charted this shift.',
  repeating: true,
  fields: [
    { key: 'focus', label: 'Focus', order: 1, description: '', repeating: false, fields: [] },
    { key: 'response', label: 'Response', order: 2, description: '', repeating: false, fields: [] },
  ],
}

const ENTRIES = [{ focus: 'Pain', response: 'Relieved to 3/10' }]

describe('RepeatingSection', () => {
  it('renders one card per stored entry, with a field per declared field', () => {
    render(<RepeatingSection section={SECTION} entries={ENTRIES} onChange={vi.fn()} />)

    expect(screen.getByDisplayValue('Pain')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Relieved to 3/10')).toBeInTheDocument()
  })

  it('adds an empty entry carrying every declared field', () => {
    // A nurse who charted three focuses when the model caught two has to be able to
    // add the third, or the repeating group is only half editable.
    const onChange = vi.fn()
    render(<RepeatingSection section={SECTION} entries={ENTRIES} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: /add focus entry/i }))

    expect(onChange).toHaveBeenCalledWith([...ENTRIES, { focus: '', response: '' }])
  })

  it('removes the entry the nurse asked to remove', () => {
    const onChange = vi.fn()
    const two = [...ENTRIES, { focus: 'Fever', response: 'Down to 37.2' }]
    render(<RepeatingSection section={SECTION} entries={two} onChange={onChange} />)

    const secondRemove = screen.getAllByRole('button', { name: /remove/i })[1]
    if (!secondRemove) throw new Error('expected a second remove button')
    fireEvent.click(secondRemove)

    expect(onChange).toHaveBeenCalledWith([ENTRIES[0]])
  })
})
