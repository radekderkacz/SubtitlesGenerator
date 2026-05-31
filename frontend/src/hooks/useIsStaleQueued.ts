import { useSyncExternalStore } from 'react'
import { JOB_STATUS, type Job } from '@/types/api'

/**
 * Backend threshold (job_service.STUCK_QUEUED_THRESHOLD_SECONDS). A queued
 * job older than this is treated as an orphan — Celery dispatch was lost
 * and the row needs the recovery-retry path (incident 2026-05-15). Kept
 * here as a UI-side mirror so the Retry affordance reveals at roughly the
 * same moment the backend would accept the retry.
 */
const STUCK_QUEUED_THRESHOLD_MS = 30_000

// One ticker for all subscribers — 2 Hz is enough to flip the badge within
// ~500 ms of crossing the threshold, and 16× cheaper than the 1 Hz per-row
// timers we already have elsewhere.
let listeners = new Set<() => void>()
let intervalId: ReturnType<typeof setInterval> | null = null

function subscribe(cb: () => void): () => void {
  listeners.add(cb)
  intervalId ??= setInterval(() => {
    for (const l of listeners) l()
  }, 500)
  return () => {
    listeners.delete(cb)
    if (listeners.size === 0 && intervalId !== null) {
      clearInterval(intervalId)
      intervalId = null
    }
  }
}

/**
 * True when ``job.status === 'queued'`` and the row hasn't been touched
 * for at least 30 seconds — the orphan-queued recovery signal. Static
 * ``false`` for any non-queued job so the hook is safe to call from every
 * JobRow regardless of status.
 */
export function useIsStaleQueued(job: Job): boolean {
  return useSyncExternalStore(
    subscribe,
    () => {
      if (job.status !== JOB_STATUS.QUEUED) return false
      const since = Date.parse(job.updated_at)
      if (!Number.isFinite(since)) return false
      return Date.now() - since >= STUCK_QUEUED_THRESHOLD_MS
    },
    () => false, // SSR-only snapshot (no JSDOM SSR in this project), unused at runtime
  )
}
