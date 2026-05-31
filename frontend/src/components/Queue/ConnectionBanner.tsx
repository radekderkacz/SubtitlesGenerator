import { AlertCircle, RotateCw } from 'lucide-react'
import { useShowStaleBanner } from '@/hooks/useConnectionStatus'

/** Hard-reload the page. Pulled out so tests can stub it. Uses
 * `globalThis` instead of `window` for the same runtime effect plus
 * lint-clean (sonarjs/typescript: "Prefer globalThis over window"). */
function reloadPage() {
  globalThis.location.reload()
}

export default function ConnectionBanner() {
  const showBanner = useShowStaleBanner()
  if (!showBanner) return null

  return (
    <output
      data-testid="connection-banner"
      aria-live="polite"
      className="block border-b border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm text-amber-200"
    >
      <div className="flex items-center justify-between gap-3 max-w-[1280px] mx-auto">
        <div className="flex items-center gap-2 min-w-0">
          <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="truncate">
            Live updates have stopped — the page may be showing stale state.
            Auto-reconnecting; if it doesn&apos;t recover, refresh.
          </span>
        </div>
        <button
          type="button"
          onClick={reloadPage}
          aria-label="Refresh the page to reconnect"
          className="shrink-0 flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/15 px-2.5 py-1 text-xs font-semibold uppercase tracking-wider text-amber-100 hover:bg-amber-500/25 hover:text-amber-50 focus:outline-none focus:ring-2 focus:ring-amber-400/60"
        >
          <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />
          Refresh
        </button>
      </div>
    </output>
  )
}
