import { useState } from 'react'
import { Cog, X } from 'lucide-react'
import { useJobStore } from '@/store/jobStore'
import { isActive } from '@/types/api'

const ACTIVE_COUNT_SELECTOR = (s: { jobs: ReadonlyArray<{ status: string }> }) =>
  s.jobs.filter((j) => isActive(j.status as never)).length

export default function BackgroundProcessingToast() {
  const [dismissed, setDismissed] = useState(false)
  const activeCount = useJobStore(ACTIVE_COUNT_SELECTOR)

  if (dismissed || activeCount === 0) return null

  return (
    <output
      aria-live="polite"
      className="fixed bottom-6 right-6 z-50 block bg-card border border-border rounded-xl shadow-2xl p-4 flex items-center gap-4 max-w-sm"
    >
      <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-primary shrink-0">
        <Cog className="h-5 w-5 animate-spin" style={{ animationDuration: '4s' }} aria-hidden="true" />
      </div>
      <div className="flex-1 min-w-0">
        <h5 className="text-sm font-bold text-foreground">Background Processing</h5>
        <p className="text-xs text-muted-foreground mt-0.5">
          {activeCount} active task{activeCount === 1 ? '' : 's'} in pipeline
        </p>
      </div>
      <button
        type="button"
        aria-label="Dismiss notice"
        onClick={() => setDismissed(true)}
        className="ml-2 p-1 hover:bg-secondary rounded transition-colors text-muted-foreground hover:text-foreground"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </output>
  )
}
