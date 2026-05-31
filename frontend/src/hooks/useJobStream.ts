import { useEffect } from 'react'
import { toast } from 'sonner'
import { useJobStore } from '@/store/jobStore'
import { basename } from '@/lib/utils'
import type { JobUpdatePayload, QueueStatePayload } from '@/types/api'

const SSE_PATH = '/api/v1/jobs/stream'

const SSE_EVENTS = {
  QUEUE_STATE: 'queue_state',
  JOB_UPDATE: 'job_update',
  HEARTBEAT: 'heartbeat',
} as const

function safeParse<T>(raw: string): T | null {
  try {
    return JSON.parse(raw) as T
  } catch (e) {
    console.error('Malformed SSE payload', e)
    return null
  }
}

function notifyOnFailure(
  previousStatus: string | undefined,
  update: JobUpdatePayload,
): void {
  // Only fire on a true transition into `failed` — not on every replay of an
  // already-failed row from a queue_state burst or a duplicate SSE delivery.
  if (update.status !== 'failed') return
  if (previousStatus === 'failed') return

  const filename = update.file_path
    ? basename(update.file_path)
    : `job ${update.id.slice(0, 8)}`
  const detail = update.error_message
    ? update.error_message.split('\n')[0].slice(0, 140)
    : null

  toast.error(`${filename} failed`, {
    description: detail ?? 'See History for the full error message.',
    duration: 15000, // sticky-ish — long jobs mean the user may have walked away
    action: {
      label: 'Open History',
      onClick: () => {
        globalThis.location.assign('/history')
      },
    },
  })
}

export function useJobStream() {
  const setJobs = useJobStore((s) => s.setJobs)
  const applyJobUpdate = useJobStore((s) => s.applyJobUpdate)
  const setConnected = useJobStore((s) => s.setConnected)
  const markEventReceived = useJobStore((s) => s.markEventReceived)

  useEffect(() => {
    const es = new EventSource(SSE_PATH)

    const onQueueState = (ev: MessageEvent) => {
      const payload = safeParse<QueueStatePayload>(ev.data)
      if (!payload || !Array.isArray(payload.jobs)) {
        console.error('Malformed queue_state payload', payload)
        return
      }
      setJobs(payload.jobs)
      // Buffering proxies (nginx proxy_buffering=on, Cloudflare) can deliver
      // the first SSE event before `onopen` fires — set connected here too.
      setConnected(true)
      markEventReceived()
    }
    const onJobUpdate = (ev: MessageEvent) => {
      const payload = safeParse<JobUpdatePayload>(ev.data)
      if (!payload || typeof payload.id !== 'string') {
        console.error('Malformed job_update payload', payload)
        return
      }
      // Look up the prior status BEFORE we apply, so we can detect the
      // `processing → failed` transition and raise a toast even when the
      // failed row has already disappeared from the QueuePage filter.
      const prev = useJobStore.getState().jobs.find((j) => j.id === payload.id)
      notifyOnFailure(prev?.status, payload)
      applyJobUpdate(payload)
      setConnected(true)
      markEventReceived()
    }
    const onHeartbeat = () => {
      // No payload to validate — the server uses heartbeat purely for liveness.
      setConnected(true)
      markEventReceived()
    }
    const onOpen = () => {
      setConnected(true)
      markEventReceived()
    }
    const onError = () => {
      // Only flip the connected flag for terminal closes. Transient errors
      // (CONNECTING) should let the staleness timer catch the gap; the browser
      // re-establishes the connection automatically.
      if (es.readyState === EventSource.CLOSED) {
        setConnected(false)
      }
    }

    es.addEventListener(SSE_EVENTS.QUEUE_STATE, onQueueState as EventListener)
    es.addEventListener(SSE_EVENTS.JOB_UPDATE, onJobUpdate as EventListener)
    es.addEventListener(SSE_EVENTS.HEARTBEAT, onHeartbeat as EventListener)
    es.onopen = onOpen
    es.onerror = onError

    return () => {
      es.removeEventListener(SSE_EVENTS.QUEUE_STATE, onQueueState as EventListener)
      es.removeEventListener(SSE_EVENTS.JOB_UPDATE, onJobUpdate as EventListener)
      es.removeEventListener(SSE_EVENTS.HEARTBEAT, onHeartbeat as EventListener)
      es.close()
    }
  }, [setJobs, applyJobUpdate, setConnected, markEventReceived])
}
