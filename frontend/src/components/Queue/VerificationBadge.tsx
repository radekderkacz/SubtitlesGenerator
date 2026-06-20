import { CheckCircle2, AlertTriangle, XCircle, Loader2, MinusCircle } from 'lucide-react'
import type { VerificationStatus } from '@/types/api'

type Props = Readonly<{ status: VerificationStatus | null; score?: number | null }>

const MAP: Record<VerificationStatus, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
  running: { label: 'Verifying…', cls: 'text-muted-foreground', Icon: Loader2 },
  pass:    { label: 'Verified', cls: 'text-green-500', Icon: CheckCircle2 },
  warn:    { label: 'Check', cls: 'text-amber-500', Icon: AlertTriangle },
  fail:    { label: 'Failed', cls: 'text-destructive', Icon: XCircle },
  skipped: { label: 'Not verified', cls: 'text-muted-foreground/60', Icon: MinusCircle },
  error:   { label: 'Verify error', cls: 'text-muted-foreground/60', Icon: MinusCircle },
}

export default function VerificationBadge({ status, score }: Props) {
  if (!status) return null
  const { label, cls, Icon } = MAP[status]
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider ${cls}`}>
      <Icon className={`h-3.5 w-3.5 ${status === 'running' ? 'animate-spin' : ''}`} aria-hidden="true" />
      {label}{status === 'pass' && typeof score === 'number' ? ` ${Math.round(score)}` : ''}
    </span>
  )
}
