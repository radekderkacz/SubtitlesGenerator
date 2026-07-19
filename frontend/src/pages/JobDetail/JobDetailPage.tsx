import { Link, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, CheckCircle2, FileQuestion, RefreshCw, XCircle } from 'lucide-react'
import PhaseBadge from '@/components/Queue/PhaseBadge'
import PhaseTimeline from '@/components/Queue/PhaseTimeline'
import CompletionCard from '@/components/Queue/CompletionCard'
import ErrorCard from '@/components/Queue/ErrorCard'
import LiveLogPane from '@/components/Queue/LiveLogPane'
import VerificationBadge from '@/components/Queue/VerificationBadge'
import { ApiRequestError, getJob, getJobLog, reverifyJob } from '@/lib/api'
import { useJobStore } from '@/store/jobStore'
import { withApiToast } from '@/lib/apiToast'
import { verdictHeadline, issueCopy, formatClock, type IssueCopy } from '@/lib/verificationCopy'
import { basename, formatDuration } from '@/lib/utils'
import type { Job } from '@/types/api'
import { isAutoRetryJob, autoRetryOriginalId } from '@/lib/jobSource'

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

type CheckRowProps = Readonly<{
  layer: string
  name: string
  severity: string
  detail: string
}>

function severityClass(severity: string): string {
  if (severity === 'fail') return 'text-destructive'
  if (severity === 'warn') return 'text-amber-500'
  return 'text-muted-foreground'
}

function CheckRow({ name, severity, detail }: CheckRowProps) {
  return (
    <li className={`flex items-start gap-2 text-xs ${severityClass(severity)}`}>
      <span className="font-mono font-semibold shrink-0">{name}</span>
      <span className="text-muted-foreground">{detail}</span>
    </li>
  )
}

type IssueBlockProps = Readonly<{
  severity: string
  copy: IssueCopy
  repeated?: { text: string; start: number; end: number; count: number }
}>

function IssueBlock({ severity, copy, repeated }: IssueBlockProps) {
  const Icon = severity === 'fail' ? XCircle : AlertTriangle
  const color = severity === 'fail' ? 'text-destructive' : 'text-amber-500'
  return (
    <div className="flex items-start gap-2.5">
      <Icon className={`h-4 w-4 shrink-0 mt-0.5 ${color}`} aria-hidden="true" />
      <div className="space-y-0.5">
        <p className="text-sm font-semibold text-foreground">{copy.title}</p>
        <p className="text-xs text-muted-foreground">{copy.explanation}</p>
        {copy.suggestion && (
          <p className="text-xs text-muted-foreground/90">→ {copy.suggestion}</p>
        )}
        {repeated && (
          <details className="text-xs text-muted-foreground/90 mt-0.5">
            <summary className="cursor-pointer hover:text-foreground select-none">Show the repeated line</summary>
            <p className="mt-1">
              <span className="font-mono">{repeated.text}</span>{' '}· repeated {repeated.count}× · {formatClock(repeated.start)}–{formatClock(repeated.end)}
            </p>
          </details>
        )}
      </div>
    </div>
  )
}

type MetricTile = Readonly<{ label: string; value: string; unit?: string; alert?: boolean }>

function metricTiles(m: NonNullable<NonNullable<Job['verification_report']>['metrics']>): MetricTile[] {
  const tiles: MetricTile[] = [
    { label: 'Read speed p95', value: `${m.cps_p95}`, unit: 'cps', alert: m.cps_p95 > 20 },
    { label: 'Fast cues', value: `${m.pct_cues_over_20cps}`, unit: '%', alert: m.pct_cues_over_20cps > 5 },
    { label: 'Cues', value: m.cue_count.toLocaleString() },
    { label: 'Shortest cue', value: m.min_duration.toFixed(2), unit: 's', alert: m.min_duration < 0.5 },
  ]
  if (m.coverage_ratio !== null && m.coverage_ratio !== undefined) {
    tiles.splice(2, 0, {
      label: 'Coverage',
      value: `${Math.round(m.coverage_ratio * 100)}`,
      unit: '%',
      alert: m.coverage_ratio < 0.5 || m.coverage_ratio > 1.1,
    })
  }
  if (m.gaps_over_90s > 0) {
    tiles.push({ label: 'Long silences', value: `${m.gaps_over_90s}`, unit: `max ${Math.round(m.max_gap)}s` })
  }
  return tiles
}

type ScorecardProps = Readonly<{ metrics: NonNullable<NonNullable<Job['verification_report']>['metrics']> }>

// Tile idiom: lowered tile surface inside the card, bold tracked micro-label,
// mono value with the unit as a small muted suffix. The grid sizes itself by
// CONTAINER width (auto-fit/minmax) — viewport breakpoints crammed six
// one-letter tiles into the panel's narrow column (bug report 2026-07-14).
function QualityScorecard({ metrics }: ScorecardProps) {
  const tiles = metricTiles(metrics)
  if (tiles.length === 0) return null
  return (
    <div
      data-testid="quality-scorecard"
      className="grid grid-cols-[repeat(auto-fit,minmax(7.5rem,1fr))] gap-2 mb-4"
    >
      {tiles.map((t) => (
        <div key={t.label} className="bg-background/60 border border-border/50 rounded-lg px-2.5 py-2">
          <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground leading-tight mb-1">
            {t.label}
          </p>
          <p
            className={`text-base leading-tight font-mono tabular-nums whitespace-nowrap ${t.alert ? 'text-amber-400' : 'text-foreground'}`}
          >
            {t.value}
            {t.unit && <span className="text-xs font-normal text-muted-foreground"> {t.unit}</span>}
          </p>
        </div>
      ))}
    </div>
  )
}

