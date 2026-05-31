import ColorPillBadge from './ColorPillBadge'
import type { Job, JobPhase, JobStatus } from '@/types/api'

type PhaseStyle = {
  label: string
  cssVar: string
}

function resolvePhaseStyle(status: JobStatus, phase: JobPhase | null): PhaseStyle {
  if (status === 'completed') return { label: 'Done', cssVar: '--phase-done' }
  if (status === 'failed') return { label: 'Failed', cssVar: '--phase-failed' }
  if (status === 'cancelled') return { label: 'Cancelled', cssVar: '--phase-cancelled' }
  if (status === 'queued') return { label: 'Queued', cssVar: '--phase-queued' }
  switch (phase) {
    case 'extracting':
      return { label: 'Extracting', cssVar: '--phase-extracting' }
    case 'transcribing':
      return { label: 'Transcribing', cssVar: '--phase-transcribing' }
    case 'translating':
      return { label: 'Translating', cssVar: '--phase-translating' }
    case 'writing':
      return { label: 'Writing', cssVar: '--phase-writing' }
    default:
      return { label: 'Processing', cssVar: '--phase-transcribing' }
  }
}

type Props = Readonly<{
  status: Job['status']
  phase: Job['phase']
}>

export default function PhaseBadge({ status, phase }: Props) {
  const { label, cssVar } = resolvePhaseStyle(status, phase)
  return <ColorPillBadge label={label} cssVar={cssVar} ariaLabel={`Phase: ${label}`} />
}
