import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import ConnectionBanner from './ConnectionBanner'
import { useJobStore } from '@/store/jobStore'
import { STALE_BANNER_MS } from '@/hooks/useConnectionStatus'

describe('ConnectionBanner', () => {
  // jsdom won't let us assign window.location.reload directly, but
  // Object.defineProperty does. Restore in afterEach.
  let originalLocation: Location
  let reloadMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-30T12:00:00Z'))
    useJobStore.setState({ jobs: [], isConnected: true, lastEventAt: Date.now() })

    reloadMock = vi.fn()
    originalLocation = window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, reload: reloadMock },
    })
  })

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation,
    })
    vi.useRealTimers()
  })

  it('renders nothing when the connection is fresh', () => {
    render(<ConnectionBanner />)
    expect(screen.queryByTestId('connection-banner')).not.toBeInTheDocument()
  })

  it('renders the banner when staleness exceeds the threshold', () => {
    render(<ConnectionBanner />)
    act(() => {
      vi.advanceTimersByTime(STALE_BANNER_MS + 100)
    })
    expect(screen.getByTestId('connection-banner')).toBeInTheDocument()
    // New copy nudges the user toward the refresh affordance.
    expect(screen.getByText(/Live updates have stopped/)).toBeInTheDocument()
  })

  it('renders the banner immediately when isConnected is false', () => {
    useJobStore.setState({ isConnected: false })
    render(<ConnectionBanner />)
    expect(screen.getByTestId('connection-banner')).toBeInTheDocument()
  })

  it('hides again after a fresh event arrives', () => {
    render(<ConnectionBanner />)
    act(() => {
      vi.advanceTimersByTime(STALE_BANNER_MS + 100)
    })
    expect(screen.getByTestId('connection-banner')).toBeInTheDocument()
    act(() => {
      useJobStore.setState({ lastEventAt: Date.now() })
      vi.advanceTimersByTime(1100)
    })
    expect(screen.queryByTestId('connection-banner')).not.toBeInTheDocument()
  })

  it('exposes a Refresh button that hard-reloads the page', () => {
    // Disconnect immediately so the banner renders with the action affordance.
    useJobStore.setState({ isConnected: false })
    render(<ConnectionBanner />)
    const refresh = screen.getByRole('button', { name: /refresh/i })
    expect(refresh).toBeInTheDocument()
    expect(reloadMock).not.toHaveBeenCalled()
    fireEvent.click(refresh)
    expect(reloadMock).toHaveBeenCalledTimes(1)
  })
})
