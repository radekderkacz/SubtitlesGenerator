import { useState } from 'react'
import { RotateCw, X } from 'lucide-react'
import ColorPillBadge from './ColorPillBadge'
import PhaseBadge from './PhaseBadge'
import ConfirmDialog from '@/components/ConfirmDialog/ConfirmDialog'
import RetryDialog from '@/components/RetryDialog/RetryDialog'
import { cancelOrRemoveJob, retryJob } from '@/lib/api'
import { withApiToast } from '@/lib/apiToast'
import { useElapsedTime } from '@/hooks/useElapsedTime'
import { useIsStaleQueued } from '@/hooks/useIsStaleQueued'
import { basename, dirname } from '@/lib/utils'
import { isActive, JOB_STATUS, type Job } from '@/types/api'

type Props = Readonly<{
  job: Job
  selected: boolean
  onSelect: (id: string) => void
}>

function buildConfirmCopy(job: Job, filename: string) {
  if (job.status === JOB_STATUS.QUEUED) {
    return {
      title: `Remove ${filename}?`,
      description: 'The job will be removed from the queue before it starts.',
      confirm: 'Remove',
    }
  }
  return {
    title: `Cancel ${filename}?`,
    description: 'The job cannot be resumed once cancelled.',
    confirm: 'Cancel Job',
  }
}

export default function JobRow({ job, selected, onSelect }: Props) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [retryOpen, setRetryOpen] = useState(false)
  const filename = basename(job.file_path)
  const dir = dirname(job.file_path)
  const active = isActive(job.status)
  const elapsedEnd = active ? null : (job.completed_at ?? job.updated_at)
  const elapsed = useElapsedTime(job.created_at, elapsedEnd)
  const showProgressBar =
    job.status === JOB_STATUS.PROCESSING || job.status === JOB_STATUS.COMPLETED
  const progressClamped = Math.min(100, Math.max(0, job.progress))
  // A cancel control is shown on every active row, not only the selected
  // one, regardless of selection.
  const showCancel = active
  // A queued job that's been sitting untouched for 30+s is an orphan
  // (incident 2026-05-15: API created the DB row but Celery dispatch was
  // lost). Surface a retry button so the user can recover without
  // intervention. Cancel + retry both show in that case — the user picks.
  const isStaleQueued = useIsStaleQueued(job)
  const showRetry = job.status === JOB_STATUS.FAILED || isStaleQueued

  const handleConfirm = () =>
    withApiToast(() => cancelOrRemoveJob(job.id), {
      successMessage:
        job.status === JOB_STATUS.QUEUED
          ? `Removed ${filename}`
          : `Cancelled ${filename}`,
    })

  const handleRetry = () =>
    withApiToast(() => retryJob(job.id), {
      successMessage: `Retrying ${filename}`,
    })

  // The select region is a real <button>; the cancel control is a sibling
  // <button> positioned absolutely on top of the select button. Keeping them
  // as siblings (not nested) avoids the HTML invalid-nested-interactive trap
  // and lets each get standard keyboard focus / ARIA semantics for free.
  const selectClasses =
    'block w-full text-left p-4 cursor-pointer transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-primary/50'
  const selectVariant = selected
    ? 'bg-secondary border-l-2 border-primary'
    : 'border-b border-secondary/50 hover:bg-card'
  const copy = buildConfirmCopy(job, filename)

  return (
    <>
      <div className="relative">
        <button
          type="button"
          aria-pressed={selected}
          onClick={() => onSelect(job.id)}
          className={`${selectClasses} ${selectVariant}`}
        >
          <div className="flex justify-between items-start mb-1 gap-2">
            <span
              className="text-sm font-medium truncate flex-1 text-foreground"
              title={job.file_path}
            >
              {filename}
            </span>
            {/* placeholder keeps the spacing identical whether or not the
                cancel/retry icon button is rendered; the real button sits
                absolutely outside */}
            {(showCancel || showRetry) && (
              <span aria-hidden="true" className="w-4 h-4 shrink-0" />
            )}
          </div>
          {dir && (
            <div className="font-mono text-[10px] text-muted-foreground mb-3 truncate">
              {dir}
            </div>
          )}
          <div className="flex items-center justify-between gap-2 mb-2">
            <div className="flex items-center gap-2 min-w-0">
              <PhaseBadge status={job.status} phase={job.phase} />
              {job.source === 'watch_folder' && (
                <ColorPillBadge
                  label="Auto"
                  cssVar="--phase-auto"
                  ariaLabel="Source: auto-detected via watch folder"
                />
              )}
            </div>
            <span className="text-[10px] font-mono text-muted-foreground shrink-0">
              {elapsed}
            </span>
          </div>
          {showProgressBar && (
            <progress
              value={progressClamped}
              max={100}
              aria-label="Job progress"
              className="job-progress w-full h-1 rounded-full overflow-hidden bg-border block appearance-none [&::-webkit-progress-bar]:bg-border [&::-webkit-progress-value]:bg-primary [&::-webkit-progress-value]:transition-all [&::-webkit-progress-value]:duration-300 [&::-moz-progress-bar]:bg-primary"
            />
          )}
        </button>
        {/* Cancel and retry can both appear on a stale-queued row. When
            they do, retry sits at top-3 right-3 and cancel shifts to
            right-9 so the two stay flush along the top edge. */}
        {showCancel && (
          <button
            type="button"
            aria-label={`${job.status === JOB_STATUS.QUEUED ? 'Remove' : 'Cancel'} ${filename}`}
            onClick={() => setConfirmOpen(true)}
            className={`absolute top-3 ${showRetry ? 'right-9' : 'right-3'} text-muted-foreground hover:text-destructive shrink-0 rounded p-0.5 focus:outline-none focus:ring-2 focus:ring-destructive/50`}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        )}
        {showRetry && (
          <button
            type="button"
            aria-label={`Retry ${filename}`}
            onClick={() => setRetryOpen(true)}
            // Yellow tint when this is an orphan-recovery retry (vs the
            // standard "failed job retry" affordance) — same icon and
            // dialog, but the colour cue distinguishes the cause.
            className={`absolute top-3 right-3 ${isStaleQueued ? 'text-yellow-500/80 hover:text-yellow-400' : 'text-muted-foreground hover:text-primary'} shrink-0 rounded p-0.5 focus:outline-none focus:ring-2 focus:ring-primary/50`}
            title={isStaleQueued ? 'Job has been queued too long — retry?' : undefined}
          >
            <RotateCw className="h-4 w-4" aria-hidden="true" />
          </button>
        )}
      </div>
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={copy.title}
        description={copy.description}
        confirmLabel={copy.confirm}
        onConfirm={handleConfirm}
        destructive
      />
      {showRetry && (
        <RetryDialog
          open={retryOpen}
          onOpenChange={setRetryOpen}
          filename={filename}
          onRetry={handleRetry}
        />
      )}
    </>
  )
}
