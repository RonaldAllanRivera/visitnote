import { Link } from 'react-router'

import { useNotes, type NoteListItem } from '@/lib/note'

/** Severities worth a badge, most serious first. */
const SEVERITIES = ['critical', 'warning'] as const

function summary(item: NoteListItem): string {
  const parts = SEVERITIES.flatMap((severity) => {
    const count = item.flag_counts[severity] ?? 0
    return count > 0 ? [`${String(count)} ${severity}`] : []
  })
  return parts.length === 0 ? 'No findings' : parts.join(' · ')
}

/**
 * A way back to your own work.
 *
 * Deliberately not the phase 7 roster: no agency scope, no review queue, no charts.
 * It exists because a nurse closes the tab and the note they just recorded should
 * not be reachable only by a URL they did not keep.
 */
export function Notes() {
  const { data: notes, isPending } = useNotes()

  if (isPending) return <p className="text-sm text-muted">Loading your notes…</p>

  if (notes === undefined) {
    return <p className="text-sm text-critical">Could not load your notes.</p>
  }

  if (notes.length === 0) {
    return (
      <section className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">Notes</h1>
        <p className="text-sm text-muted">
          Nothing here yet. <Link to="/new" className="underline underline-offset-4">
            Record your first note
          </Link>.
        </p>
      </section>
    )
  }

  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Notes</h1>
      <ul className="divide-y divide-line">
        {notes.map((item) => (
          <li key={item.id}>
            <Link to={`/notes/${item.id}`} className="flex items-baseline justify-between gap-4 py-3">
              <span>
                <span className="block text-sm">{item.client_label ?? 'Unlabelled'}</span>
                <span className="block text-xs text-muted">
                  {item.visit_date ?? '—'} · {item.format}
                  {item.edited ? ' · edited' : ''}
                  {item.signed_at !== null ? ' · signed' : ''}
                </span>
              </span>
              <span className="text-xs text-muted">{summary(item)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}
