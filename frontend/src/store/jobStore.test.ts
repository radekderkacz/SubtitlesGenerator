import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useJobStore } from './jobStore'
import { makeJob } from '@/test-utils/mockJob'
import type { JobUpdatePayload } from '@/types/api'

describe('useJobStore', () => {
  beforeEach(() => {
    useJobStore.setState({ jobs: [], isConnected: false, lastEventAt: null })
  })

  describe('setJobs', () => {
    it('replaces the entire job array', () => {
      useJobStore.getState().setJobs([makeJob({ id: 'j1' })])
      useJobStore.getState().setJobs([makeJob({ id: 'j2' }), makeJob({ id: 'j3' })])

      const { jobs } = useJobStore.getState()
      expect(jobs.map((j) => j.id)).toEqual(['j2', 'j3'])
    })

    it('accepts an empty array (empty queue)', () => {
      useJobStore.getState().setJobs([makeJob({ id: 'j1' })])
      useJobStore.getState().setJobs([])
      expect(useJobStore.getState().jobs).toEqual([])
    })
  })

  describe('applyJobUpdate', () => {
    it('merges the partial update into the existing job, preserving non-payload fields', () => {
      const existing = makeJob({
        id: 'j1',
        status: 'queued',
        phase: null,
        progress: 0,
        file_path: '/media/Film.mkv',
        target_language: 'en',
        model_size: 'large-v3',
        source: 'watch_folder',
      })
      useJobStore.getState().setJobs([existing])

      const update: JobUpdatePayload = {
        id: 'j1',
        status: 'processing',
        phase: 'transcribing',
        progress: 42,
        updated_at: '2026-04-29T01:00:00Z',
      }
      useJobStore.getState().applyJobUpdate(update)

      const merged = useJobStore.getState().jobs[0]
      expect(merged.status).toBe('processing')
      expect(merged.phase).toBe('transcribing')
      expect(merged.progress).toBe(42)
      expect(merged.updated_at).toBe('2026-04-29T01:00:00Z')
      // Non-payload fields preserved from queue_state
      expect(merged.file_path).toBe('/media/Film.mkv')
      expect(merged.target_language).toBe('en')
      expect(merged.model_size).toBe('large-v3')
      expect(merged.source).toBe('watch_folder')
    })

    it('appends a partial when the ID is unknown (queue_state will fill in later)', () => {
      const update: JobUpdatePayload = {
        id: 'unknown',
        status: 'processing',
        phase: 'extracting',
        progress: 5,
        updated_at: '2026-04-29T01:00:00Z',
      }
      useJobStore.getState().applyJobUpdate(update)

      const { jobs } = useJobStore.getState()
      expect(jobs).toHaveLength(1)
      expect(jobs[0].id).toBe('unknown')
      expect(jobs[0].status).toBe('processing')
    })

    it('returns a new array reference (immutable update)', () => {
      const original = [makeJob({ id: 'j1' })]
      useJobStore.getState().setJobs(original)
      const beforeRef = useJobStore.getState().jobs

      useJobStore.getState().applyJobUpdate({
        id: 'j1',
        status: 'processing',
        phase: 'transcribing',
        progress: 50,
        updated_at: '2026-04-29T02:00:00Z',
      })

      const afterRef = useJobStore.getState().jobs
      expect(afterRef).not.toBe(beforeRef)
    })
  })

  describe('setConnected', () => {
    it('flips the isConnected boolean', () => {
      expect(useJobStore.getState().isConnected).toBe(false)
      useJobStore.getState().setConnected(true)
      expect(useJobStore.getState().isConnected).toBe(true)
      useJobStore.getState().setConnected(false)
      expect(useJobStore.getState().isConnected).toBe(false)
    })
  })
})

describe('useJobStore — markEventReceived', () => {
  beforeEach(() => {
    useJobStore.setState({ jobs: [], isConnected: false, lastEventAt: null })
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-30T12:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('defaults lastEventAt to null', () => {
    expect(useJobStore.getState().lastEventAt).toBeNull()
  })

  it('sets lastEventAt to Date.now() when called', () => {
    useJobStore.getState().markEventReceived()
    expect(useJobStore.getState().lastEventAt).toBe(Date.parse('2026-04-30T12:00:00Z'))
  })

  it('updates lastEventAt to the latest call timestamp', () => {
    useJobStore.getState().markEventReceived()
    vi.setSystemTime(new Date('2026-04-30T12:00:30Z'))
    useJobStore.getState().markEventReceived()
    expect(useJobStore.getState().lastEventAt).toBe(Date.parse('2026-04-30T12:00:30Z'))
  })
})
