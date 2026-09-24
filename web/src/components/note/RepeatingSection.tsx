import { normalizeFieldValue, type SectionSpec } from '@/lib/note'

type Entry = Record<string, string | null>

/**
 * A section the format repeats -- FDAR's focus entries, and nothing else in any
 * current template.
 *
 * Generic over the schema rather than written for FDAR: a section is repeating
 * because its template row says `repeating: true`, and a future format that repeats
 * something else needs no code here. An added entry carries every declared field as
 * an empty string rather than omitting them, because the server rejects an entry
 * whose keys do not match the schema exactly -- a missing key and a field the author
 * left blank are different facts.
 */
export function RepeatingSection({
  section,
  entries,
  onChange,
}: {
  section: SectionSpec
  entries: Entry[]
  onChange: (next: Entry[]) => void
}) {
  const blank = (): Entry =>
    Object.fromEntries(section.fields.map((field) => [field.key, '']))

  const updateEntry = (index: number, key: string, value: string) => {
    onChange(
      entries.map((entry, i) =>
        i === index ? { ...entry, [key]: normalizeFieldValue(value) } : entry,
      ),
    )
  }

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-medium">{section.label}</h3>
        {section.description !== '' && (
          <p className="text-xs text-muted">{section.description}</p>
        )}
      </div>

      {entries.map((entry, index) => (
        <div key={index} className="space-y-3 rounded-md border border-line p-3">
          <div className="flex items-baseline justify-between">
            <span className="text-xs text-muted">
              {section.label} {index + 1}
            </span>
            <button
              type="button"
              onClick={() => { onChange(entries.filter((_, i) => i !== index)) }}
              className="text-xs text-muted underline underline-offset-4"
            >
              Remove
            </button>
          </div>

          {section.fields.map((field) => {
            const id = `${section.key}-${String(index)}-${field.key}`
            return (
              <div key={field.key} className="space-y-1">
                <label htmlFor={id} className="block text-xs font-medium">
                  {field.label}
                </label>
                <textarea
                  id={id}
                  rows={2}
                  value={entry[field.key] ?? ''}
                  onChange={(event) => { updateEntry(index, field.key, event.target.value) }}
                  className="w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm"
                />
              </div>
            )
          })}
        </div>
      ))}

      <button
        type="button"
        onClick={() => { onChange([...entries, blank()]) }}
        className="rounded-md border border-line px-3 py-2 text-sm"
      >
        Add {section.label.toLowerCase().replace(/ entries$/, ' entry')}
      </button>
    </div>
  )
}
