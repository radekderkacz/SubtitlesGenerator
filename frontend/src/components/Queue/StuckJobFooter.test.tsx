import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import StuckJobFooter from './StuckJobFooter'
import { makeJob } from '@/test-utils/mockJob'

describe('StuckJobFooter', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-29T12:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('hides for non-processing jobs', () => {
    for (const status of ['queued', 'completed', 'failed', 'cancelled'] as const) {
      const { unmount } = render(
        <StuckJobFooter
          job={makeJob({
            status,
            updated_at: '2026-04-29T11:00:00Z',
          })}
        />,
      )
      expect(screen.queryByText(/Job appears stuck/)).not.toBeInTheDocument()
      unmount()
    }
  })

  it('hides when the job updated less than 30 minutes ago', () => {
    render(
      <StuckJobFooter
        job={makeJob({
          status: 'processing',
          updated_at: '2026-04-29T11:50:00Z', // 10 min ago
        })}
      />,
    )
    expect(screen.queryByText(/Job appears stuck/)).not.toBeInTheDocument()
  })

  it('shows when the job updated more than 30 minutes ago', () => {
    render(
      <StuckJobFooter
        job={makeJob({
          status: 'processing',
          updated_at: '2026-04-29T11:25:00Z', // 35 min ago
        })}
      />,
    )
    expect(screen.getByText(/Job appears stuck/)).toBeInTheDocument()
  })

  it('appears after time advances past the threshold', () => {
    render(
      <StuckJobFooter
        job={makeJob({
          status: 'processing',
          updated_at: '2026-04-29T11:50:00Z', // 10 min ago
        })}
      />,
    )
    expect(screen.queryByText(/Job appears stuck/)).not.toBeInTheDocument()
    // Jump forward 22 minutes — now updated_at is 32 min ago
    act(() => {
      vi.advanceTimersByTime(22 * 60 * 1000)
    })
    expect(screen.getByText(/Job appears stuck/)).toBeInTheDocument()
  })
})
