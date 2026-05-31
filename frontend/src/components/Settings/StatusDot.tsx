import type { ProbeStatus } from '@/store/settingsStatusStore'

const DOT: Record<ProbeStatus, string> = {
  idle: 'bg-muted-foreground/40',
  checking: 'bg-amber-400 animate-pulse',
  ok: 'bg-emerald-500',
  warn: 'bg-amber-500',
  error: 'bg-red-500',
}
const LABEL: Record<ProbeStatus, string> = {
  idle: 'Not checked', checking: 'Checking…', ok: 'OK', warn: 'Warning', error: 'Error',
}

export default function StatusDot({ status }: Readonly<{ status: ProbeStatus }>) {
  return (
    <span
      data-testid="section-status"
      data-status={status}
      className={`inline-block h-2 w-2 rounded-full shrink-0 ${DOT[status]}`}
      aria-label={LABEL[status]}
    />
  )
}