type VerificationPanelProps = Readonly<{ job: Job }>

function VerificationPanel({ job }: VerificationPanelProps) {
  if (!job.verification_status) return null
  const status = job.verification_status
  const checks = job.verification_report?.checks ?? []

  const ranked = checks
    .filter((c) => c.severity === 'fail' || c.severity === 'warn')
    .sort((a, b) => (a.severity === 'fail' ? 0 : 1) - (b.severity === 'fail' ? 0 : 1))
  const seen = new Set<string>()
  const issues: Array<{ severity: string; copy: IssueCopy; repeated?: { text: string; start: number; end: number; count: number } }> = []
  for (const c of ranked) {
    const copy = issueCopy(c)
    if (copy && !seen.has(copy.title)) {
      seen.add(copy.title)
      issues.push({ severity: c.severity, copy, repeated: c.repeated })
    }
  }

  const okCount = checks.filter((c) => c.severity === 'ok').length
  const headline = verdictHeadline(status, issues.length)

  const layers = ['structural', 'heuristic', 'semantic'] as const
  const grouped = layers
    .map((layer) => ({ layer, items: checks.filter((c) => c.layer === layer) }))
    .filter((g) => g.items.length > 0)

  const handleReverify = () => {
    void withApiToast(() => reverifyJob(job.id), { successMessage: 'Re-verification started' })
  }

  return (
    <section aria-labelledby="verification-heading" className="bg-card border border-border rounded-lg p-6">
      <div className="flex items-center justify-between mb-3">
        <h2 id="verification-heading" className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
          Verification
        </h2>
        <VerificationBadge status={status} />
      </div>

      {headline.summary && (
        <p className="text-sm text-foreground/80 mb-4">{headline.summary}</p>
      )}

      {job.verification_report?.auto_retry_job_id && (
        <p className="text-sm text-foreground/80 bg-secondary/50 border border-border rounded px-3 py-2 mb-4">
          Your setup runs locally at no cost, so a fresh attempt was started automatically.{' '}
          <Link
            to={`/jobs/${job.verification_report.auto_retry_job_id}`}
            className="text-[var(--action-accent)] hover:underline font-medium"
          >
            View the retry
          </Link>
        </p>
      )}

      {issues.length > 0 && (
        <div className="space-y-3 mb-4">
          {issues.map((it) => (
            <IssueBlock key={it.copy.title} severity={it.severity} copy={it.copy} repeated={it.repeated} />
          ))}
        </div>
      )}

      {job.verification_report?.metrics && (
        <QualityScorecard metrics={job.verification_report.metrics} />
      )}

      {okCount > 0 && (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground mb-4">
          <CheckCircle2 className="h-3.5 w-3.5 text-green-500" aria-hidden="true" />
          {okCount} other check{okCount === 1 ? '' : 's'} passed.
        </p>
      )}

      {checks.length > 0 && (
        <details className="mb-4">
          <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground select-none">
            See all details
          </summary>
          <div className="mt-3 space-y-3">
            {grouped.map(({ layer, items }) => (
              <div key={layer}>
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-1">{layer}</p>
                <ul className="space-y-1">
                  {items.map((c, i) => (
                    <CheckRow key={`${c.name}-${i}`} layer={c.layer} name={c.name} severity={c.severity} detail={c.detail} />
                  ))}
                </ul>
              </div>
            ))}
            {typeof job.verification_score === 'number' && (
              <p className="text-[11px] text-muted-foreground/70">Score: {Math.round(job.verification_score)}/100</p>
            )}
          </div>
        </details>
      )}

      <button
        type="button"
        onClick={handleReverify}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-secondary text-secondary-foreground text-xs font-medium hover:opacity-90 transition-opacity"
      >
        <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
        Re-verify
      </button>
    </section>
  )
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

  // The verification verdict lands AFTER this page's react-query snapshot (it's
  // post-completion / triggered by Re-verify), arriving over SSE into the job
  // store. Overlay the live verification fields so the panel updates without a
  // manual reload. (The store entry may be a partial — only verification fields
  // are overlaid; the rest of the job comes from the query.)
  const liveJob = useJobStore((s) => s.jobs.find((j) => j.id === safeId))

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

  const job = liveJob
    ? {
        ...jobQuery.data,
        verification_status: liveJob.verification_status ?? jobQuery.data.verification_status,
        verification_score: liveJob.verification_score ?? jobQuery.data.verification_score,
        verification_report: liveJob.verification_report ?? jobQuery.data.verification_report,
      }
    : jobQuery.data
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
        {isAutoRetryJob(job) && (
          <p className="text-xs text-muted-foreground">
            Automatic retry of a run whose subtitles failed verification —{' '}
            <Link
              to={`/jobs/${autoRetryOriginalId(job)}`}
              className="text-[var(--action-accent)] hover:underline"
            >
              view the original job
            </Link>
          </p>
        )}
        {job.source_srt_path && !isAutoRetryJob(job) && (
          <p className="text-xs text-muted-foreground">
            Sourced from an existing subtitle track (verified, transcription skipped):{' '}
            <span className="font-mono">{basename(job.source_srt_path)}</span>
          </p>
        )}
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
          <VerificationPanel job={job} />
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
