import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import {
  STALE_AMBER_MS,
  STALE_BANNER_MS,
  STALE_RED_MS,
  useConnectionStatus,
  useShowStaleBanner,
} from './useConnectionStatus'
import { useJobStore } from '@/store/jobStore'

describe('useConnectionStatus', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-30T12:00:00Z'))
    useJobStore.setState({ jobs: [], isConnected: false, lastEventAt: null })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns red when not connected', () => {
    useJobStore.setState({ isConnected: false, lastEventAt: null })
    const { result } = renderHook(() => useConnectionStatus())
    expect(result.current).toBe('red')
  })

  it('returns amber when connected but no events have arrived yet', () => {
    useJobStore.setState({ isConnected: true, lastEventAt: null })
    const { result } = renderHook(() => useConnectionStatus())
    expect(result.current).toBe('amber')
  })

  it('returns green when an event arrived within the amber threshold', () => {
    useJobStore.setState({ isConnected: true, lastEventAt: Date.now() })
    const { result } = renderHook(() => useConnectionStatus())
    expect(result.current).toBe('green')
  })

  it('transitions green → amber once the amber threshold is crossed', () => {
    useJobStore.setState({ isConnected: true, lastEventAt: Date.now() })
    const { result } = renderHook(() => useConnectionStatus())
    expect(result.current).toBe('green')
    act(() => {
      vi.advanceTimersByTime(STALE_AMBER_MS + 100)
    })
    expect(result.current).toBe('amber')
  })

  it('transitions amber → red once the red threshold is crossed', () => {
    useJobStore.setState({ isConnected: true, lastEventAt: Date.now() })
    const { result } = renderHook(() => useConnectionStatus())
    act(() => {
      vi.advanceTimersByTime(STALE_RED_MS + 100)
    })
    expect(result.current).toBe('red')
  })

  it('returns to green immediately after a fresh event', () => {
    useJobStore.setState({ isConnected: true, lastEventAt: Date.now() })
    const { result } = renderHook(() => useConnectionStatus())
    act(() => {
      vi.advanceTimersByTime(STALE_RED_MS + 100)
    })
    expect(result.current).toBe('red')
    act(() => {
      useJobStore.setState({ lastEventAt: Date.now() })
      vi.advanceTimersByTime(1100) // force one tick
    })
    expect(result.current).toBe('green')
  })
})

describe('useShowStaleBanner', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-30T12:00:00Z'))
    useJobStore.setState({ jobs: [], isConnected: false, lastEventAt: null })
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns true immediately when isConnected is false', () => {
    useJobStore.setState({ isConnected: false, lastEventAt: Date.now() })
    const { result } = renderHook(() => useShowStaleBanner())
    expect(result.current).toBe(true)
  })

  it('returns false when no events have arrived yet but the connection is up', () => {
    useJobStore.setState({ isConnected: true, lastEventAt: null })
    const { result } = renderHook(() => useShowStaleBanner())
    expect(result.current).toBe(false)
  })

  it('flips to true once the banner threshold is crossed', () => {
    useJobStore.setState({ isConnected: true, lastEventAt: Date.now() })
    const { result } = renderHook(() => useShowStaleBanner())
    expect(result.current).toBe(false)
    act(() => {
      vi.advanceTimersByTime(STALE_BANNER_MS + 100)
    })
    expect(result.current).toBe(true)
  })

  it('returns false again after a fresh event', () => {
    useJobStore.setState({ isConnected: true, lastEventAt: Date.now() })
    const { result } = renderHook(() => useShowStaleBanner())
    act(() => {
      vi.advanceTimersByTime(STALE_BANNER_MS + 100)
    })
    expect(result.current).toBe(true)
    act(() => {
      useJobStore.setState({ lastEventAt: Date.now() })
      vi.advanceTimersByTime(1100)
    })
    expect(result.current).toBe(false)
  })
})
