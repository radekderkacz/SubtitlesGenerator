import { MODEL_STATUS_STYLES, type ModelStatus } from '@/lib/translation-models'

/** Inline status tag — a coloured dot + short label — rendered next to a
 *  model name in the dropdown row + under the input as a "current
 *  selection" indicator. The `note` prop is the hover/aria tooltip. */
export default function ModelStatusBadge({
  status,
  note,
}: Readonly<{ status: ModelStatus; note: string }>) {
  const styles = MODEL_STATUS_STYLES[status]
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[10px] text-muted-foreground"
      title={note}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full shrink-0 ${styles.dot}`} />
      <span className="uppercase tracking-wider">{styles.label}</span>
    </span>
  )
}
