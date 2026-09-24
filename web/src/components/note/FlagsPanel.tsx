import type { NoteFlag } from '@/lib/note'

/**
 * Ordered by what a reviewer should deal with first, not by the order the model
 * emitted them. Severity comes from the template rather than the model, so this
 * ordering is a property of the note format and not of a generation.
 */
const SEVERITY_ORDER: Record<NoteFlag['severity'], number> = {
  critical: 0,
  warning: 1,
  info: 2,
}

const SEVERITY_STYLE: Record<NoteFlag['severity'], string> = {
  critical: 'border-critical/50',
  warning: 'border-line',
  info: 'border-line',
}

/**
 * What the model found, as a checklist.
 *
 * Flags do not change when a section is edited. They record what was true of the
 * generated note; re-evaluating them would mean writing deterministic checkers that
 * phase 5b's eval suite also needs, and a checker that gets a rule wrong silently
 * clears a real finding on a legal record.
 */
export function FlagsPanel({ flags }: { flags: NoteFlag[] }) {
  if (flags.length === 0) {
    return <p className="text-sm text-muted">No findings. Read it through anyway.</p>
  }

  const ordered = [...flags].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
  )

  return (
    <ul className="space-y-2">
      {ordered.map((flag) => (
        <li
          key={`${flag.severity}-${flag.code}-${flag.message}`}
          className={`rounded-md border p-3 ${SEVERITY_STYLE[flag.severity]}`}
        >
          <span data-testid="flag-code" className="block font-mono text-xs text-muted">
            {flag.code}
          </span>
          <span className="block text-sm">{flag.message}</span>
        </li>
      ))}
    </ul>
  )
}
