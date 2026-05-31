type Props = Readonly<{
  label: string
  cssVar: string
  ariaLabel: string
}>

/**
 * Pill-shaped badge with a custom CSS-variable background. Both PhaseBadge
 * and the Auto-source indicator on JobRow share this primitive.
 */
export default function ColorPillBadge({ label, cssVar, ariaLabel }: Props) {
  return (
    <span
      aria-label={ariaLabel}
      className="inline-block rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-tighter text-white transition-colors duration-150"
      style={{ backgroundColor: `var(${cssVar})` }}
    >
      {label}
    </span>
  )
}
