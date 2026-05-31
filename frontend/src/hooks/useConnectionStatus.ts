import { useSyncExternalStore } from 'react'
import { useJobStore } from '@/store/jobStore'

export type ConnectionStatus = 'green' | 'amber' | 'red'

export const STALE_AMBER_MS = 5_000
export const STALE_RED_MS = 30_000
export const STALE_BANNER_MS = 60_000

const TICK_INTERVAL_MS = 1_000

function subscribeToTicker(callback: () => void): () => void {
  const id = setInterval(callback, TICK_INTERVAL_MS)
  return () => clearInterval(id)
}

function deriveStatus(): ConnectionStatus {
  const { isConnected, lastEventAt } = useJobStore.getState()
  if (!isConnected) return 'red'
  if (lastEventAt === null) return 'amber'
  const age = Date.now() - lastEventAt
  if (age < STALE_AMBER_MS) return 'green'
  if (age < STALE_RED_MS) return 'amber'
  return 'red'
}

/**
 * Returns the SSE connection indicator color, derived from `lastEventAt`
 * staleness + `isConnected`. Re-evaluates every 1 second so the indicator
 * ages without depending on external SSE events arriving.
 *
 * `useSyncExternalStore` keeps render pure (no Date.now() or store reads
 * during the render phase) while still letting components subscribe to a
 * value that changes over wall-clock time.
 */
export function useConnectionStatus(): ConnectionStatus {
  return useSyncExternalStore(
    subscribeToTicker,
    deriveStatus,
    () => 'amber' as ConnectionStatus, // SSR / first paint before any event
  )
}

/** Returns true when the connection has been stale long enough to warrant
 * a persistent banner over the queue list. */
export function useShowStaleBanner(): boolean {
  return useSyncExternalStore(
    subscribeToTicker,
    () => {
      const { isConnected, lastEventAt } = useJobStore.getState()
      if (!isConnected) return true
      if (lastEventAt === null) return false
      return Date.now() - lastEventAt >= STALE_BANNER_MS
    },
    () => false,
  )
}
