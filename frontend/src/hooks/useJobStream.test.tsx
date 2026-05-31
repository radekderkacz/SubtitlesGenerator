import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useJobStream } from './useJobStream'
import { useJobStore } from '@/store/jobStore'
import { makeJob } from '@/test-utils/mockJob'

type Listener = (ev: MessageEvent) => void

class FakeEventSource {
  // Match the real EventSource readyState constants — `useJobStream` reads
  // `EventSource.CLOSED` to distinguish terminal failures from transient ones.
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2

  url: string
  readyState = 0
  onopen: ((ev: Event) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  close = vi.fn(() => {
    this.readyState = 2
  })
  private readonly listeners = new Map<string, Set<Listener>>()

  constructor(url: string) {
    this.url = url
    instances.push(this)
  }

  addEventListener(type: string, handler: Listener): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set())
    this.listeners.get(type)!.add(handler)
  }

  removeEventListener(type: string, handler: Listener): void {
    this.listeners.get(type)?.delete(handler)
  }

  emit(type: string, data: string): void {
    const ev = new MessageEvent(type, { data })
    this.listeners.get(type)?.forEach((h) => h(ev))
  }

  triggerOpen(): void {
    this.onopen?.(new Event('open'))
  }

  triggerError(): void {
    this.onerror?.(new Event('error'))
  }

  setReadyState(state: number): void {
    this.readyState = state
  }
}

const instances: FakeEventSource[] = []

