import { useState } from 'react'
import { Link } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { Filter, Inbox, Plus } from 'lucide-react'
import { apiFetch, stopAllJobs } from '@/lib/api'
import { useJobStore } from '@/store/jobStore'
import ConfirmDialog from '@/components/ConfirmDialog/ConfirmDialog'
import ActiveJobCard from '@/components/Queue/ActiveJobCard'
import UpNextRail from '@/components/Queue/UpNextRail'
import WatchFolderPanel from '@/components/Queue/WatchFolderPanel'
import { withApiToast } from '@/lib/apiToast'
import { isActive, type Job, type Settings } from '@/types/api'

type Props = Readonly<Record<string, never>>

/**
 * Active Queue.
 *
 * The previous list+detail split panel is replaced by a focus-card bento:
 * the most-active job (first processing, else first queued) takes the main
 * 2-column area; everything else falls into the Up Next rail on the right.
 * Per-job deep-links go to /jobs/:id.
 */
export default function QueuePage(_props: Props) {
  const [stopAllOpen, setStopAllOpen] = useState(false)

  const jobs = useJobStore((s) => s.jobs)

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<Settings>('/api/v1/settings'),
  })

  const showSetupBanner =
    settings !== undefined &&
    (!settings.nas_mount_path || !settings.transcription_api_url)

  const { focused, secondary, pending } = pickActive(jobs)
  const activeCount = jobs.filter((j) => isActive(j.status)).length

  const handleStopAll = () =>
    withApiToast(() => stopAllJobs(), {
      successMessage: 'All running and queued jobs have been cancelled.',
    })

  return (
    <div className="max-w-[1280px] mx-auto p-6 pb-24">
      {/* ConnectionBanner moved to app-shell (Layout.tsx) so SSE staleness
          is surfaced on every page, not just the queue. */}
      {showSetupBanner && (
        <output className="block border border-amber-500/40 bg-amber-500/10 rounded-lg p-4 text-sm text-amber-200 mb-6">
          Setup required — configure your NAS path and AI backends in Settings before submitting jobs.{' '}
          <Link to="/settings" className="underline font-medium">
            Open Settings
          </Link>
        </output>
      )}

      <header className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground mb-1">
            Active Queue
          </h1>
          <p className="text-sm text-muted-foreground">
            {summaryLine(jobs)}
          </p>
        </div>
        <div className="flex gap-2">
          {activeCount > 0 && (
            <button
              type="button"
              onClick={() => setStopAllOpen(true)}
              className="px-4 py-2 rounded-lg text-xs uppercase tracking-wider font-semibold border border-destructive/30 text-destructive hover:bg-destructive/10 transition-colors"
            >
              Stop All
            </button>
          )}
          <button
            type="button"
            disabled
            title="Filtering coming in a follow-up"
            className="px-4 py-2 rounded-lg text-xs uppercase tracking-wider font-semibold border border-white/5 text-foreground hover:bg-secondary transition-colors flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Filter className="h-4 w-4" aria-hidden="true" />
            Filter
          </button>
          <Link
            to="/browse"
            className="px-4 py-2 rounded-lg text-xs uppercase tracking-wider font-semibold bg-[var(--action-accent)] text-white hover:bg-[var(--action-accent)]/90 transition-colors flex items-center gap-1.5 shadow-[0_0_15px_rgba(59,130,246,0.3)]"
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            New Task
          </Link>
        </div>
      </header>

      {focused === null ? (
        <EmptyState />
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <ActiveJobCard job={focused} />
          <UpNextRail secondary={secondary} pending={pending} />
        </div>
      )}

      <div className="mt-8">
        <WatchFolderPanel />
      </div>

      <ConfirmDialog
        open={stopAllOpen}
        onOpenChange={setStopAllOpen}
        title={`Stop ${activeCount} active job${activeCount === 1 ? '' : 's'}?`}
        description="All queued and running jobs will be cancelled. This cannot be undone."
        confirmLabel="Stop All"
        onConfirm={handleStopAll}
        destructive
      />
    </div>
  )
}

function pickActive(jobs: ReadonlyArray<Job>): {
  focused: Job | null
  secondary: Job[]
  pending: Job[]
} {
  const processing = jobs.filter((j) => j.status === 'processing')
  const queued = jobs.filter((j) => j.status === 'queued')
  const focused = processing[0] ?? queued[0] ?? null
  const secondary = processing.filter((j) => j.id !== focused?.id)
  const pending = queued.filter((j) => j.id !== focused?.id)
  return { focused, secondary, pending }
}

function summaryLine(jobs: ReadonlyArray<Job>): string {
  const processing = jobs.filter((j) => j.status === 'processing').length
  const queued = jobs.filter((j) => j.status === 'queued').length
  if (processing === 0 && queued === 0) return 'Queue is idle. Submit a video to get started.'
  const parts = []
  if (processing > 0) parts.push(`${processing} job${processing === 1 ? '' : 's'} running`)
  if (queued > 0) parts.push(`${queued} pending`)
  return parts.join(', ') + '.'
}

function EmptyState() {
  return (
    <div className="bg-card rounded-xl border border-white/[0.05] p-12 flex flex-col items-center justify-center text-center min-h-[400px]">
      <div className="w-16 h-16 rounded-full bg-secondary/60 flex items-center justify-center text-muted-foreground mb-4">
        <Inbox className="h-8 w-8" aria-hidden="true" />
      </div>
      <h2 className="text-lg font-semibold text-foreground mb-1">Queue is idle</h2>
      <p className="text-sm text-muted-foreground max-w-sm mb-6">
        No jobs are running or pending. Browse your library to generate subtitles for a film.
      </p>
      <Link
        to="/browse"
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[var(--action-accent)] text-white text-sm font-semibold hover:bg-[var(--action-accent)]/90 transition-colors"
      >
        <Plus className="h-4 w-4" aria-hidden="true" />
        New Task
      </Link>
    </div>
  )
}
