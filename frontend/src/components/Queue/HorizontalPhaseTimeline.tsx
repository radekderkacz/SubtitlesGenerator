import { Check } from 'lucide-react'
import type { JobPhase, JobStatus } from '@/types/api'

const STEPS = [
  { key: 'queued', label: 'Queued' },
  { key: 'extracting', label: 'Extract Audio' },
  { key: 'transcribing', label: 'Transcribing' },
  { key: 'translating', label: 'Translate' },
  { key: 'writing', label: 'Finalize' },
] as const

const PHASE_TO_INDEX: Record<NonNullable<JobPhase>, number> = {
  extracting: 1,
  transcribing: 2,
  translating: 3,
  writing: 4,
  done: 5,
}

type StepState = 'done' | 'active' | 'pending' | 'failed' | 'cancelled'

function stateForStep(stepIndex: number, active: number, status: JobStatus): StepState {
  if (stepIndex < active) return 'done'
  if (stepIndex > active) return 'pending'
  if (status === 'failed') return 'failed'
  if (status === 'cancelled') return 'cancelled'
  return 'active'
}

function activeIndex(status: JobStatus, phase: JobPhase | null): number {
  if (status === 'completed') return 5
  if (status === 'queued') return 0
  if (status === 'failed' || status === 'cancelled') {
    return phase ? PHASE_TO_INDEX[phase] : 0
  }
  return phase ? PHASE_TO_INDEX[phase] : 0
}

type Props = Readonly<{
  status: JobStatus
  phase: JobPhase | null
}>

/**
 * Horizontal 5-step pipeline pill row used by the Active Queue
 * focus card. Connector line behind, dots on top, the active step is
 * outlined + animated; completed steps are filled with a checkmark.
 */
export default function HorizontalPhaseTimeline({ status, phase }: Props) {
  const active = activeIndex(status, phase)
  // Spread the steps evenly; dots are at 10%, 30%, 50%, 70%, 90% of the row.
  // The active progress line stops at the centre of the active dot.
  const activeDotPercent = 10 + active * 20

  return (
    <div
      className="flex justify-between items-start px-2 pt-2 relative"
      aria-label="Pipeline status"
    >
      <div
        aria-hidden="true"
        className="absolute top-3 left-[10%] right-[10%] h-[2px] bg-secondary z-0"
      />
      <div
        aria-hidden="true"
        className="absolute top-3 left-[10%] h-[2px] bg-[var(--action-accent)] z-0 shadow-[0_0_10px_rgba(59,130,246,0.5)] transition-all"
        style={{ width: active === 0 ? 0 : `${activeDotPercent - 10}%` }}
      />
      {STEPS.map((step, i) => (
        <StepDot
          key={step.key}
          label={step.label}
          state={stateForStep(i, active, status)}
        />
      ))}
    </div>
  )
}

type StepDotProps = Readonly<{
  label: string
  state: StepState
}>

function StepDot({ label, state }: StepDotProps) {
  const base = 'relative z-10 w-6 h-6 rounded-full flex items-center justify-center'
  if (state === 'done') {
    return (
      <div className="flex flex-col items-center gap-2">
        <div className={`${base} bg-[var(--action-accent)] text-white`}>
          <Check className="h-3 w-3" aria-hidden="true" />
        </div>
        <span className="text-[11px] uppercase tracking-wider font-semibold text-foreground">
          {label}
        </span>
      </div>
    )
  }
  if (state === 'active') {
    return (
      <div className="flex flex-col items-center gap-2">
        <div
          className={`${base} border-2 border-[var(--action-accent)] bg-card animate-pulse shadow-[0_0_12px_rgba(59,130,246,0.5)]`}
        >
          <div className="w-2 h-2 rounded-full bg-[var(--action-accent)]" />
        </div>
        <span className="text-[11px] uppercase tracking-wider font-semibold text-[var(--action-accent)]">
          {label}
        </span>
      </div>
    )
  }
  if (state === 'failed') {
    return (
      <div className="flex flex-col items-center gap-2">
        <div className={`${base} border-2 border-destructive bg-card`}>
          <div className="w-2 h-2 rounded-full bg-destructive" />
        </div>
        <span className="text-[11px] uppercase tracking-wider font-semibold text-destructive">
          {label}
        </span>
      </div>
    )
  }
  if (state === 'cancelled') {
    return (
      <div className="flex flex-col items-center gap-2">
        <div className={`${base} border-2 border-muted-foreground/40 bg-card`}>
          <div className="w-2 h-2 rounded-full bg-muted-foreground/40" />
        </div>
        <span className="text-[11px] uppercase tracking-wider font-semibold text-muted-foreground">
          {label}
        </span>
      </div>
    )
  }
  return (
    <div className="flex flex-col items-center gap-2">
      <div className={`${base} border-2 border-border bg-card`} />
      <span className="text-[11px] uppercase tracking-wider font-semibold text-muted-foreground">
        {label}
      </span>
    </div>
  )
}
