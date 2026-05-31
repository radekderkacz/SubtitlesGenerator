import { Inbox } from 'lucide-react'
import PhaseBadge from './PhaseBadge'
import PhaseTimeline from './PhaseTimeline'
import CompletionCard from './CompletionCard'
import ErrorCard from './ErrorCard'
import LiveLogPane from './LiveLogPane'
import StuckJobFooter from './StuckJobFooter'
import { basename, formatDuration } from '@/lib/utils'
import type { Job } from '@/types/api'

type Props = Readonly<{
  selectedJob: Job | null
}>

function durationLabel(job: Job): string {
  const start = Date.parse(job.created_at)
  if (!Number.isFinite(start)) return '—'
  const endRaw = job.completed_at ?? job.updated_at
  const end = Date.parse(endRaw)
  if (!Number.isFinite(end)) return '—'
  return formatDuration((end - start) / 1000)
}

function formatSubmittedAt(iso: string): string {
  const ms = Date.parse(iso)
  if (!Number.isFinite(ms)) return iso
  return new Date(ms).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function JobDetailPanel({ selectedJob }: Props) {
  if (selectedJob === null) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <div className="w-14 h-14 rounded-full bg-secondary/60 flex items-center justify-center text-muted-foreground mb-4">
          <Inbox className="h-7 w-7" aria-hidden="true" />
        </div>
        <h3 className="text-base font-semibold text-foreground mb-1">Select a job</h3>
        <p className="text-sm text-muted-foreground max-w-xs">
          Pick a job from the queue to inspect its pipeline status and live log output.
        </p>
      </div>
    )
  }

  const filename = basename(selectedJob.file_path)
  const showCompletion = selectedJob.status === 'completed'
  const showError = selectedJob.status === 'failed'

  return (
    <article aria-label={`Job detail: ${filename}`} className="flex-1 p-8 overflow-y-auto">
      <header className="mb-6 space-y-2">
        <div className="flex items-baseline gap-3 flex-wrap">
          <h2
            className="text-2xl font-bold tracking-tight text-foreground truncate"
            title={selectedJob.file_path}
          >
            {filename}
          </h2>
          <PhaseBadge status={selectedJob.status} phase={selectedJob.phase} />
        </div>
        <p
          className="font-mono text-sm text-muted-foreground truncate"
          title={selectedJob.file_path}
        >
          {selectedJob.file_path}
        </p>
        <p className="text-xs text-muted-foreground font-mono">ID: {selectedJob.id}</p>
        <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground pt-2">
          <div>
            Submitted:{' '}
            <span className="font-mono text-foreground">
              {formatSubmittedAt(selectedJob.created_at)}
            </span>
          </div>
          <div className="border-l border-border pl-4">
            Duration: <span className="font-mono text-foreground">{durationLabel(selectedJob)}</span>
          </div>
          <div className="border-l border-border pl-4 flex items-center gap-2">
            <span>Model:</span>
            <span className="px-2 py-0.5 bg-secondary text-muted-foreground text-[11px] font-mono border border-border rounded">
              {selectedJob.model_size ?? 'system default'}
            </span>
          </div>
        </dl>
      </header>

      <div className="flex flex-col lg:flex-row gap-6">
        <div className="w-full lg:w-[400px] shrink-0 space-y-6">
          <section
            aria-labelledby="pipeline-status-heading"
            className="bg-card border border-border rounded-lg p-6"
          >
            <h3
              id="pipeline-status-heading"
              className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-6"
            >
              Pipeline Status
            </h3>
            <PhaseTimeline status={selectedJob.status} phase={selectedJob.phase} />
          </section>
          {showCompletion && <CompletionCard job={selectedJob} />}
          {showError && <ErrorCard job={selectedJob} />}
        </div>
        <div className="flex-1 min-w-0">
          <LiveLogPane job={selectedJob} />
        </div>
      </div>

      <StuckJobFooter job={selectedJob} />
    </article>
  )
}
