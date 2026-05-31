import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ScheduleBuilder from './ScheduleBuilder'
import type { Schedule } from '@/types/api'

// Mock previewCron
vi.mock('@/lib/api', () => ({
  previewCron: vi.fn().mockResolvedValue({
    next_fires: [
      '2026-05-22T03:00:00+00:00',
      '2026-05-23T03:00:00+00:00',
      '2026-05-24T03:00:00+00:00',
    ],
  }),
}))

const mockOnChange = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ScheduleBuilder', () => {
  it('renders mode selector', () => {
    const value: Schedule = { mode: 'daily', time: '03:00' }
    render(<ScheduleBuilder value={value} onChange={mockOnChange} />)
    // The mode label appears as text in the schedule section
    expect(screen.getByText('Schedule')).toBeInTheDocument()
  })

  it('renders time input for daily mode', () => {
    const value: Schedule = { mode: 'daily', time: '03:00' }
    render(<ScheduleBuilder value={value} onChange={mockOnChange} />)
    const timeInput = screen.getByDisplayValue('03:00')
    expect(timeInput).toBeInTheDocument()
  })

  it('calls onChange with new time when time input changes', () => {
    const value: Schedule = { mode: 'daily', time: '03:00' }
    render(<ScheduleBuilder value={value} onChange={mockOnChange} />)
    const timeInput = screen.getByDisplayValue('03:00')
    fireEvent.change(timeInput, { target: { value: '06:00' } })
    expect(mockOnChange).toHaveBeenCalledWith({ mode: 'daily', time: '06:00' })
  })

  it('renders every-N-hours controls for hourly mode', () => {
    const value: Schedule = { mode: 'hourly', every_n_hours: 6 }
    render(<ScheduleBuilder value={value} onChange={mockOnChange} />)
    // "Every ... hours" text appears for hourly mode
    expect(screen.getByText('Every')).toBeInTheDocument()
    expect(screen.getByText('hours')).toBeInTheDocument()
  })

  it('does NOT show cron expression in the DOM', () => {
    const value: Schedule = { mode: 'daily', time: '03:00' }
    render(<ScheduleBuilder value={value} onChange={mockOnChange} />)
    // Cron strings like "0 3 * * *" must NOT appear
    expect(screen.queryByText(/\* \* \*/)).toBeNull()
  })

  it('shows next 3 runs after debounce', async () => {
    const value: Schedule = { mode: 'daily', time: '03:00' }
    render(<ScheduleBuilder value={value} onChange={mockOnChange} />)
    await waitFor(() => {
      expect(screen.getByText(/Next 3 runs/i)).toBeInTheDocument()
    }, { timeout: 2000 })
  })
})
