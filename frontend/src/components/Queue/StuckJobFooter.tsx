import { useSyncExternalStore } from 'react'
import { AlertTriangle } from 'lucide-react'
import type { Job } from '@/types/api'

const STUCK_THRESHOLD_MS = 30 * 60 * 1000

type Props = Readonly<{
  job: Job
}>

function subscribeToMinuteTicks(callback: () => void): () => void {
  const id = setInterval(callback, 60_000)
  return () => clearInterval(id)
}

export default function StuckJobFooter({ job }: Props) {
  // Use useSyncExternalStore so render stays pure: Date.now() lives in the
  // snapshot function (allowed by the API), and a 1-minute external ticker
  // forces React to re-read it without triggering setState-in-effect rules.
  const isStuck = useSyncExternalStore(
    subscribeToMinuteTicks,
    () => {
      if (job.status !== 'processing') return false
      const stuckSince = Date.parse(job.updated_at)
      return Number.isFinite(stuckSince) && Date.now() - stuckSince > STUCK_THRESHOLD_MS
    },
    () => false, // SSR / initial-render snapshot
  )

  if (!isStuck) return null

  return (
    <footer className="mt-4 text-sm">
      <button
        type="button"
        className="inline-flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors"
      >
        <AlertTriangle
          className="h-4 w-4"
          style={{ color: 'var(--phase-failed)' }}
          aria-hidden="true"
        />
        Job appears stuck? Open the full log
      </button>
    </footer>
  )
}
