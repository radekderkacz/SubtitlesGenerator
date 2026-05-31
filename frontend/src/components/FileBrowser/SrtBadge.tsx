import { Check } from 'lucide-react'

type Props = Readonly<{ hasSrt: boolean }>

/**
 * Pill badge showing whether a video file has a companion SRT.
 * - `true`  → emerald "SRT ✓" pill
 * - `false` → muted "No SRT" pill
 *.
 */
export default function SrtBadge({ hasSrt }: Props) {
  if (hasSrt) {
    return (
      <span
        aria-label="Has SRT"
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500 text-[10px] font-bold uppercase tracking-tighter border border-emerald-500/20"
      >
        <Check className="h-3 w-3" aria-hidden="true" />
        SRT
      </span>
    )
  }
  return (
    <span
      aria-label="No SRT"
      className="inline-block px-2 py-0.5 rounded-full bg-secondary text-muted-foreground text-[10px] font-bold uppercase tracking-tighter border border-border"
    >
      No SRT
    </span>
  )
}