beforeEach(() => {
  instances.length = 0
  ;(globalThis as unknown as { EventSource: typeof EventSource }).EventSource =
    FakeEventSource as unknown as typeof EventSource
  useJobStore.setState({ jobs: [], isConnected: false, lastEventAt: null })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useJobStream', () => {
  it('opens an EventSource to /api/v1/jobs/stream on mount', () => {
    renderHook(() => useJobStream())
    expect(instances).toHaveLength(1)
    expect(instances[0].url).toBe('/api/v1/jobs/stream')
  })

  it('replaces jobs and flips isConnected on queue_state', () => {
    renderHook(() => useJobStream())
    const job = makeJob({ id: 'j1', status: 'queued' })

    act(() => {
      instances[0].emit(
        'queue_state',
        JSON.stringify({ jobs: [job], replayed_at: '2026-04-29T00:00:00Z' }),
      )
    })

    expect(useJobStore.getState().jobs).toHaveLength(1)
    expect(useJobStore.getState().jobs[0].id).toBe('j1')
    expect(useJobStore.getState().isConnected).toBe(true)
  })

  it('merges a job_update into the existing job, preserving non-payload fields', () => {
    renderHook(() => useJobStream())

    act(() => {
      instances[0].emit(
        'queue_state',
        JSON.stringify({
          jobs: [makeJob({ id: 'j1', file_path: '/media/Film.mkv', source: 'watch_folder' })],
          replayed_at: '2026-04-29T00:00:00Z',
        }),
      )
    })

    act(() => {
      instances[0].emit(
        'job_update',
        JSON.stringify({
          id: 'j1',
          status: 'processing',
          phase: 'transcribing',
          progress: 50,
          updated_at: '2026-04-29T01:00:00Z',
        }),
      )
    })

    const merged = useJobStore.getState().jobs[0]
    expect(merged.status).toBe('processing')
    expect(merged.phase).toBe('transcribing')
    expect(merged.progress).toBe(50)
    expect(merged.file_path).toBe('/media/Film.mkv')
    expect(merged.source).toBe('watch_folder')
  })

  it('appends a partial when job_update arrives for unknown ID', () => {
    renderHook(() => useJobStream())

    act(() => {
      instances[0].emit(
        'job_update',
        JSON.stringify({
          id: 'orphan',
          status: 'processing',
          phase: 'extracting',
          progress: 5,
          updated_at: '2026-04-29T00:00:00Z',
        }),
      )
    })

    const { jobs } = useJobStore.getState()
    expect(jobs).toHaveLength(1)
    expect(jobs[0].id).toBe('orphan')
  })

  it('logs and skips malformed JSON payloads without crashing', () => {
    const consoleErr = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderHook(() => useJobStream())

    act(() => {
      instances[0].emit('queue_state', '{not valid json')
    })

    expect(consoleErr).toHaveBeenCalled()
    expect(useJobStore.getState().jobs).toEqual([])
    expect(useJobStore.getState().isConnected).toBe(false)
  })

  it('flips isConnected=true on EventSource onopen', () => {
    renderHook(() => useJobStream())
    expect(useJobStore.getState().isConnected).toBe(false)

    act(() => {
      instances[0].triggerOpen()
    })

    expect(useJobStore.getState().isConnected).toBe(true)
  })

  it('keeps isConnected=true on transient onerror (readyState=CONNECTING)', () => {
    // Transient drops shouldn't flip the connected flag — the
    // staleness timer (`lastEventAt`) catches the gap, the browser auto-
    // reconnects. Only terminal CLOSED errors flip it.
    renderHook(() => useJobStream())
    act(() => {
      instances[0].triggerOpen()
    })
    expect(useJobStore.getState().isConnected).toBe(true)

    act(() => {
      instances[0].setReadyState(0) // CONNECTING
      instances[0].triggerError()
    })

    expect(useJobStore.getState().isConnected).toBe(true)
  })

  it('flips isConnected=false on terminal onerror (readyState=CLOSED)', () => {
    renderHook(() => useJobStream())
    act(() => {
      instances[0].triggerOpen()
    })
    expect(useJobStore.getState().isConnected).toBe(true)

    act(() => {
      instances[0].setReadyState(2) // CLOSED
      instances[0].triggerError()
    })

    expect(useJobStore.getState().isConnected).toBe(false)
  })

  it('marks lastEventAt on heartbeat events', () => {
    renderHook(() => useJobStream())
    expect(useJobStore.getState().lastEventAt).toBeNull()
    act(() => {
      instances[0].emit('heartbeat', '{}')
    })
    expect(useJobStore.getState().lastEventAt).not.toBeNull()
    expect(useJobStore.getState().isConnected).toBe(true)
  })

  it('marks lastEventAt on every event type (queue_state and job_update)', () => {
    renderHook(() => useJobStream())
    act(() => {
      instances[0].emit(
        'queue_state',
        JSON.stringify({ jobs: [], replayed_at: '2026-04-30T12:00:00Z' }),
      )
    })
    const after1 = useJobStore.getState().lastEventAt
    expect(after1).not.toBeNull()

    act(() => {
      instances[0].emit(
        'job_update',
        JSON.stringify({
          id: 'j1',
          status: 'processing',
          phase: 'transcribing',
          progress: 50,
          updated_at: '2026-04-30T12:00:01Z',
        }),
      )
    })
    expect(useJobStore.getState().lastEventAt).not.toBeNull()
  })

  it('closes the EventSource on unmount', () => {
    const { unmount } = renderHook(() => useJobStream())
    expect(instances[0].close).not.toHaveBeenCalled()
    unmount()
    expect(instances[0].close).toHaveBeenCalledTimes(1)
  })

  it('handles repeated mount/unmount cycles cleanly', () => {
    const first = renderHook(() => useJobStream())
    expect(instances).toHaveLength(1)
    first.unmount()
    expect(instances[0].close).toHaveBeenCalledTimes(1)

    const second = renderHook(() => useJobStream())
    expect(instances).toHaveLength(2)
    expect(instances[1].close).not.toHaveBeenCalled()
    second.unmount()
    expect(instances[1].close).toHaveBeenCalledTimes(1)
  })

  it('rejects malformed queue_state payloads (missing jobs array)', () => {
    const consoleErr = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderHook(() => useJobStream())

    act(() => {
      instances[0].emit('queue_state', JSON.stringify({ replayed_at: '2026-04-29T00:00:00Z' }))
    })

    expect(consoleErr).toHaveBeenCalled()
    expect(useJobStore.getState().jobs).toEqual([])
  })

  it('rejects job_update payloads with non-string id', () => {
    const consoleErr = vi.spyOn(console, 'error').mockImplementation(() => {})
    renderHook(() => useJobStream())

    act(() => {
      instances[0].emit('job_update', JSON.stringify({ id: 42, status: 'processing' }))
    })

    expect(consoleErr).toHaveBeenCalled()
    expect(useJobStore.getState().jobs).toEqual([])
  })

  it('raises a toast.error on the processing→failed transition', async () => {
    const { toast } = await import('sonner')
    const toastErr = vi.spyOn(toast, 'error').mockImplementation(() => 'toast-id' as any)
    renderHook(() => useJobStream())

    // Seed an active processing job
    act(() => {
      instances[0].emit(
        'queue_state',
        JSON.stringify({
          jobs: [
            makeJob({
              id: 'j-fail',
              file_path: '/media/films/Big Movie.mkv',
              status: 'processing',
              phase: 'transcribing',
            }),
          ],
          replayed_at: '2026-05-11T00:00:00Z',
        }),
      )
    })

    // Now transition to failed
    act(() => {
      instances[0].emit(
        'job_update',
        JSON.stringify({
          id: 'j-fail',
          status: 'failed',
          phase: 'transcribing',
          progress: 20,
          file_path: '/media/films/Big Movie.mkv',
          error_message: 'CUDA out of memory',
          updated_at: '2026-05-11T00:01:00Z',
        }),
      )
    })

    expect(toastErr).toHaveBeenCalledTimes(1)
    const [title, opts] = toastErr.mock.calls[0]
    expect(title).toBe('Big Movie.mkv failed')
    expect((opts as { description?: string }).description).toBe('CUDA out of memory')
    expect((opts as { action?: { label: string } }).action?.label).toBe('Open History')
    toastErr.mockRestore()
  })

  it('does not toast when a queue_state replay carries an already-failed job', async () => {
    const { toast } = await import('sonner')
    const toastErr = vi.spyOn(toast, 'error').mockImplementation(() => 'toast-id' as any)
    renderHook(() => useJobStream())

    act(() => {
      instances[0].emit(
        'queue_state',
        JSON.stringify({
          jobs: [makeJob({ id: 'j-stale', status: 'failed' })],
          replayed_at: '2026-05-11T00:00:00Z',
        }),
      )
    })
    // A subsequent job_update for the same already-failed row should be a no-op
    act(() => {
      instances[0].emit(
        'job_update',
        JSON.stringify({ id: 'j-stale', status: 'failed', progress: 20 }),
      )
    })

    expect(toastErr).not.toHaveBeenCalled()
    toastErr.mockRestore()
  })
})
