import { Link } from 'react-router'
import { AudioLines, GripVertical, Inbox } from 'lucide-react'
import { basename } from '@/lib/utils'
import type { Job } from '@/types/api'

type Props = Readonly<{
  /** Other in-flight jobs (processing) besides the focused one. */
  secondary: ReadonlyArray<Job>
  /** Queued jobs waiting their turn. */
  pending: ReadonlyArray<Job>
}>

export default function UpNextRail({ secondary, pending }: Props) {
  return (
    <aside className="flex flex-col gap-6 min-h-0">
      {secondary.map((job) => (
        <SecondaryActiveCard key={job.id} job={job} />
      ))}

      <section
        aria-label="Up next"
        className="bg-card rounded-xl shadow-[0_10px_40px_-10px_rgba(0,0,0,0.5)] border border-white/[0.05] flex-1 flex flex-col overflow-hidden"
      >
        <header className="p-4 border-b border-white/[0.05] flex justify-between items-center">
          <h3 className="text-sm font-semibold text-foreground">Up Next</h3>
          <span className="px-2 py-0.5 bg-background rounded text-muted-foreground text-[11px] font-semibold uppercase tracking-wider">
            {pending.length} item{pending.length === 1 ? '' : 's'}
          </span>
        </header>
        <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-3">
          {pending.length === 0 ? (
            <output className="flex-1 flex flex-col items-center justify-center text-center py-6 gap-3">
              <Inbox className="h-7 w-7 text-muted-foreground" aria-hidden="true" />
              <p className="text-xs text-muted-foreground">
                Queue is clear — no pending jobs.
              </p>
            </output>
          ) : (
            pending.map((job, i) => <PendingItem key={job.id} job={job} index={i + 1} />)
          )}
        </div>
      </section>
    </aside>
  )
}

type SecondaryProps = Readonly<{ job: Job }>

function SecondaryActiveCard({ job }: SecondaryProps) {
  const filename = basename(job.file_path)
  return (
    <Link
      to={`/jobs/${job.id}`}
      className="bg-card rounded-xl p-4 shadow-[0_10px_40px_-10px_rgba(0,0,0,0.5)] border border-white/[0.05] flex flex-col gap-3 hover:border-white/15 transition-colors"
      aria-label={`Secondary processing job: ${filename}`}
    >
      <div className="flex items-start gap-3">
        <AudioLines className="h-5 w-5 text-[var(--primary-container)] shrink-0 mt-0.5" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-semibold text-foreground truncate" title={filename}>
            {filename}
          </h4>
          <p className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold mt-0.5">
            {job.phase ?? 'Processing'}
          </p>
        </div>
      </div>
      <div className="h-1 w-full bg-background rounded-full overflow-hidden border border-white/5">
        <div
          className="h-full bg-[var(--action-accent)] shadow-[0_0_10px_rgba(59,130,246,0.8)] transition-all"
          style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }}
        />
      </div>
    </Link>
  )
}

type PendingProps = Readonly<{ job: Job; index: number }>

function PendingItem({ job, index }: PendingProps) {
  const filename = basename(job.file_path)
  return (
    <Link
      to={`/jobs/${job.id}`}
      className="flex items-center justify-between group hover:bg-white/[0.02] rounded -mx-2 px-2 py-1 transition-colors"
    >
      <div className="flex items-center gap-3 min-w-0">
        <span className="font-mono text-[11px] text-muted-foreground/60 w-5 text-right shrink-0">
          {index}
        </span>
        <div className="min-w-0">
          <h4 className="text-sm text-foreground truncate" title={filename}>
            {filename}
          </h4>
          {job.target_language && (
            <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">
              {job.target_language.toUpperCase()} (SRT)
            </span>
          )}
        </div>
      </div>
      <GripVertical className="h-4 w-4 text-muted-foreground/40 group-hover:text-foreground shrink-0" aria-hidden="true" />
    </Link>
  )
}
