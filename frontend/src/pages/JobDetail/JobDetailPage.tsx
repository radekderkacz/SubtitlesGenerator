import { Link, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, FileQuestion } from 'lucide-react'
import PhaseBadge from '@/components/Queue/PhaseBadge'
import PhaseTimeline from '@/components/Queue/PhaseTimeline'
import CompletionCard from '@/components/Queue/CompletionCard'
import ErrorCard from '@/components/Queue/ErrorCard'
import LiveLogPane from '@/components/Queue/LiveLogPane'
import { ApiRequestError, getJob, getJobLog } from '@/lib/api'
import { basename, formatDuration } from '@/lib/utils'
import type { Job } from '@/types/api'

type Props = Readonly<Record<string, never>>

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

export default function JobDetailPage(_props: Props) {
  const { id } = useParams<{ id: string }>()
  const safeId = id ?? ''

  const jobQuery = useQuery({
    queryKey: ['job', safeId],
    queryFn: () => getJob(safeId),
    enabled: safeId !== '',
    retry: (failureCount, error) => {
      // Don't retry on a 404 — that's a real "not found", not a flake.
      if (error instanceof ApiRequestError && error.status === 404) return false
      return failureCount < 2
    },
  })

  // Per-job log only exists once the worker has written one. 404 is expected
  // for queued jobs that never started — surface no error in that case.
  const logQuery = useQuery({
    queryKey: ['job-log', safeId],
    queryFn: () => getJobLog(safeId),
    enabled: safeId !== '' && jobQuery.data !== undefined,
    retry: false,
  })

  if (jobQuery.isError && jobQuery.error instanceof ApiRequestError && jobQuery.error.status === 404) {
    return <NotFoundState />
  }

  if (jobQuery.isLoading || jobQuery.data === undefined) {
    return (
      <output className="block max-w-[1400px] mx-auto p-6 text-sm text-muted-foreground">
        Loading job…
      </output>
    )
  }

  const job = jobQuery.data
  const filename = basename(job.file_path)
  const showCompletion = job.status === 'completed'
  const showError = job.status === 'failed'

  return (
    <article aria-label={`Job detail: ${filename}`} className="max-w-[1400px] mx-auto p-6">
      <header className="mb-8 space-y-2">
        <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-xs text-muted-foreground font-mono mb-4">
          <Link to="/history" className="hover:text-foreground transition-colors">History</Link>
          <span className="text-border">/</span>
          <span className="text-foreground font-semibold truncate" title={job.file_path}>{filename}</span>
        </nav>
        <div className="flex items-baseline gap-3 flex-wrap">
          <h1 className="text-2xl font-bold tracking-tight text-foreground truncate" title={job.file_path}>
            {filename}
          </h1>
          <PhaseBadge status={job.status} phase={job.phase} />
        </div>
        <p className="font-mono text-sm text-muted-foreground truncate" title={job.file_path}>
          {job.file_path}
        </p>
        <p className="text-xs text-muted-foreground font-mono">ID: {job.id}</p>
        <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground pt-2">
          <div>
            Submitted: <span className="font-mono text-foreground">{formatSubmittedAt(job.created_at)}</span>
          </div>
          <div className="border-l border-border pl-4">
            Duration: <span className="font-mono text-foreground">{durationLabel(job)}</span>
          </div>
          <div className="border-l border-border pl-4 flex items-center gap-2">
            <span>Model:</span>
            <span className="px-2 py-0.5 bg-secondary text-muted-foreground text-[11px] font-mono border border-border rounded">
              {job.model_size ?? 'system default'}
            </span>
          </div>
          {job.target_language && (
            <div className="border-l border-border pl-4">
              Language: <span className="font-mono text-foreground">{job.target_language}</span>
            </div>
          )}
        </dl>
      </header>

      <div className="flex flex-col lg:flex-row gap-6">
        <div className="w-full lg:w-[400px] shrink-0 space-y-6">
          <section
            aria-labelledby="pipeline-status-heading"
            className="bg-card border border-border rounded-lg p-6"
          >
            <h2
              id="pipeline-status-heading"
              className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-6"
            >
              Pipeline Status
            </h2>
            <PhaseTimeline status={job.status} phase={job.phase} />
          </section>
          {showCompletion && <CompletionCard job={job} />}
          {showError && <ErrorCard job={job} />}
        </div>
        <div className="flex-1 min-w-0">
          <LiveLogPane job={job} rawLog={logQuery.data} />
        </div>
      </div>
    </article>
  )
}

function NotFoundState() {
  return (
    <div className="max-w-[1400px] mx-auto p-6 flex items-center justify-center min-h-[60vh]">
      <div className="text-center space-y-4">
        <div className="w-16 h-16 mx-auto rounded-full bg-secondary/60 flex items-center justify-center text-muted-foreground">
          <FileQuestion className="h-8 w-8" aria-hidden="true" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-foreground">Job not found.</h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-sm">
            The job ID in the URL doesn&apos;t match any record. It may have been cleared from history.
          </p>
        </div>
        <Link
          to="/history"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Back to History
        </Link>
      </div>
    </div>
  )
}
