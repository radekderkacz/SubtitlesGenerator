import { useMemo, useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useJobStore } from '@/store/jobStore'
import { isActive, type Job } from '@/types/api'
import JobRow from './JobRow'
import QueueListEmpty from './QueueListEmpty'
import QueueListSkeleton from './QueueListSkeleton'

type Props = Readonly<{
  selectedId: string | null
  onSelect: (id: string) => void
}>

const ROW_HEIGHT = 110
const VIRTUALIZER_OVERSCAN = 4

// Active rows (processing/queued) sort oldest-first so the currently-running
// job anchors at the top and the next FIFO pick sits directly below it —
// matches the actual worker execution order. Terminal rows (completed/failed/
// cancelled) sort newest-first under that, the standard "recent history"
// convention. Stable comparator: ties fall back to id so order doesn't churn.
function compareJobs(a: Job, b: Job): number {
  const aActive = isActive(a.status)
  const bActive = isActive(b.status)
  if (aActive !== bActive) return aActive ? -1 : 1
  const direction = aActive ? 1 : -1
  const cmp = a.created_at.localeCompare(b.created_at)
  if (cmp !== 0) return direction * cmp
  return a.id.localeCompare(b.id)
}

export default function QueueList({ selectedId, onSelect }: Props) {
  const jobs = useJobStore((s) => s.jobs)
  const isConnected = useJobStore((s) => s.isConnected)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const sortedJobs = useMemo(() => [...jobs].sort(compareJobs), [jobs])

  const virtualizer = useVirtualizer({
    count: sortedJobs.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: VIRTUALIZER_OVERSCAN,
  })

  if (!isConnected) return <QueueListSkeleton />
  if (sortedJobs.length === 0) return <QueueListEmpty />

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto" data-testid="queue-list-scroll">
      <div
        style={{
          height: virtualizer.getTotalSize(),
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const job = sortedJobs[virtualRow.index]
          return (
            <div
              key={job.id}
              data-index={virtualRow.index}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              <JobRow job={job} selected={job.id === selectedId} onSelect={onSelect} />
            </div>
          )
        })}
      </div>
    </div>
  )
}
