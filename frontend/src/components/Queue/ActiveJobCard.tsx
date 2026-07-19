import { useState } from 'react'
import { Film, X } from 'lucide-react'
import HorizontalPhaseTimeline from './HorizontalPhaseTimeline'
import LiveLogPane from './LiveLogPane'
import ConfirmDialog from '@/components/ConfirmDialog/ConfirmDialog'
import { cancelOrRemoveJob } from '@/lib/api'
import { withApiToast } from '@/lib/apiToast'
import { useElapsedTime } from '@/hooks/useElapsedTime'
import { basename } from '@/lib/utils'
import { isActive, type Job } from '@/types/api'
import { isAutoRetryJob } from '@/lib/jobSource'

type Props = Readonly<{
  job: Job
}>

const PHASE_LABEL: Record<string, string> = {
  extracting: 'Extracting Audio',
  transcribing: 'Transcribing',
  translating: 'Translating',
  writing: 'Finalizing',
  done: 'Completed',
}

function phaseLabel(job: Job): string {
  if (job.status === 'queued') return 'Waiting in queue'
  if (job.phase) return PHASE_LABEL[job.phase] ?? 'Processing'
  return 'Processing'
}

export default function ActiveJobCard({ job }: Props) {
  const [confirmOpen, setConfirmOpen] = useState(false)
  const filename = basename(job.file_path)
  const elapsed = useElapsedTime(job.created_at, isActive(job.status) ? null : job.updated_at)

  const handleCancel = () =>
    withApiToast(() => cancelOrRemoveJob(job.id), {
      successMessage: `Cancelled ${filename}`,
    })

  return (
    <article
      aria-label={`Active job: ${filename}`}
      className="xl:col-span-2 bg-card rounded-xl p-6 shadow-[0_10px_40px_-10px_rgba(0,0,0,0.5)] flex flex-col gap-6 border border-white/[0.05]"
    >
      <header className="flex justify-between items-start">
        <div className="flex items-center gap-4 min-w-0">
          <div className="w-12 h-12 rounded-lg bg-background flex items-center justify-center text-[var(--primary-container)] border border-white/[0.05] shrink-0">
            <Film className="h-6 w-6" aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-foreground truncate" title={job.file_path}>
              {filename}
            </h3>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              {job.target_language && (
                <span className="px-2 py-[2px] rounded text-[11px] uppercase tracking-wider font-semibold bg-[#1e293b] text-[#94a3b8]">
                  {job.target_language.toUpperCase()} (SRT)
                </span>
              )}
              {job.model_size && (
                <span className="px-2 py-[2px] rounded text-[11px] uppercase tracking-wider font-semibold bg-[#1e293b] text-[#94a3b8]">
                  {job.model_size}
                </span>
              )}
              <span className="text-[11px] text-muted-foreground font-mono">{phaseLabel(job)}</span>
            </div>
          </div>
        </div>
        {isActive(job.status) && (
          <button
            type="button"
            onClick={() => setConfirmOpen(true)}
            aria-label={`Cancel ${filename}`}
            className="text-muted-foreground hover:text-destructive transition-colors p-2"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        )}
      </header>

      <HorizontalPhaseTimeline status={job.status} phase={job.phase} />

      <div>
        <div className="flex justify-between text-[11px] uppercase tracking-wider font-semibold text-muted-foreground mb-1">
          <span>Progress</span>
          <span className="text-[var(--action-accent)]">{job.progress}%</span>
        </div>
        <div className="h-1 w-full bg-background rounded-full overflow-hidden border border-white/5">
          <div
            className="h-full bg-[var(--action-accent)] shadow-[0_0_10px_rgba(59,130,246,0.8)] transition-all duration-500"
            style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }}
          />
        </div>
        <div className="flex justify-between text-[11px] text-muted-foreground mt-1">
          <span>Elapsed: <span className="font-mono text-foreground">{elapsed}</span></span>
          {job.source === 'watch_folder' && (
            <span className="text-[var(--phase-auto)] font-semibold uppercase tracking-wider">Auto</span>
          )}
          {isAutoRetryJob(job) && (
            <span className="text-[var(--phase-auto)] font-semibold uppercase tracking-wider">Auto-retry</span>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-[200px]">
        <LiveLogPane job={job} />
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`Cancel ${filename}?`}
        description="The job cannot be resumed once cancelled."
        confirmLabel="Cancel Job"
        onConfirm={handleCancel}
        destructive
      />
    </article>
  )
}
