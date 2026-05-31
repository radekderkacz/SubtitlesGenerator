import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useIsStaleQueued } from './useIsStaleQueued'
import { makeJob } from '@/test-utils/mockJob'

describe('useIsStaleQueued', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-29T12:00:00Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns true on the first render when the row is already stale', () => {
    // useSyncExternalStore calls getSnapshot synchronously on every render
    // (not just after the first subscribe tick), so a row that was already
    // stale at mount time flips true immediately — no flicker, no delay.
    const ancient = '2024-01-01T00:00:00Z'
    const { result } = renderHook(() =>
      useIsStaleQueued(makeJob({ status: 'queued', updated_at: ancient })),
    )
    expect(result.current).toBe(true)
  })

  it('returns true once a queued row has been untouched >30s', () => {
    const { result } = renderHook(() =>
      useIsStaleQueued(
        makeJob({ status: 'queued', updated_at: '2026-04-29T11:59:00Z' }),
      ),
    )
    // Tick past the subscribe interval so useSyncExternalStore re-reads.
    act(() => {
      vi.advanceTimersByTime(600)
    })
    expect(result.current).toBe(true)
  })

  it('stays false for a queued row that is younger than the threshold', () => {
    const { result } = renderHook(() =>
      useIsStaleQueued(
        makeJob({ status: 'queued', updated_at: '2026-04-29T11:59:50Z' }),
      ),
    )
    act(() => {
      vi.advanceTimersByTime(600)
    })
    // 10s gap, threshold is 30s, so still false.
    expect(result.current).toBe(false)
  })

  it('flips true exactly when the threshold elapses', () => {
    // Row was updated at 11:59:30 — at "now" the gap is 30s. Advance one
    // more tick and the gap is 30.5s, which crosses the threshold.
    const { result } = renderHook(() =>
      useIsStaleQueued(
        makeJob({ status: 'queued', updated_at: '2026-04-29T11:59:30Z' }),
      ),
    )
    // Immediately false (gap = exactly 30s, threshold is >=30s — actually equals threshold)
    act(() => {
      vi.advanceTimersByTime(600)
    })
    expect(result.current).toBe(true)
  })

  it('returns false for non-queued statuses no matter how old', () => {
    for (const status of ['processing', 'failed', 'completed', 'cancelled'] as const) {
      const { result, unmount } = renderHook(() =>
        useIsStaleQueued(
          makeJob({ status, updated_at: '2020-01-01T00:00:00Z' }),
        ),
      )
      act(() => {
        vi.advanceTimersByTime(600)
      })
      expect(result.current).toBe(false)
      unmount()
    }
  })

  it('handles an unparseable updated_at gracefully (false)', () => {
    const { result } = renderHook(() =>
      useIsStaleQueued(
        makeJob({ status: 'queued', updated_at: 'not-a-date' }),
      ),
    )
    act(() => {
      vi.advanceTimersByTime(600)
    })
    expect(result.current).toBe(false)
  })
})
