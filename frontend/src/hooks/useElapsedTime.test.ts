import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useElapsedTime } from './useElapsedTime'

describe('useElapsedTime', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-29T12:00:30Z'))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns current elapsed when endISO is null', () => {
    const { result } = renderHook(() =>
      useElapsedTime('2026-04-29T12:00:00Z', null),
    )
    expect(result.current).toBe('30s')
  })

  it('updates each second while endISO is null', () => {
    const { result } = renderHook(() =>
      useElapsedTime('2026-04-29T12:00:00Z', null),
    )
    expect(result.current).toBe('30s')
    act(() => {
      vi.advanceTimersByTime(5000)
    })
    expect(result.current).toBe('35s')
  })

  it('returns static elapsed when endISO is set', () => {
    const { result } = renderHook(() =>
      useElapsedTime('2026-04-29T12:00:00Z', '2026-04-29T12:01:15Z'),
    )
    expect(result.current).toBe('1m 15s')
    act(() => {
      vi.advanceTimersByTime(10_000)
    })
    expect(result.current).toBe('1m 15s')
  })

  it('cleans up interval on unmount', () => {
    const { unmount } = renderHook(() =>
      useElapsedTime('2026-04-29T12:00:00Z', null),
    )
    expect(vi.getTimerCount()).toBe(1)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not start an interval when endISO is already set on mount', () => {
    renderHook(() =>
      useElapsedTime('2026-04-29T12:00:00Z', '2026-04-29T12:00:15Z'),
    )
    expect(vi.getTimerCount()).toBe(0)
  })

  it('returns "0s" instead of NaN for an invalid startISO', () => {
    const { result } = renderHook(() => useElapsedTime('not-a-date', null))
    expect(result.current).toBe('0s')
  })

  it('returns "0s" instead of NaN for an invalid endISO', () => {
    const { result } = renderHook(() =>
      useElapsedTime('2026-04-29T12:00:00Z', 'not-a-date'),
    )
    expect(result.current).toBe('0s')
  })
})
