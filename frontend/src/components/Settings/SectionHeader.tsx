import type { ReactNode } from 'react'
import type { ProbeStatus } from '@/store/settingsStatusStore'
import StatusDot from './StatusDot'

type Props = Readonly<{
  title: string
  description: string
  status: ProbeStatus
  detail?: string | null
  action?: ReactNode
}>

export default function SectionHeader({ title, description, status, detail, action }: Props) {
  // Project class vocabulary (NOT external M3 token classes — those are a
  // prototype dialect that produces no-op CSS here; see the
  // design-token → project class mapping. headline-sm (20px/600) → text-xl
  // font-semibold; on-surface → foreground; on-surface-variant →
  // muted-foreground; surface-container-low → the raw var (semantic, not
  // bg-sidebar which only coincidentally shares the hex).
  return (
    <header className="flex justify-between items-start gap-4 pb-4 mb-6 border-b border-border">
      <div>
        <h3 className="text-xl font-semibold text-foreground mb-1">{title}</h3>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="flex items-center gap-4 shrink-0">
        <span className="flex items-center gap-2 bg-[var(--surface-container-low)] px-3 py-1 rounded-full text-xs font-semibold tracking-wider text-muted-foreground">
          <StatusDot status={status} />
          {detail ?? null}
        </span>
        {action}
      </div>
    </header>
  )
}
