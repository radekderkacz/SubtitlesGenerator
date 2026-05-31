import { Check, X } from 'lucide-react'
import type { JobPhase, JobStatus } from '@/types/api'

type StepKey = 'queued' | 'extracting' | 'transcribing' | 'translating' | 'writing' | 'done'

type StepState = 'completed' | 'active' | 'pending' | 'failed' | 'cancelled'

type Step = Readonly<{
  key: StepKey
  label: string
  cssVar: string // CSS custom property used for the active/completed ring
}>

const STEPS: ReadonlyArray<Step> = [
  { key: 'queued', label: 'Queued', cssVar: '--phase-queued' },
  { key: 'extracting', label: 'Extracting Audio', cssVar: '--phase-extracting' },
  { key: 'transcribing', label: 'Transcribing', cssVar: '--phase-transcribing' },
  { key: 'translating', label: 'Translating', cssVar: '--phase-translating' },
  { key: 'writing', label: 'Writing SRT', cssVar: '--phase-writing' },
  { key: 'done', label: 'Done', cssVar: '--phase-done' },
]

const PHASE_TO_INDEX: Record<JobPhase, number> = {
  extracting: 1,
  transcribing: 2,
  translating: 3,
  writing: 4,
  done: 5,
}

function activeIndex(status: JobStatus, phase: JobPhase | null): number {
  if (status === 'queued') return 0
  if (status === 'completed') return 5
  // failed, cancelled, processing fall through to phase-based
  if (phase === null) return status === 'processing' ? 0 : -1
  return PHASE_TO_INDEX[phase]
}

function compareToActive(stepIndex: number, active: number): 'before' | 'at' | 'after' {
  if (stepIndex < active) return 'before'
  if (stepIndex === active) return 'at'
  return 'after'
}

function stateForFailed(stepIndex: number, active: number): StepState {
  if (active === -1) return stepIndex === 0 ? 'failed' : 'pending'
  const cmp = compareToActive(stepIndex, active)
  if (cmp === 'before') return 'completed'
  if (cmp === 'at') return 'failed'
  return 'pending'
}

function stateForCancelled(stepIndex: number, active: number): StepState {
  const cmp = compareToActive(stepIndex, active)
  if (cmp === 'before') return 'completed'
  if (cmp === 'at' && active !== -1) return 'cancelled'
  return 'pending'
}

function stateForActive(stepIndex: number, active: number): StepState {
  const cmp = compareToActive(stepIndex, active)
  if (cmp === 'before') return 'completed'
  if (cmp === 'at') return 'active'
  return 'pending'
}

function stateForStep(
  stepIndex: number,
  status: JobStatus,
  phase: JobPhase | null,
): StepState {
  if (status === 'completed') return 'completed'
  const active = activeIndex(status, phase)
  if (status === 'failed') return stateForFailed(stepIndex, active)
  if (status === 'cancelled') return stateForCancelled(stepIndex, active)
  return stateForActive(stepIndex, active)
}

type Props = Readonly<{
  status: JobStatus
  phase: JobPhase | null
}>

export default function PhaseTimeline({ status, phase }: Props) {
  return (
    <ol className="relative space-y-0" aria-label="Pipeline status">
      <div className="absolute left-[11px] top-2 bottom-2 w-[2px] bg-secondary" aria-hidden="true" />
      {STEPS.map((step, i) => {
        const state = stateForStep(i, status, phase)
        const isLast = i === STEPS.length - 1
        return (
          <li
            key={step.key}
            className={`relative flex items-start gap-4 ${isLast ? '' : 'pb-6'}`}
            data-state={state}
            data-step={step.key}
          >
            <StepDot state={state} cssVar={step.cssVar} />
            <div className="pt-0.5">
              <p className={`text-sm font-medium ${labelClassFor(state)}`} style={labelStyleFor(state, step.cssVar)}>
                {step.label}
              </p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

type StepDotProps = Readonly<{ state: StepState; cssVar: string }>

function StepDot({ state, cssVar }: StepDotProps) {
  const baseRing = 'relative z-10 w-6 h-6 rounded-full flex items-center justify-center bg-background'
  if (state === 'completed') {
    return (
      <div
        className={`${baseRing} border-2`}
        style={{ borderColor: 'var(--phase-done)', backgroundColor: 'var(--phase-done)' }}
      >
        <Check className="h-3 w-3 text-background" aria-hidden="true" />
      </div>
    )
  }
  if (state === 'active') {
    return (
      <div
        className={`${baseRing} border-2 animate-pulse`}
        style={{
          borderColor: `var(${cssVar})`,
          boxShadow: `0 0 15px color-mix(in srgb, var(${cssVar}) 40%, transparent)`,
        }}
      >
        <div className="w-2 h-2 rounded-full" style={{ backgroundColor: `var(${cssVar})` }} />
      </div>
    )
  }
  if (state === 'failed') {
    return (
      <div
        className={`${baseRing} border-2`}
        style={{ borderColor: 'var(--phase-failed)' }}
      >
        <X className="h-3 w-3" style={{ color: 'var(--phase-failed)' }} aria-hidden="true" />
      </div>
    )
  }
  if (state === 'cancelled') {
    return (
      <div className={`${baseRing} border-2 border-muted-foreground/40`}>
        <div className="w-2 h-2 rounded-full bg-muted-foreground/60" />
      </div>
    )
  }
  // pending
  return (
    <div className={`${baseRing} border-2 border-secondary`}>
      <div className="w-2 h-2 rounded-full bg-secondary" />
    </div>
  )
}

function labelClassFor(state: StepState): string {
  if (state === 'completed') return 'text-muted-foreground'
  if (state === 'pending') return 'text-muted-foreground/60'
  if (state === 'cancelled') return 'text-muted-foreground'
  // active and failed get colored via inline style
  return ''
}

function labelStyleFor(state: StepState, cssVar: string): React.CSSProperties | undefined {
  if (state === 'active') return { color: `var(${cssVar})` }
  if (state === 'failed') return { color: 'var(--phase-failed)' }
  return undefined
}
