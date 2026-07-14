import { CheckCircle2, AlertTriangle, XCircle, Loader2, MinusCircle } from 'lucide-react'
import type { VerificationStatus } from '@/types/api'
import { badgeLabel } from '@/lib/verificationCopy'

type Props = Readonly<{ status: VerificationStatus | null; score?: number | null }>

const STYLE: Record<VerificationStatus, { cls: string; Icon: typeof CheckCircle2 }> = {
  running: { cls: 'text-muted-foreground', Icon: Loader2 },
  pass:    { cls: 'text-green-500', Icon: CheckCircle2 },
  warn:    { cls: 'text-amber-500', Icon: AlertTriangle },
  fail:    { cls: 'text-destructive', Icon: XCircle },
  skipped: { cls: 'text-muted-foreground/60', Icon: MinusCircle },
  error:   { cls: 'text-muted-foreground/60', Icon: MinusCircle },
}

export default function VerificationBadge({ status }: Props) {
  if (!status) return null
  const { cls, Icon } = STYLE[status]
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider ${cls}`}>
      <Icon className={`h-3.5 w-3.5 ${status === 'running' ? 'animate-spin' : ''}`} aria-hidden="true" />
      {badgeLabel(status)}
    </span>
  )
}
