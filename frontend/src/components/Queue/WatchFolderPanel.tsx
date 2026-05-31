import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, Eye, FolderOpen, Inbox } from 'lucide-react'
import { Link } from 'react-router'
import { useJobStore } from '@/store/jobStore'
import { getWatchFolderActivity } from '@/lib/api'
import { isActive } from '@/types/api'
import { basename } from '@/lib/utils'

type Props = Readonly<Record<string, never>>

const REFRESH_INTERVAL_MS = 30_000

export default function WatchFolderPanel(_props: Props) {
  // Collapsed by default when there's already active queue activity
  // User can override via the toggle.
  const activeCount = useJobStore((s) => s.jobs.filter((j) => isActive(j.status)).length)
  const [expanded, setExpanded] = useState(false)

  const query = useQuery({
    queryKey: ['watch-folders', 'activity'],
    queryFn: getWatchFolderActivity,
    refetchInterval: REFRESH_INTERVAL_MS,
  })

  const hasActivity =
    query.data !== undefined &&
    (query.data.auto_enqueued_count_24h > 0 ||
      query.data.recent_auto_jobs.length > 0 ||
      query.data.recent_skipped.length > 0)

  // Default-expanded when the queue is idle and we have activity to surface.
  const isExpanded = expanded || (activeCount === 0 && hasActivity)

  return (
    <section
      aria-label="Watch folder activity"
      className="border-t border-border bg-card/40"
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={isExpanded}
        className="w-full flex items-center justify-between px-4 py-3 text-xs font-semibold text-muted-foreground hover:text-foreground transition-colors"
      >
        <span className="flex items-center gap-2">
          <Eye className="h-3.5 w-3.5" aria-hidden="true" />
          Watch Folder Activity
          {query.data !== undefined && query.data.auto_enqueued_count_24h > 0 && (
            <span className="ml-1 inline-flex items-center justify-center px-1.5 py-0.5 rounded-full bg-primary/10 text-primary text-[10px] font-bold">
              {query.data.auto_enqueued_count_24h}
            </span>
          )}
        </span>
        {isExpanded ? (
          <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
        )}
      </button>
      {isExpanded && <PanelBody data={query.data} isLoading={query.isLoading} />}
    </section>
  )
}

type BodyProps = Readonly<{
  data: import('@/types/api').WatchFolderActivity | undefined
  isLoading: boolean
}>

function PanelBody({ data, isLoading }: BodyProps) {
  if (isLoading || data === undefined) {
    return <p className="px-4 pb-3 text-[11px] italic text-muted-foreground">Loading…</p>
  }
  const empty =
    data.auto_enqueued_count_24h === 0 &&
    data.recent_auto_jobs.length === 0 &&
    data.recent_skipped.length === 0
  if (empty) {
    return (
      <p className="px-4 pb-3 text-[11px] italic text-muted-foreground">
        No files detected in the last 24 hours.
      </p>
    )
  }
  return (
    <div className="px-4 pb-3 space-y-3 text-[11px] text-muted-foreground">
      {data.monitored_paths.length > 0 && (
        <div className="flex items-start gap-2">
          <FolderOpen className="h-3 w-3 mt-0.5 shrink-0" aria-hidden="true" />
          <span className="font-mono truncate" title={data.monitored_paths.join(', ')}>
            {data.monitored_paths.join(', ')}
          </span>
        </div>
      )}
      {data.recent_auto_jobs.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider mb-1">Recently auto-enqueued</p>
          <ul className="space-y-1 list-none">
            {data.recent_auto_jobs.slice(0, 10).map((j) => (
              <li key={j.id} className="flex items-center gap-2">
                <Inbox
                  className="h-3 w-3 shrink-0"
                  style={{ color: 'var(--phase-auto)' }}
                  aria-hidden="true"
                />
                <Link
                  to={`/jobs/${j.id}`}
                  className="font-mono text-foreground/80 hover:text-foreground truncate"
                  title={j.file_path}
                >
                  {basename(j.file_path)}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      {data.recent_skipped.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider mb-1">Skipped (SRT exists)</p>
          <ul className="space-y-1 list-none">
            {data.recent_skipped.slice(0, 10).map((s) => (
              <li key={`${s.path}-${s.skipped_at}`} className="flex items-center gap-2 opacity-70">
                <Eye className="h-3 w-3 shrink-0" aria-hidden="true" />
                <span className="font-mono truncate" title={s.path}>
                  {basename(s.path)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
