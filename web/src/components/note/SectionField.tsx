import { normalizeFieldValue, type SectionSpec } from '@/lib/note'

/**
 * One prose section, labelled and described by the template.
 *
 * The description is the same sentence the prompt gave the model, shown to the nurse
 * as help text: the instruction the note was written against is also the best
 * statement of what belongs in the box.
 */
export function SectionField({
  section,
  value,
  onChange,
}: {
  section: SectionSpec
  value: string | null
  onChange: (next: string | null) => void
}) {
  const id = `section-${section.key}`
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="block text-sm font-medium">
        {section.label}
      </label>
      {section.description !== '' && (
        <p className="text-xs text-muted">{section.description}</p>
      )}
      <textarea
        id={id}
        rows={4}
        value={value ?? ''}
        onChange={(event) => { onChange(normalizeFieldValue(event.target.value)) }}
        className="w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm"
      />
    </div>
  )
}
