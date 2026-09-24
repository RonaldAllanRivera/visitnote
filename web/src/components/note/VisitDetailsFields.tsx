/**
 * The note's header: who, when, and the exact times.
 *
 * Editable, because the missing-times flags are decided from these fields rather
 * than by parsing prose -- a flag pointing at a read-only field is a flag that
 * cannot be cleared.
 */
const LABELS: Record<string, string> = {
  client_label: 'Care recipient',
  visit_date: 'Date',
  start_time: 'Start time',
  end_time: 'End time',
}

export function VisitDetailsFields({
  details,
  onChange,
}: {
  details: Record<string, unknown>
  onChange: (key: string, value: string) => void
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {Object.keys(LABELS).map((key) => {
        const id = `visit-detail-${key}`
        const value = details[key]
        return (
          <div key={key} className="space-y-1">
            <label htmlFor={id} className="block text-xs font-medium">
              {LABELS[key]}
            </label>
            <input
              id={id}
              value={typeof value === 'string' ? value : ''}
              onChange={(event) => { onChange(key, event.target.value) }}
              className="w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm"
            />
          </div>
        )
      })}
    </div>
  )
}
